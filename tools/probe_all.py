# -*- coding: utf-8 -*-
"""测活 + 测速（带缓存退避，压住单轮耗时）

相比旧版的四处改动：
1. URL 先做百分号编码 —— 修中文/空格导致的 UnicodeEncodeError 误判（一次误杀过整批台）
2. probe_cache.json 记住每条线路的历史结果；失败线路按 0/0/3天/7天 退避重测，不再每轮白跑
3. 首轮 40 线程 / 5s；只有「现役线路首轮失败」才复核（16 线程 / 8s），候选死链一律不复核
4. 活线路再读 3 秒算实际带宽 KB/s，供 assemble 做质量门槛，把「连得上但卡」的剔掉
"""
import json, time, ssl, os, socket, urllib.request, urllib.error, urllib.parse
import concurrent.futures as cf

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
HDR = {'User-Agent': UA, 'Accept': '*/*'}

W1 = int(os.environ.get('PROBE_W1', '40'))        # 首轮并发
T1 = float(os.environ.get('PROBE_T1', '5'))       # 首轮超时
W2 = int(os.environ.get('PROBE_W2', '16'))        # 复核并发
T2 = float(os.environ.get('PROBE_T2', '8'))       # 复核超时
WS = int(os.environ.get('PROBE_WS', '24'))        # 测速并发
SPT = float(os.environ.get('PROBE_SPT', '3.0'))   # 测速读多久
CAP = int(os.environ.get('PROBE_SPCAP', '1500000'))
DO_SPEED = os.environ.get('PROBE_SPEED', '1') == '1'
BUDGET = int(os.environ.get('PROBE_BUDGET', '1500'))   # 首轮总时限（秒），超了就收
MAXTODO = int(os.environ.get('PROBE_MAXTODO', '14000'))

CACHE_F = 'probe_cache.json'
BACKOFF = [0, 0, 3 * 86400, 7 * 86400, 14 * 86400]     # 连续失败 n 次后的重测间隔
OK_REUSE = 86400                                        # 非现役线路「通过」结果复用 24h
SAFE = ":/?&=%@+,;~!*()[]'#"


def log(m):
    print('[%s] %s' % (time.strftime('%H:%M:%S'), m), flush=True)


def enc(u):
    try:
        return urllib.parse.quote(u, safe=SAFE)
    except Exception:
        return u


def classify(raw, ct, status):
    """返回 (ok, how)"""
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
        if 'Name' in nm or 'getaddrinfo' in str(rs):
            return 'dns'
        if 'Refused' in nm:
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
            if '#EXT-X-STREAM-INF' in txt:          # master playlist，再下钻一层
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
    if total < 150 * 1024:          # 太少，判断不了带宽（可能是短片段/预告片）
        return -1
    return int(total / 1024.0 / max(el, 0.25))


def sweep(urls, workers, tt, tag='', limit=BUDGET):
    res = {}
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
    out = {}
    todo_live, todo_other = [], []
    reused_ok = reused_fail = 0

    for u in live:
        todo_live.append(u)                     # 现役线路每轮必测
    for u in others:
        if u in live:
            continue
        c = cache.get(u)
        if c:
            age = now - c.get('t', 0)
            f = int(c.get('fails', 0))
            if c.get('ok') and age < OK_REUSE:
                out[u] = c; reused_ok += 1; continue
            if (not c.get('ok')) and age < BACKOFF[min(f, len(BACKOFF) - 1)]:
                out[u] = c; reused_fail += 1; continue
        todo_other.append(u)

    # 现役优先；候选按「历史通过过」优先，再截断到预算内
    todo_other.sort(key=lambda u: (0 if cache.get(u, {}).get('ok') else 1,))
    room = max(0, MAXTODO - len(todo_live))
    if len(todo_other) > room:
        log('候选 %d 条超预算，本轮只测前 %d 条（其余下轮）' % (len(todo_other), room))
        todo_other = todo_other[:room]
    todo = todo_live + todo_other

    log('现役 %d + 候选 %d = 待测 %d（复用缓存 活%d/死%d，%d线程/%.0fs）'
        % (len(todo_live), len(todo_other), len(todo), reused_ok, reused_fail, W1, T1))

    r1 = sweep(todo, W1, T1, tag='首轮')
    ok1 = [u for u, v in r1.items() if v['ok']]
    bad1 = [u for u, v in r1.items() if not v['ok']]
    log('首轮：通过 %d，失败 %d，用时 %.0fs' % (len(ok1), len(bad1), time.time() - t_all))

    # 复核：只救「现役且上轮是活的」——掉线才值得再看一眼
    soft = [u for u in bad1 if u in live and cache.get(u, {}).get('ok')]
    if soft:
        log('复核现役掉线 %d 条（%d线程/%.0fs）' % (len(soft), W2, T2))
        r2 = sweep(soft, W2, T2, tag='复核')
        revived = 0
        for u in soft:
            if r2[u]['ok']:
                r1[u] = r2[u]; revived += 1
        log('复核救回 %d 条' % revived)
    else:
        log('无需复核')

    # 测速：只测本轮真连上的，不测缓存
    live_now = [u for u, v in r1.items() if v['ok']]
    if DO_SPEED and live_now:
        log('测速 %d 条（%d线程，每条 %.1fs）' % (len(live_now), WS, SPT))
        t_sp = time.time()
        with cf.ThreadPoolExecutor(max_workers=WS) as ex:
            futs = {ex.submit(measure, u, r1[u]['how']): u for u in live_now}
            done = 0
            for f in cf.as_completed(futs):
                u = futs[f]
                try:
                    r1[u]['kb'] = f.result()
                except Exception:
                    r1[u]['kb'] = -1
                done += 1
                if done % 500 == 0:
                    log('    测速 %d/%d (%.0fs)' % (done, len(live_now), time.time() - t_sp))
        log('测速完成 %.0fs' % (time.time() - t_sp))

    # 落盘 + 更新缓存
    for u, v in r1.items():
        c = cache.get(u, {})
        if v['ok']:
            cache[u] = {'t': int(time.time()), 'ok': True, 'fails': 0, 'ms': v['ms'],
                        'how': v['how'], 'kb': v.get('kb', 0)}
        else:
            cache[u] = {'t': int(time.time()), 'ok': False,
                        'fails': int(c.get('fails', 0)) + 1, 'ms': 0,
                        'how': v['how'], 'kb': 0}
        out[u] = cache[u]

    json.dump(out, open('probe_all.json', 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(cache, open(CACHE_F, 'w', encoding='utf-8'), ensure_ascii=False)

    okn = sum(1 for v in out.values() if v.get('ok'))
    kbs = sorted(v.get('kb', 0) for v in out.values() if v.get('ok') and v.get('kb', 0) > 0)
    if kbs:
        def pct(p):
            return kbs[min(len(kbs) - 1, int(len(kbs) * p))]
        log('带宽分布（共 %d 条实测）：P10 %d / P25 %d / P50 %d / P75 %d / P90 %d KB/s'
            % (len(kbs), pct(.10), pct(.25), pct(.50), pct(.75), pct(.90)))
    log('合计可用 URL %d / %d，总用时 %.0fs' % (okn, len(out), time.time() - t_all))


if __name__ == '__main__':
    main()
