# -*- coding: utf-8 -*-
"""把测活的境外台并入源池：同名台补线路，新台追加"""
import json, re, os, hashlib, collections

SUF = ['超高清', '高清', '超清', '蓝光', '标清', 'HD', 'FHD', 'UHD', 'SD']
TAG = re.compile(r'\s*\((?:\d{3,4}p|\d{3,4}i|Geo-blocked|Not 24/7|Offline|Stream Error)\)', re.I)


def clean(name):
    s = TAG.sub('', name or '')
    s = re.sub(r'\s+', ' ', s).strip(' -|')
    return s


def norm(s):
    s = (s or '').upper()
    s = re.sub(r'\[[^\]]*\]', '', s)
    s = re.sub(r'[（(][^)）]*[)）]', '', s)
    s = re.sub(r'[\s\-_.·・]', '', s)
    ch = True
    while ch:
        ch = False
        for suf in SUF:
            if s.endswith(suf) and len(s) > len(suf) + 1:
                s = s[:-len(suf)]
                ch = True
    return s


def main():
    d = json.load(open('pools.json', encoding='utf-8'))
    P, order = d['pools'], d['order']
    cand = json.load(open(os.environ.get('CAND', 'cand_intl.json'), encoding='utf-8'))
    pr = json.load(open(os.environ.get('PROBE_OUT', 'pintl_probe.json'), encoding='utf-8'))

    idx = {}
    for k in order:
        idx.setdefault(norm(P[k]['name']), k)

    MAXSRC = 3
    added = []
    extra = 0
    bygroup = collections.Counter()

    # 同一台名可能有多条线路，先按台聚合
    buckets = collections.OrderedDict()
    for c in cand:
        p = pr.get(c['url'])
        if not p or not p.get('ok'):
            continue
        # EXTINF 属性里偶尔混进 User-Agent，台名取最后一个逗号之后的部分最可靠
        nm = clean((c.get('raw') or '').rsplit(',', 1)[-1]) if c.get('raw') else ''
        if not nm or '"' in nm or 'http' in nm.lower():
            nm = clean(c['name'])
        if not nm:
            continue
        buckets.setdefault(nm, {'grp': c['grp'], 'logo': c.get('logo', ''), 'urls': []})
        b = buckets[nm]
        if c['url'] not in b['urls']:
            b['urls'].append((p.get('ms') or 99999, c['url']))
        if not b['logo'] and c.get('logo'):
            b['logo'] = c['logo']

    for nm, b in buckets.items():
        urls = [u for _, u in sorted(b['urls'])][:MAXSRC]
        nk = norm(nm)
        if nk in idx:
            ch = P[idx[nk]]
            have = {s.get('u') for s in ch['srcs'] if s['t'] == 'url'}
            for u in urls:
                if len([s for s in ch['srcs'] if s['t'] == 'url']) >= MAXSRC:
                    break
                if u not in have:
                    ch['srcs'].append({'t': 'url', 'u': u})
                    have.add(u)
                    extra += 1
            continue
        base = hashlib.md5(re.sub(r'\s', '', nm.upper()).encode('utf-8')).hexdigest()[:10]
        key = base
        n = 1
        while key in P:
            n += 1
            key = '%s%02d' % (base[:8], n)
        P[key] = {'name': nm, 'group': b['grp'], 'logo': b['logo'], 'id': '', 'lan': '',
                  'srcs': [{'t': 'url', 'u': u} for u in urls]}
        order.append(key)
        idx[nk] = key
        added.append((nm, b['grp']))
        bygroup[b['grp']] += 1

    json.dump({'order': order, 'pools': P}, open('pools.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=0)
    print('总台数 %d（新增 %d 台，给老台补线路 %d 条）' % (len(order), len(added), extra))
    for g, n in bygroup.most_common():
        print('  %-16s +%d' % (g, n))
    json.dump([{'name': n, 'group': g} for n, g in added],
              open('intl_added.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)


if __name__ == '__main__':
    main()
