# -*- coding: utf-8 -*-
"""测活 + 测速（带缓存退避 / 按 host 探路熔断，压住单轮耗时）

相比旧版的改动：
1. URL 先做百分号编码 —— 修中文/空格导致的 UnicodeEncodeError 误判（曾误杀整批台）
2. probe_cache.json 记住每条线路历史；失败线路按 0/0/3天/7天 退避，不再每轮白跑
3. 探测分两级：
   - 现役线路逐条测（绝不断言）
   - 候选/新台按 host 探路：每个 host 先测 2 条，都死就跳过这个 host 剩下的，
     死链源往往一个 IP 上挂几百条，这一刀能砍掉大半无效请求
4. 活线路读 2 秒算带宽 KB/s，供 assemble 做质量门槛，把「连得上但卡」的剔掉
5. 每批结果即时落盘，万一超时被杀也不丢整轮
"""
import json, time, ssl, os, socket, threading, urllib.request, urllib.error, urllib.parse
import concurrent.futures as cf

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
HDR = {'User-Agent': UA, 'Accept': '*/*'}

W1 = max(40, int(os.environ.get('PROBE_W1', '40')))   # 首轮并发（低于 40 不干，20 线程要跑 26 分钟）
T1 = min(5.0, float(os.environ.get('PROBE_T1', '4.5')))  # 首轮超时（首字节 4.5s 不出基本没戏）
W2 = int(os.environ.get('PROBE_W2', '20'))        # 复核并发
T2 = float(os.environ.get('PROBE_T2', '8'))       # 复核超时
WS = max(40, int(os.environ.get('PROBE_WS', '40')))   # 测速并发
SPT = float(os.environ.get('PROBE_SPT', '2.0'))   # 测速读多久
CAP = int(os.environ.get('PROBE_SPCAP', '1200000'))
DO_SPEED = os.environ.get('PROBE_SPEED', '1') == '1'
MAXTODO = int(os.environ.get('PROBE_MAXTODO', '14000'))
PROBE_N = int(os.environ.get('PROBE_PERHOST', '2'))   # 每个 host 先探几条

CACHE_F = 'probe_cache.json'
OUT_F = 'probe_all.json'
BACKOFF = [0, 0, 3 * 86400, 7 * 86400, 14 * 86400]
OK_REUSE = 86400
SAFE = ":/?&=%@+,;~!*()[]'#"
HARD_DEAD = ('timeout', 'reset', 'refused', 'dns', 'ssl')   # 这些原因可触发 host 熔断

_lock = threading.Lock()


def log(m):
    print('[%s] %s' % (time.strftime('%H:%M:%S'), m), flush=True)


def enc(u):
    try:
        return urllib.parse.quote(u, safe=SAFE)
    except Exception:
        return u


def hostof(u):
    try:
        return urllib.parse.urlsplit(enc(u)).netloc.lower()
    except Exception:
        return '?'


def classify(raw, ct, status):
    if not raw:
        return False, 'empty'
    if raw[:1] == b'\x47' and len(raw) > 1000:
        return True, 'ts'
    if raw[:3] == b'FLV':
        return True, 'flv'
    if raw[4:8] == b'ftyp' or raw[:4] == b'\x1a\x45\xdf\xa3':
        return True, 'mp4'
    if raw[:4] in (b'\x00\x00\x01\xba', b'\x00\x00\x01\xb3'):
        return True, 'ps'
    text = raw.decode('utf-8', 'ignore')
    if '#EXTM3U' in text and ('#EXTINF' in text or '#EXT-X-STREAM-INF' in text
                              or '#EXT-X-TARGETDURATION' in text):
        return True, 'hls'
    if '<MPD' in text[:400] or '<mpd' in text[:400]:
        return True, 'dash'
    if status in (200, 206) and ('video/' in ct or 'audio/' in ct or 'mpegurl' in ct
                                 or 'octet-stream' in ct):
        return True, 'ct:' + ct.split(';')[0]
    if status in (200, 206) and len(raw) > 4000 and '<' not in text[:60]:
        return True, 'bin'
    return False, 'bad:%s:%dB' % (ct.split(';')[0] or '-', len(raw))


def short_err(e):
    if isinstance(e, urllib.error.HTTPError):
        return 'http%d' % e.code
    if isinstance(e, (socket.timeout, TimeoutError)):
        return 'timeout'
    if isinstance(e, urllib.error.URLError):
        rs = getattr(e, 'reason', None)
        if isinstance(rs, (socket.timeout, TimeoutError)):
            return 'timeout'
        nm = type(rs).__name__ if rs is not None else 'URLError'
        s = str(rs)
        if 'Name' in nm or 'getaddrinfo' in s or 'Temporary failure' in s:
            return 'dns'
        if 'Refused' in nm or 'refused' in s:
            return 'refused'
        if 'Reset' in nm or 'Disconnected' in nm or 'Broken' in nm:
            return 'reset'
        if 'SSL' in nm or 'Certificate' in nm:
            return 'ssl'
        return 'urlerr:' + nm
    nm = type(e).__name__
    if 'SSL' in nm:
        return 'ssl'
    if 'Reset' in nm or 'Disconnected' in nm or 'Broken' in nm:
        return 'reset'
    return nm


