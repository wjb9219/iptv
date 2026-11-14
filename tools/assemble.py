# -*- coding: utf-8 -*-
"""合成最终源池：老台补备源 + 新台全收 + 死台进重试名单（不永久丢弃）"""
import json, re, hashlib, collections

SUF = ['超高清', '高清', '超清', '蓝光', '标清', 'HD', 'FHD', 'UHD', 'SD']


def norm(s):
    s = (s or '').upper()
    s = re.sub(r'\[[^\]]*\]', '', s)
    s = re.sub(r'[（(][^)）]*[)）]', '', s)
    s = re.sub(r'[\s\-_.·]', '', s)
    ch = True
    while ch:
        ch = False
        for suf in SUF:
            if s.endswith(suf) and len(s) > len(suf) + 1:
                s = s[:-len(suf)]; ch = True
    if s.startswith('中国中央电视台'):
        s = 'CCTV' + s[len('中国中央电视台'):]
    if s.startswith('CCTV') and not re.match(r'CCTV\d', s):
        s = s.replace('CCTV-', 'CCTV')
    return s


GMAP = {'General': '其他', 'Undefined': '其他', 'News': '新闻频道', 'Sports': '体育频道',
        'Movies': '电影频道', 'Kids': '儿童频道', 'Documentary': '纪录频道', 'Music': '音乐频道',
        'Entertainment': '其他', 'Culture': '其他', 'Religious': '其他', 'Education': '其他',
        'Family': '其他', 'Comedy': '其他', 'Travel': '其他', 'Cooking': '其他'}

pools_doc = json.load(open('pools.json', encoding='utf-8'))
pools = pools_doc['pools']; order = pools_doc['order']
cand = json.load(open('cand_all.json', encoding='utf-8'))
probe = json.load(open('probe_all.json', encoding='utf-8'))
extra = cand.get('extra', {}); newc = cand.get('new', {})

try:
    retry_old = json.load(open('retry_dead.json', encoding='utf-8'))
except Exception:
    retry_old = {}

MAXSRC = 3


def alive(urls):
    return [u for u in urls if probe.get(u, {}).get('ok')]


rows = []
dead = {}
added_new = []
grew_backup = 0

for k in order:
    ch = pools[k]
    lcid = ch.get('lan') or next((s['cid'] for s in ch['srcs'] if s['t'] == 'lan'), '')
    srcs = []
    if lcid:
        srcs.append({'t': 'lan', 'cid': lcid})
    old = [s['u'] for s in ch['srcs'] if s['t'] == 'url']
    pool_urls = old + [u for u in extra.get(k, []) if u not in old]
    live = alive(pool_urls)
    if not live and old:
        # 全灭时保留一条历史线路：宁可暂时播不动，也别让这个台从外网列表消失
        live = old[:1]
    for u in live:
        if len(srcs) >= MAXSRC: break
        srcs.append({'t': 'url', 'u': u})
    if len(srcs) > len(ch['srcs']):
        grew_backup += 1
    if not srcs:
        dead[ch['name']] = {'group': ch['group'], 'logo': ch.get('logo', ''), 'id': ch.get('id', ''),
                            'urls': pool_urls[:8]}
        continue
    rows.append({'name': ch['name'], 'group': ch['group'], 'logo': ch.get('logo', ''),
                 'id': ch.get('id', ''), 'lan': lcid, 'srcs': srcs})

have = {norm(r['name']) for r in rows}
for k, v in newc.items():
    live = alive(v['urls'])
    if not live:
        nm = v['name']
        if norm(nm) not in have:
            dead.setdefault(nm, {'group': GMAP.get(v.get('group'), '其他'), 'logo': '', 'id': '',
                                 'urls': v['urls'][:8]})
        continue
    nm = v['name']
    key = norm(nm)
    if not nm or not key or key in have:
        continue
    have.add(key)
    rows.append({'name': nm, 'group': GMAP.get(v.get('group'), v.get('group') or '其他'),
                 'logo': '', 'id': '', 'lan': '',
                 'srcs': [{'t': 'url', 'u': u} for u in live[:MAXSRC]]})
    added_new.append(nm)

# 老重试名单里本轮复活的
revived = []
for nm, v in retry_old.items():
    if nm in dead:  # 仍然死
        v['urls'] = list(dict.fromkeys(v.get('urls', []) + dead[nm].get('urls', [])))[:8]
        dead[nm] = v
        continue
    if norm(nm) in have:
        continue
    live = alive(v.get('urls', []))
    if live:
        rows.append({'name': nm, 'group': v.get('group') or '其他', 'logo': v.get('logo', ''),
                     'id': v.get('id', ''), 'lan': '',
                     'srcs': [{'t': 'url', 'u': u} for u in live[:MAXSRC]]})
        have.add(norm(nm)); revived.append(nm)

out = {}; used = {}; keys = []
for r in rows:
    base = hashlib.md5(re.sub(r'[\s\-_.·]', '', r['name'].upper()).encode()).hexdigest()[:10]
    key = base; used[key] = used.get(key, 0) + 1
    if used[key] > 1:
        key = base[:8] + '%02d' % used[key]
    out[key] = r; keys.append(key)

json.dump({'order': keys, 'pools': out}, open('pools.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=0)
json.dump(dead, open('retry_dead.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)

n2 = sum(1 for k in keys if len(out[k]['srcs']) >= 2)
n3 = sum(1 for k in keys if len(out[k]['srcs']) >= 3)
lan = sum(1 for k in keys if out[k]['lan'])
print('最终台数 %d（内网台 %d）' % (len(keys), lan))
print('本轮新增 %d 个能播新台，老台复活 %d 个' % (len(added_new), len(revived)))
print('备源 2 条以上 %d 台，3 条 %d 台，这轮补上备源的老台 %d 个' % (n2, n3, grew_backup))
print('进重试名单（本轮不通，下轮再试）：%d 个' % len(dead))
print('新增样例：', added_new[:30])
print('复活样例：', revived[:10])
print('分组：', collections.Counter(r['group'] for r in rows).most_common(8))
json.dump({'added': added_new, 'revived': revived, 'dead': sorted(dead),
           'n2': n2, 'n3': n3, 'total': len(keys)},
          open('round_report.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
