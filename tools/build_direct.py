# -*- coding: utf-8 -*-
"""直连版 m3u：每台一条最稳线路，内网台走 8100 垫宽代理"""
import json

d = json.load(open('pools.json', encoding='utf-8'))
pools, order = d['pools'], d['order']
EPG = 'http://192.168.3.38:8099/epg.xml.gz'
LAN = 'http://192.168.3.38:8100/p/%s.m3u8'


def pick(ch):
    for s in ch['srcs']:
        if s['t'] == 'lan':
            return LAN % s['cid']
    return ch['srcs'][0]['u']


out = ['#EXTM3U url-tvg="%s" x-tvg-url="%s"' % (EPG, EPG)]
n = 0
for k in order:
    ch = pools[k]
    attrs = []
    # id 为空时用台名兜底：EPG 靠 tvg-id 匹配，缺了整台就没有节目单
    attrs.append('tvg-id="%s"' % (ch['id'] or ch['name']))
    attrs.append('tvg-name="%s"' % ch['name'])
    if ch['logo']:
        attrs.append('tvg-logo="%s"' % ch['logo'])
    if ch['group']:
        attrs.append('group-title="%s"' % ch['group'])
    out.append('#EXTINF:-1 %s,%s' % (' '.join(attrs), ch['name']))
    out.append(pick(ch))
    n += 1
open('_live_direct.m3u', 'w', encoding='utf-8', newline='\n').write('\n'.join(out) + '\n')
print('直连版 %d 台 -> _live_direct.m3u' % n)
