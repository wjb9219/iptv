# -*- coding: utf-8 -*-
"""境外候选测活：NAS 侧跑，低并发 + 失败项二次复核"""
import json, os, ssl, time, urllib.request, urllib.error
import concurrent.futures as cf

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
HDR = {'User-Agent': UA, 'Accept': '*/*'}
CAND = os.environ.get('CAND', 'cand_intl.json')
PROBE_OUT = os.environ.get('PROBE_OUT', 'pintl_probe.json')
T = 12
W = int(os.environ.get('PROBE_W', '20'))


def once(u, t=T):
    t0 = time.time()
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers=HDR), timeout=t, context=CTX)
        raw = r.read(20480)
        ms = int((time.time() - t0) * 1000)
        if not raw:
            return False, ms, 'empty'
        if raw[:1] == b'\x47' and len(raw) > 1000:
            return True, ms, 'ts'
        if raw[:3] == b'FLV':
            return True, ms, 'flv'
        if raw[4:8] == b'ftyp' or raw[:4] == b'\x1a\x45\xdf\xa3':
            return True, ms, 'mp4'
        if raw[:4] in (b'\x00\x00\x01\xba', b'\x00\x00\x01\xb3'):
            return True, ms, 'ps'
        text = raw.decode('utf-8', 'ignore')
        if '#EXTM3U' in text and ('#EXTINF' in text or '#EXT-X-STREAM-INF' in text):
            # 主清单里若全是外省/无效子清单也算通过，只要清单本身合法
            return True, ms, 'hls'
        if '<MPD' in text[:400] or '<mpd' in text[:400]:
            return True, ms, 'dash'
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


def ensure_cand():
    if os.path.exists(CAND):
        return
    import gzip, shutil
    gz = CAND + '.gz'
    if os.path.exists(gz):
        with gzip.open(gz, 'rb') as f, open(CAND, 'wb') as g:
            shutil.copyfileobj(f, g)
        print('已解压候选清单', flush=True)


def main():
    ensure_cand()
    cand = json.load(open(CAND, encoding='utf-8'))
    urls = sorted({c['url'] for c in cand})
    out = {}
    try:
        out = json.load(open(PROBE_OUT, encoding='utf-8'))
    except Exception:
        out = {}

    def job(u):
        ok, ms, kind = once(u)
        return u, ok, ms, kind

    todo = [u for u in urls if not out.get(u, {}).get('ok')]
    print('待测 %d 条（已有结果 %d，可播 %d），线程 %d'
          % (len(todo), len(out), sum(1 for v in out.values() if v['ok']), W), flush=True)
    t0 = time.time()
    done = 0
    with cf.ThreadPoolExecutor(max_workers=W) as ex:
        fut = {ex.submit(job, u): u for u in todo}
        for f in cf.as_completed(fut):
            u, ok, ms, kind = f.result()
            out[u] = {'ok': ok, 'ms': ms, 'kind': kind}
            done += 1
            if done % 200 == 0:
                good = sum(1 for v in out.values() if v['ok'])
                print('  %d/%d 通过 %d  %.0fs' % (done, len(todo), good, time.time() - t0), flush=True)
                json.dump(out, open(PROBE_OUT, 'w', encoding='utf-8'), ensure_ascii=False)

    # 失败项二次并发低档复核，避免误杀
    bad = [u for u in urls if not out.get(u, {}).get('ok')]
    print('首轮失败 %d，二次复核…' % len(bad), flush=True)
    W2 = max(4, W // 3)
    with cf.ThreadPoolExecutor(max_workers=W2) as ex:
        for u, ok, ms, kind in ex.map(lambda x: job2(x), bad):
            if ok:
                out[u] = {'ok': True, 'ms': ms, 'kind': kind + '/retry'}

    json.dump(out, open(PROBE_OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    good = sum(1 for v in out.values() if v['ok'])
    print('完成：%d 条可播 / %d 条' % (good, len(urls)), flush=True)


def job2(u):
    return (u,) + once(u, T + 4)


if __name__ == '__main__':
    main()