def once(u, t=T1):
    t0 = time.time()
    try:
        r = urllib.request.urlopen(urllib.request.Request(enc(u), headers=HDR),
                                  timeout=t, context=CTX)
        raw = r.read(32768)
        ms = int((time.time() - t0) * 1000)
        ok, how = classify(raw, (r.headers.get('Content-Type') or '').lower(), r.status)
        return {'ok': ok, 'ms': ms, 'how': how, 'kb': 0}
    except Exception as e:
        return {'ok': False, 'ms': int((time.time() - t0) * 1000), 'how': short_err(e), 'kb': 0}


def first_line(txt):
    for ln in txt.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith('#'):
            return ln
    return ''


def measure(u, how):
    """读 SPT 秒，返回 KB/s；-1 表示测不出（读到的字节太少，不参与质量判定）"""
    base = enc(u)
    target = base
    t1 = time.time()
    total = 0
    try:
        if how == 'hls' or how.startswith('ct:application/vnd.apple'):
            txt = urllib.request.urlopen(urllib.request.Request(base, headers=HDR),
                                         timeout=6, context=CTX).read(262144).decode('utf-8', 'ignore')
            seg = first_line(txt)
            if not seg:
                return -1
            target = urllib.parse.urljoin(base, seg)
            if '#EXT-X-STREAM-INF' in txt:
                sub = urllib.request.urlopen(urllib.request.Request(enc(target), headers=HDR),
                                             timeout=6, context=CTX).read(262144).decode('utf-8', 'ignore')
                seg2 = first_line(sub)
                if not seg2:
                    return -1
                target = urllib.parse.urljoin(target, seg2)
        t1 = time.time()
        r = urllib.request.urlopen(urllib.request.Request(enc(target), headers=HDR),
                                   timeout=SPT + 3, context=CTX)
        while time.time() - t1 < SPT and total < CAP:
            b = r.read(65536)
            if not b:
                break
            total += len(b)
    except Exception:
        pass
    el = time.time() - t1
    if total < 120 * 1024:
        return -1
    return int(total / 1024.0 / max(el, 0.25))


def flush(res, cache, final=False):
    """边测边落盘：超时被杀也不至于整轮白跑"""
    out = dict(cache)
    for u, v in res.items():
        c = cache.get(u, {})
        if v['ok']:
            out[u] = {'t': int(time.time()), 'ok': True, 'fails': 0, 'ms': v['ms'],
                      'how': v['how'], 'kb': v.get('kb', 0)}
        else:
            out[u] = {'t': int(time.time()), 'ok': False,
                      'fails': int(c.get('fails', 0)) + 1, 'ms': 0,
                      'how': v['how'], 'kb': 0}
    try:
        json.dump(out, open(OUT_F + '.tmp', 'w', encoding='utf-8'), ensure_ascii=False)
        os.replace(OUT_F + '.tmp', OUT_F)
    except Exception:
        pass
    return out


def sweep(urls, workers, tt, tag='', res=None):
    res = res if res is not None else {}
    if not urls:
        return res
    t0 = time.time()
    n = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(once, u, tt): u for u in urls}
        for f in cf.as_completed(futs):
            res[futs[f]] = f.result()
            n += 1
            if n % 500 == 0:
                log('    %s %d/%d (%.0fs)' % (tag, n, len(urls), time.time() - t0))
    return res


def load(p, dflt):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return dflt


