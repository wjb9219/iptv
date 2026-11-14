# -*- coding: utf-8 -*-
"""并发测活：一次不过的进第二轮重试，避免误杀"""
import json, time, ssl, urllib.request, concurrent.futures as cf

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
HDR = {'User-Agent': UA, 'Accept': '*/*'}


def once(u, t=8):
    t0 = time.time()
    try:
        req = urllib.request.Request(u, headers=HDR)
        r = urllib.request.urlopen(req, timeout=t, context=CTX)
        raw = r.read(20480)
        ms = int((time.time() - t0) * 1000)
        if not raw:
            return False, ms, 'empty'
        if raw[:1] == b'\x47' and len(raw) > 1000:
            return True, ms, 'ts'
        s = raw.decode('utf-8', 'ignore')
        if '#EXTM3U' in s and ('#EXTINF' in s or '#EXT-X-STREAM-INF' in s):
            return True, ms, 'hls'
        if r.status in (200, 206) and len(raw) > 2000 and '<' not in s[:60]:
            return True, ms, 'bin'
        return False, ms, 'bad:%dB' % len(raw)
    except urllib.error.HTTPError as e:
        return False, 0, 'http%d' % e.code
    except Exception as e:
        return False, 0, type(e).__name__


def probe(u, tries=2):
    best = (False, 0, '')
    for i in range(tries):
        ok, ms, how = once(u)
        if ok:
            return (True, ms, how)
        best = (ok, ms, how)
    return best


if __name__ == '__main__':
    cand = json.load(open('cand_all.json', encoding='utf-8'))
    try:
        known = json.load(open('pool_probe.json', encoding='utf-8'))
    except Exception:
        known = {}
    try:
        known.update(json.load(open('probe_all.json', encoding='utf-8')))
    except Exception:
        pass
    urls = set()
    for lst in cand['extra'].values():
        urls.update(lst)
    for v in cand['new'].values():
        urls.update(v['urls'])
    # 之前判死的台也一起重测，别彻底放弃
    try:
        rd = json.load(open('retry_dead.json', encoding='utf-8'))
        for v in rd.values():
            urls.update(v.get('urls', []))
        print('重试名单 %d 个台也纳入本轮复测' % len(rd))
    except Exception:
        pass
    todo = sorted(u for u in urls if not known.get(u, {}).get('ok'))
    print('候选 URL %d 个，待测 %d 个' % (len(urls), len(todo)))
    res = dict(known)
    t0 = time.time()
    done = 0
    with cf.ThreadPoolExecutor(max_workers=80) as ex:
        futs = {ex.submit(probe, u): u for u in todo}
        for f in cf.as_completed(futs):
            u = futs[f]
            ok, ms, how = f.result()
            res[u] = {'ok': ok, 'ms': ms, 'how': how}
            done += 1
            if done % 500 == 0:
                print('  已测 %d/%d  (%.0fs)' % (done, len(todo), time.time() - t0), flush=True)
    json.dump(res, open('probe_all.json', 'w', encoding='utf-8'), ensure_ascii=False)
    okn = sum(1 for u in urls if res.get(u, {}).get('ok'))
    print('测完 %d 个 URL（%.0fs），可用 %d 个' % (len(urls), time.time() - t0, okn))
