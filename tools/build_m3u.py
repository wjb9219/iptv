# -*- coding: utf-8 -*-
"""由 pools.json 生成 m3u：内网版走多源网关，测试版只取前 N 台"""
import json, sys

d = json.load(open('pools.json', encoding='utf-8'))
pools, order = d['pools'], d['order']
GW = 'http://192.168.3.38:8101/m/%s.m3u8'
EPG = 'http://192.168.3.38:8099/epg.xml.gz'

TEST = ['CCTV1', 'CCTV2', 'CCTV5', 'CCTV6', 'CCTV13', '湖南卫视', '浙江卫视', '江苏卫视',
        '东方卫视', '北京卫视', '河南新闻频道', '信阳新闻综合', '凤凰中文', 'CCTV4K',
        'CCTV17', '广东卫视', '深圳卫视', '四川卫视', 'CGTN', '河南都市频道']


def line(k):
    ch = pools[k]
    attrs = []
    if ch['id']:
        attrs.append('tvg-id="%s"' % ch['id'])
    attrs.append('tvg-name="%s"' % ch['name'])
    if ch['logo']:
        attrs.append('tvg-logo="%s"' % ch['logo'])
    if ch['group']:
        attrs.append('group-title="%s"' % ch['group'])
    return '#EXTINF:-1 %s,%s\n%s\n' % (' '.join(attrs), ch['name'], GW % k)


def write(path, keys, head):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(head + '\n')
        for k in keys:
            f.write(line(k))
    return len(keys)


HEAD = '#EXTM3U url-tvg="%s" x-tvg-url="%s"' % (EPG, EPG)

# 全量
n = write('_live_gw.m3u', order, HEAD)
print('全量 %d 台 -> _live_gw.m3u' % n)

# 测试版：指定台 + 前若干台
byname = {}
for k in order:
    byname.setdefault(pools[k]['name'], k)
tk = []
for nm in TEST:
    k = byname.get(nm)
    if k and k not in tk:
        tk.append(k)
# 补一批多源的台
for k in order:
    if len(pools[k]['srcs']) >= 3 and k not in tk:
        tk.append(k)
    if len(tk) >= 28:
        break
n2 = write('live_gw_test.m3u', tk[:28], HEAD)
print('测试 %d 台 -> live_gw_test.m3u' % n2)
for k in tk[:28]:
    print('  %-12s %d源  %s' % (pools[k]['name'], len(pools[k]['srcs']), k))
