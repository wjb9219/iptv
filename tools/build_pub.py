# -*- coding: utf-8 -*-
"""外网版 m3u：只留公网线路（去掉 192.168 内网地址），供 GitHub Pages 使用"""
import json

d = json.load(open('pools.json', encoding='utf-8'))
pools, order = d['pools'], d['order']
PUB = 'https://wjb9219.github.io/iptv/epg.xml.gz'

out = ['#EXTM3U url-tvg="%s" x-tvg-url="%s"' % (PUB, PUB)]
n = 0; skipped = 0
for k in order:
    ch = pools[k]
    urls = [s['u'] for s in ch['srcs'] if s['t'] == 'url' and '192.168.' not in s['u']]
    if not urls:
        skipped += 1
        continue
    attrs = []
    if ch['id']:
        attrs.append('tvg-id="%s"' % ch['id'])
    attrs.append('tvg-name="%s"' % ch['name'])
    if ch['logo']:
        attrs.append('tvg-logo="%s"' % ch['logo'])
    if ch['group']:
        attrs.append('group-title="%s"' % ch['group'])
    out.append('#EXTINF:-1 %s,%s' % (' '.join(attrs), ch['name']))
    out.append(urls[0])
    n += 1
open('_live_pub.m3u', 'w', encoding='utf-8', newline='\n').write('\n'.join(out) + '\n')
print('外网版 %d 台（跳过 %d 个只有内网线路的台）' % (n, skipped))