def main():
    t_all = time.time()
    cand = load('cand_all.json', {'extra': {}, 'new': {}})
    cache = load(CACHE_F, {})
    pools = load('pools.json', {'pools': {}}).get('pools', {})
    retry = load('retry_dead.json', {})

    live = set()
    for ch in pools.values():
        for s in ch.get('srcs', []):
            if s.get('t') == 'url' and s.get('u'):
                live.add(s['u'])

    others = set()
    for lst in cand.get('extra', {}).values():
        others.update(lst)
    for v in cand.get('new', {}).values():
        others.update(v.get('urls', []))
    for v in retry.values():
        others.update(v.get('urls', []))

    now = time.time()
    todo_live, todo_other = [], []
    reused = 0

    for u in live:
        todo_live.append(u)
    for u in others:
        if u in live:
            continue
        c = cache.get(u)
        if c:
            age = now - c.get('t', 0)
            f = int(c.get('fails', 0))
            if c.get('ok') and age < OK_REUSE:
                reused += 1; continue
            if (not c.get('ok')) and age < BACKOFF[min(f, len(BACKOFF) - 1)]:
                reused += 1; continue
        todo_other.append(u)

    todo_other.sort(key=lambda u: (0 if cache.get(u, {}).get('ok') else 1,))
    room = max(0, MAXTODO - len(todo_live))
    if len(todo_other) > room:
        log('候选 %d 条超预算，本轮只测前 %d 条（其余下轮）' % (len(todo_other), room))
        todo_other = todo_other[:room]

    log('现役 %d + 候选 %d，复用缓存 %d（%d线程/%.0fs）'
        % (len(todo_live), len(todo_other), reused, W1, T1))

    res = {}
    # ① 现役线路：逐条实测，一条都不能少
    sweep(todo_live, W1, T1, tag='现役', res=res)
    n_ok = sum(1 for u in todo_live if res.get(u, {}).get('ok'))
    log('现役通过 %d/%d（%.0fs）' % (n_ok, len(todo_live), time.time() - t_all))
    cache = flush(res, cache)

    # ② 候选线路：按 host 探路，探不通的 host 剩下的直接判死，不再浪费请求
    byhost = {}
    for u in todo_other:
        byhost.setdefault(hostof(u), []).append(u)
    heads = [u for lst in byhost.values() for u in lst[:PROBE_N]]
    log('候选 %d 条 / %d 个 host，先探路 %d 条' % (len(todo_other), len(byhost), len(heads)))
    sweep(heads, W1, T1, tag='探路', res=res)
    dead_host = set()
    for h, lst in byhost.items():
        head = lst[:PROBE_N]
        if len(lst) > PROBE_N and head and all(
                (not res.get(u, {}).get('ok')) and res.get(u, {}).get('how', '') in HARD_DEAD
                for u in head):
            dead_host.add(h)
    skipped = 0
    for h in dead_host:
        for u in byhost[h][PROBE_N:]:
            res[u] = {'ok': False, 'ms': 0, 'how': 'host_dead', 'kb': 0}
            skipped += 1
    log('熔断 %d 个 host，省掉 %d 条请求' % (len(dead_host), skipped))

    rest = [u for h, lst in byhost.items() if h not in dead_host for u in lst[PROBE_N:]]
    log('剩余候选 %d 条（%.0fs）' % (len(rest), time.time() - t_all))
    sweep(rest, W1, T1, tag='候选', res=res)
    cache = flush(res, cache)
    log('首轮合计通过 %d / %d，累计 %.0fs'
        % (sum(1 for v in res.values() if v['ok']), len(res), time.time() - t_all))

    # ③ 复核：只救现役线路的失败项（上轮是活的、或首次运行没记录），候选死链不复核
    soft = [u for u in todo_live if not res.get(u, {}).get('ok')
            and cache.get(u, {}).get('ok', True)]
    if soft:
        log('复核现役掉线 %d 条（%d线程/%.0fs）' % (len(soft), W2, T2))
        r2 = sweep(soft, W2, T2, tag='复核')
        revived = 0
        for u in soft:
            if r2[u]['ok']:
                res[u] = r2[u]; revived += 1
        log('复核救回 %d 条' % revived)
        cache = flush(res, cache)
    else:
        log('无需复核')

    # ④ 测速
    live_now = [u for u, v in res.items() if v['ok']]
    if DO_SPEED and live_now:
        log('测速 %d 条（%d线程，每条 %.1fs）' % (len(live_now), WS, SPT))
        t_sp = time.time()
        done = [0]
        with cf.ThreadPoolExecutor(max_workers=WS) as ex:
            futs = {ex.submit(measure, u, res[u]['how']): u for u in live_now}
            for f in cf.as_completed(futs):
                u = futs[f]
                try:
                    res[u]['kb'] = f.result()
                except Exception:
                    res[u]['kb'] = -1
                done[0] += 1
                if done[0] % 500 == 0:
                    log('    测速 %d/%d (%.0fs)' % (done[0], len(live_now), time.time() - t_sp))
                    cache = flush(res, cache)
        log('测速完成 %.0fs' % (time.time() - t_sp))

    cache = flush(res, cache, final=True)
    json.dump(cache, open(CACHE_F, 'w', encoding='utf-8'), ensure_ascii=False)

    final = load(OUT_F, {})
    okn = sum(1 for v in final.values() if v.get('ok'))
    kbs = sorted(v.get('kb', 0) for v in final.values() if v.get('ok') and v.get('kb', 0) > 0)
    if kbs:
        def pct(p):
            return kbs[min(len(kbs) - 1, int(len(kbs) * p))]
        log('带宽分布（%d 条实测）：P10 %d / P25 %d / P50 %d / P75 %d / P90 %d KB/s'
            % (len(kbs), pct(.10), pct(.25), pct(.50), pct(.75), pct(.90)))
    log('合计可用 URL %d / %d，总用时 %.0fs' % (okn, len(final), time.time() - t_all))


if __name__ == '__main__':
    main()
