# -*- coding: utf-8 -*-
"""合成最终源池：老台补备源 + 新台全收 + 质量门槛 + 分组排序 + 死台进重试名单

本轮改动：
1. 分组固定顺序，国际频道放最后（国内在前，打开列表先看到自己的台）
2. 剔除春晚类频道（历年春晚轮播，占位不干活）
3. 国际台按实测带宽做质量门槛：连得上但码率过低的线路不选；一台全低质则整台先撤下
   阈值取自本轮国际线路带宽的 P30，并夹在 [K_FLOOR, K_CEIL] 之间，避免出口慢时一刀切光
"""
import json, re, os, hashlib, collections

SUF = ['超高清', '高清', '超清', '蓝光', '标清', 'HD', 'FHD', 'UHD', 'SD']
INTL = '国际频道'
GROUP_ORDER = ['央视频道', '卫视频道', '省市频道', '港·澳·台', '体育频道', '电影频道',
               '电视剧频道', '纪录频道', '少儿动画', '音乐频道', '其他', INTL]
K_FLOOR = float(os.environ.get('K_FLOOR', '150'))
K_CEIL = float(os.environ.get('K_CEIL', '600'))
K_PCT = float(os.environ.get('K_PCT', '0.30'))
CS_KILL = os.environ.get('CS_KILL', '1') == '1'


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


def is_chunwan(name, group):
    return CS_KILL and ('春晚' in (name or '') or group == '春晚频道')


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


def kbof(u):
    """线路实测带宽；None=未知（不参与质量判定，也不剔除）"""
    v = probe.get(u) or {}
    if not v.get('ok'):
        return None
    kb = v.get('kb', 0) or 0
    return kb if kb > 0 else None


def alive(urls):
    return [u for u in urls if (probe.get(u) or {}).get('ok')]


def rank(urls):
    """按带宽降序，未知带宽排最后"""
    def key(u):
        k = kbof(u)
        return (0, -k) if k is not None else (1, 0)
    return sorted(urls, key=key)


# ── 自适应门槛：本轮国际线路带宽的 P30 ──────────────────────────────
intl_kb = []
for k in order:
    ch = pools[k]
    if ch.get('group') != INTL:
        continue
    for u in [s['u'] for s in ch['srcs'] if s['t'] == 'url']:
        v = kbof(u)
        if v:
            intl_kb.append(v)
intl_kb.sort()
if len(intl_kb) >= 30:
    thr = intl_kb[min(len(intl_kb) - 1, int(len(intl_kb) * K_PCT))]
    thr = int(max(K_FLOOR, min(K_CEIL, thr)))
else:
    thr = int(K_FLOOR)
print('国际线路 %d 条有带宽数据，质量门槛取 %d KB/s（P%.0f，夹在 %d~%d）'
      % (len(intl_kb), thr, K_PCT * 100, K_FLOOR, K_CEIL))

rows = []
dead = {}
added_new = []
grew_backup = 0
drop_cs = 0
drop_low = []

for k in order:
    ch = pools[k]
    if is_chunwan(ch['name'], ch.get('group')):
        drop_cs += 1
        continue
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
    live = rank(live)

    if ch.get('group') == INTL:
        keep = [u for u in live if (kbof(u) is None or kbof(u) >= thr)]
        dropped = [u for u in live if u not in keep]
        if not keep and live:
            drop_low.append((ch['name'], [kbof(u) or -1 for u in live][:3]))
            dead[ch['name']] = {'group': ch.get('group'), 'logo': ch.get('logo', ''),
                                'id': ch.get('id', ''), 'urls': live[:3], 'why': 'quality'}
            continue
        live = keep

    for u in live:
        if len(srcs) >= MAXSRC:
            break
        srcs.append({'t': 'url', 'u': u})
    if len(srcs) > len(ch['srcs']):
        grew_backup += 1
    if not srcs:
        dead[ch['name']] = {'group': ch['group'], 'logo': ch.get('logo', ''), 'id': ch.get('id', ''),
                            'urls': pool_urls[:8], 'why': 'dead'}
        continue
    rows.append({'name': ch['name'], 'group': ch['group'], 'logo': ch.get('logo', ''),
                 'id': ch.get('id', ''), 'lan': lcid, 'srcs': srcs})

have = {norm(r['name']) for r in rows}
for k, v in newc.items():
    nm = v['name']
    grp = GMAP.get(v.get('group'), v.get('group') or '其他')
    if is_chunwan(nm, grp):
        drop_cs += 1
        continue
    live = rank(alive(v['urls']))
    if grp == INTL:
        live = [u for u in live if (kbof(u) is None or kbof(u) >= thr)]
    if not live:
        if norm(nm) not in have:
            dead.setdefault(nm, {'group': grp, 'logo': '', 'id': '',
                                 'urls': v['urls'][:8], 'why': 'dead'})
        continue
    key = norm(nm)
    if not nm or not key or key in have:
        continue
    have.add(key)
    rows.append({'name': nm, 'group': grp, 'logo': '', 'id': '', 'lan': '',
                 'srcs': [{'t': 'url', 'u': u} for u in live[:MAXSRC]]})
    added_new.append(nm)

# 老重试名单里本轮复活的
revived = []
for nm, v in retry_old.items():
    if nm in dead:  # 仍然死（含质量不达标）
        v['urls'] = list(dict.fromkeys(v.get('urls', []) + dead[nm].get('urls', [])))[:8]
        v['why'] = dead[nm].get('why', 'dead')
        dead[nm] = v
        continue
    if norm(nm) in have or is_chunwan(nm, v.get('group')):
        continue
    live = rank(alive(v.get('urls', [])))
    if v.get('group') == INTL:
        live = [u for u in live if (kbof(u) is None or kbof(u) >= thr)]
    if live:
        rows.append({'name': nm, 'group': v.get('group') or '其他', 'logo': v.get('logo', ''),
                     'id': v.get('id', ''), 'lan': '',
                     'srcs': [{'t': 'url', 'u': u} for u in live[:MAXSRC]]})
        have.add(norm(nm)); revived.append(nm)

# ── 分组排序：国内各分组在前，国际频道放最后 ────────────────────────
def gkey(g):
    return GROUP_ORDER.index(g) if g in GROUP_ORDER else GROUP_ORDER.index('其他')

rows.sort(key=lambda r: gkey(r['group']))

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
gc = collections.Counter(out[k]['group'] for k in keys)
nq = sum(1 for v in dead.values() if v.get('why') == 'quality')
print('最终台数 %d（内网台 %d）' % (len(keys), lan))
print('本轮新增 %d 个能播新台，老台复活 %d 个' % (len(added_new), len(revived)))
print('剔除春晚 %d 个；因低码率撤下国际台 %d 个' % (drop_cs, nq))
if drop_low:
    print('低码率样例：', drop_low[:8])
print('备源 2 条以上 %d 台，3 条 %d 台，这轮补上备源的老台 %d 个' % (n2, n3, grew_backup))
print('进重试名单：%d 个（其中低质 %d）' % (len(dead), nq))
print('新增样例：', added_new[:20])
print('分组顺序：', gc.most_common(20))
json.dump({'added': added_new, 'revived': revived, 'dead': sorted(dead),
           'n2': n2, 'n3': n3, 'total': len(keys), 'thr': thr,
           'drop_cs': drop_cs, 'drop_low': len(drop_low),
           'groups': [[g, c] for g, c in gc.most_common()]},
          open('round_report.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
