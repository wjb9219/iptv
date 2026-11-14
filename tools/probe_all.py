# -*- coding: utf-8 -*-
"""并发测活（两轮）：先小并发跑一遍，没过的再低并发复核一次，避免误杀
NAS 的网络栈扛不住长时间高并发，实测 80 线程会把大量能播的台判死。"""
import json, time, ssl, os, urllib.request, concurrent.futures as cf

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
HDR = {'User-Agent': UA, 'Accept': '*/*'}
W1 = int(os.environ.get('PROBE_W1', '12'))
W2 = int(os.environ.get('PROBE_W2', '6'))
T = float(os.environ.get('PROBE_T', '12'))


def once(u, t=T):
    t0 = time.time()
    try:
        req = urllib.request.Request(u, headers=HDR)
        r = urllib.request.urlopen(req, timeout=t, context=CTX)
        raw = r.read(20480)
        ms = int((time.time() - t0) * 1000)
        if not raw:
            return False, ms, 'empty'
        # 1) 裸流/容器格式：TS / FLV / MP4 / MPEG-PS
        if raw[:1] == b'\x47' and len(raw) > 1000:
            return True, ms, 'ts'
        if raw[:3] == b'FLV':
            return True, ms, 'flv'
        if raw[4:8] == b'ftyp' or raw[:4] == b'\x1a\x45\xdf\xa3':
            return True, ms, 'mp4'
        if raw[:4] == b'\x00\x00\x01\xba' or raw[:4] == b'\x00\x00\x01\xb3':
            return True, ms, 'ps'
        text = raw.decode('utf-8', 'ignore')
        # 2) HLS/DASH 清单
        if '#EXTM3U' in text and ('#EXTINF' in text or '#EXT-X-STREAM-INF' in text):
            return True, ms, 'hls'
        if '<MPD' in text[:400] or '<mpd' in text[:400]:
            return True, ms, 'dash'
        # 3) 服务端明确声明是媒体流，就认（含 flv/mp4/octet-stream 等）
        ct = (r.headers.get('Content-Type') or '').lower()
        if r.status in (200, 206) and ('video/' in ct or 'audio/' in ct or 'mpegurl' in ct
                                       or 'octet-stream' in ct):
            return True, ms, 'ct:' + ct.split(';')[0]
        if r.status in (200, 206) and len(raw) > 2000 and '<' not in text[:60]:
            return True, ms, 'bin'
        return False, ms, 'bad:%s:%dB' % (ct.split(';')[0] or '-', len(raw))
    except urllib.error.HTTPError as e:
        return False, 0, 'http%d' % e.code
    except Exception as e:
        return False, 0, type(e).__name__


def sweep(urls, workers):
    res = {}
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(once, u): u for u in urls}
        n = 0
        for f in cf.as_completed(futs):
            res[futs[f]] = f.result()
            n += 1
            if n % 400 == 0:
                print('    进度 %d/%d (%.0fs)' % (n, len(urls), time.time() - t0), flush=True)
    return res, time.time() - t0


if __name__ == '__main__':
    cand = json.load(open('cand_all.json', encoding='utf-8'))
    known = {}   # 每轮全量重测，不复用上轮结果，免得死链一直挂着

    urls = set()
    # 现役列表里的每一条线路都必须重测，否则源里一消失就被当死台删掉（真实踩过的坑）
    try:
        pools = json.load(open('pools.json', encoding='utf-8'))['pools']
        for ch in pools.values():
            for src in ch.get('srcs', []):
                if src.get('t') == 'url' and src.get('u'):
                    urls.add(src['u'])
    except Exception as e:
        print('读 pools.json 失败：%r' % e)
    for lst in cand['extra'].values():
        urls.update(lst)
    for v in cand['new'].values():
        urls.update(v['urls'])
    try:
        rd = json.load(open('retry_dead.json', encoding='utf-8'))
        for v in rd.values():
            urls.update(v.get('urls', []))
        print('重试名单 %d 个台也纳入本轮复测' % len(rd))
    except Exception:
        pass

    todo = sorted(urls)
    print('候选 URL %d 个，待测 %d 个（%d 线程）' % (len(urls), len(todo), W1))
    res = dict(known)
    first, el = sweep(todo, W1)
    res.update(first)
    ok1 = sum(1 for u in todo if first[u][0])
    fail = [u for u in todo if not first[u][0]]
    print('第一轮 %d 个待测，通过 %d，失败 %d（%.0fs）' % (len(todo), ok1, len(fail), el), flush=True)

    if fail:
        print('第二轮复核 %d 个失败项（%d 线程，避免误杀）' % (len(fail), W2), flush=True)
        second, el2 = sweep(fail, W2)
        revived = 0
        for u in fail:
            if second[u][0]:
                res[u] = second[u]; revived += 1
        print('复核救回 %d 个（%.0fs）' % (revived, el2))

    json.dump(res, open('probe_all.json', 'w', encoding='utf-8'), ensure_ascii=False)
    okn = sum(1 for u in urls if res.get(u, {}).get('ok'))
    print('合计可用 URL %d / %d' % (okn, len(urls)))
