# -*- coding: utf-8 -*-
"""广撒网抓源：多镜像多仓库，落盘为 _a_<key>.m3u"""
import ssl, os, urllib.request, concurrent.futures as cf

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'

S = {
    # iptv-org 国家/语言
    'org_cn': 'https://fastly.jsdelivr.net/gh/iptv-org/iptv@master/streams/cn.m3u',
    'org_hk': 'https://fastly.jsdelivr.net/gh/iptv-org/iptv@master/streams/hk.m3u',
    'org_tw': 'https://fastly.jsdelivr.net/gh/iptv-org/iptv@master/streams/tw.m3u',
    'org_mo': 'https://fastly.jsdelivr.net/gh/iptv-org/iptv@master/streams/mo.m3u',
    'org_sg': 'https://fastly.jsdelivr.net/gh/iptv-org/iptv@master/streams/sg.m3u',
    'org_my': 'https://fastly.jsdelivr.net/gh/iptv-org/iptv@master/streams/my.m3u',
    'org_us': 'https://fastly.jsdelivr.net/gh/iptv-org/iptv@master/streams/us.m3u',
    # 国内常用聚合
    'fmm_ipv4': 'https://fastly.jsdelivr.net/gh/fanmingming/live@main/tv/m3u/ipv4.m3u',
    'fmm_ipv6': 'https://fastly.jsdelivr.net/gh/fanmingming/live@main/tv/m3u/ipv6.m3u',
    'ssili': 'https://fastly.jsdelivr.net/gh/ssili126/tv@main/itvlist.m3u',
    'yuechan': 'https://fastly.jsdelivr.net/gh/YueChan/IPTV@main/live.m3u',
    'vb4': 'https://fastly.jsdelivr.net/gh/vbskycn/iptv@master/tv/iptv4.m3u',
    'dazui': 'https://fastly.jsdelivr.net/gh/imDazui/Tvlist-awesome-m3u-m3u8@master/m3u/%E5%9B%BD%E5%86%85%E7%94%B5%E8%A7%86%E5%8F%B0%E6%B5%8B%E8%AF%95.m3u',
    'aptv': 'https://fastly.jsdelivr.net/gh/Kimentanm/aptv@master/m3u/iptv.m3u',
    'zbe': 'https://fastly.jsdelivr.net/gh/zbefine/iptv@main/iptv.m3u',
    'kanglin': 'https://fastly.jsdelivr.net/gh/kanglin/iptv@main/iptv.m3u',
    'guovin': 'https://fastly.jsdelivr.net/gh/Guovin/iptv-api@gd/output/result.m3u',
    'hujing': 'https://fastly.jsdelivr.net/gh/hujingguang/ChinaIPTV@main/cnTV_AutoUpdate.m3u8',
    'qwert': 'https://fastly.jsdelivr.net/gh/qwerttvv/Beijing-IPTV@master/IPv4_Multicast.m3u',
    # 酒店/商源/杂源
    'kimwang': 'https://fastly.jsdelivr.net/gh/kimwang1978/collect-tv-txt@main/merged_output.m3u',
    'wcb1969': 'https://fastly.jsdelivr.net/gh/wcb1969/iptv@main/tv.m3u',
    'yan': 'https://fastly.jsdelivr.net/gh/yanhu2030/iptv@main/iptv.m3u',
    'iptvmate': 'https://fastly.jsdelivr.net/gh/iptvmate/iptvmate.github.io@main/playlist.m3u',
    'orgcn2': 'https://fastly.jsdelivr.net/gh/iptv-org/iptv@master/streams/cn_s.m3u',
    'fanming1': 'https://fastly.jsdelivr.net/gh/fanmingming/live@main/tv/m3u/index.m3u',
    'zbefine2': 'https://fastly.jsdelivr.net/gh/zbefine/iptv@main/itvlist.m3u',
    'tvlive': 'https://fastly.jsdelivr.net/gh/azhansy/tv_live@main/playlist.m3u',
    'hong': 'https://fastly.jsdelivr.net/gh/hongshana/iptv@main/iptv.m3u',
    'sun': 'https://fastly.jsdelivr.net/gh/sunwf/iptv@master/iptv.m3u',
}


def g(kv):
    k, u = kv
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': UA}), timeout=40, context=CTX)
        t = r.read(12 * 1024 * 1024).decode('utf-8', 'ignore')
        n = t.count('#EXTINF')
        if n < 10:
            return (k, 0, 'few:%d' % n)
        open('_a_%s.m3u' % k, 'w', encoding='utf-8', newline='\n').write(t)
        return (k, n, 'ok %dB' % len(t))
    except Exception as e:
        return (k, 0, '%s%s' % (type(e).__name__, getattr(e, 'code', '')))


if __name__ == '__main__':
    tot = 0
    with cf.ThreadPoolExecutor(max_workers=14) as ex:
        for k, n, m in ex.map(g, S.items()):
            print('%-10s %-6d %s' % (k, n, m))
            tot += n
    print('源条目合计', tot)
