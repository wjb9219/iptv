# -*- coding: utf-8 -*-
"""聚合所有源：给已有台找备源 + 收集全部新台候选"""
import json, re, glob, collections

SUF = ['超高清', '高清', '超清', '蓝光', '标清', 'HD', 'FHD', 'UHD', 'SD']
BAD = ('like gecko', 'mozilla', 'applewebkit', 'chrome/')


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


def variants(nm):
    a = norm(nm); out = [a]
    if a in ('CCTV4K', 'CCTV8K'):
        out.append(a[:-1])
    else:
        b = re.sub(r'(4K|8K)$', '', a)
        if b != a and len(b) >= 3: out.append(b)
    c = re.sub(r'(频道|台|直播)$', '', a)
    if c != a and c: out.append(c)
    seen = set(); r = []
    for x in out:
        if x and x not in seen: seen.add(x); r.append(x)
    return r


def clean(nm):
    nm = re.sub(r'\s*[（(][^)）]*(720|1080|480|576|600|960|2160|4K|8K)[^)）]*[)）]\s*', '', nm, flags=re.I)
    nm = re.sub(r'\s*\[[^\]]*\]\s*', ' ', nm)
    nm = re.sub(r'\s+', ' ', nm).strip(' -_\t')
    return nm


CJK = re.compile(r'[\u4e00-\u9fff]')

DOMESTIC = ('aptv', 'guovin', 'vb4', 'zbe', 'hujing', 'fanming1', 'fmm_ipv6',
            'org_cn', 'org_hk', 'org_tw', 'org_mo', 'org_sg', 'zho', 'yue', 'cmn',
            'cn', 'fmm', 's_', 's2_')


def is_domestic(tag):
    return any(k in tag for k in DOMESTIC)


def parse(f):
    """返回 [(name, url, group, tag)]"""
    out = []; cur = None; grp = ''
    tag = f.replace('_a_', '').replace('_s2_', '').replace('_s_', '').replace('_l_', '').replace('_c_', '').replace('.m3u', '')
    for l in open(f, encoding='utf-8', errors='ignore'):
        l = l.rstrip('\r\n')
        if l.startswith('#EXTINF'):
            m = re.search(r'tvg-name="([^"]*)"', l)
            nm = m.group(1).strip() if m and m.group(1).strip() else (l.split(',', 1)[1].strip() if ',' in l else '')
            g = re.search(r'group-title="([^"]*)"', l)
            grp = g.group(1) if g else ''
            cur = nm
        elif l.startswith('http') and cur:
            out.append((cur, l.strip(), grp, tag)); cur = None
    return out


pools_doc = json.load(open('pools.json', encoding='utf-8'))
pools = pools_doc['pools']; order = pools_doc['order']
idx = {}
for k in order:
    idx.setdefault(norm(pools[k]['name']), k)

retry = {}
try:
    retry = json.load(open('retry_dead.json', encoding='utf-8'))
except Exception:
    pass

files = sorted(glob.glob('_a_*.m3u') + glob.glob('_s_*.m3u') + glob.glob('_s2_*.m3u') +
               glob.glob('_l_*.m3u') + glob.glob('_c_*.m3u'))
entries = []
for f in files:
    entries += parse(f)
print('源文件 %d 个，条目 %d 条' % (len(files), len(entries)))

extra = collections.defaultdict(list)     # 台 key -> [(url, tag)]
newch = collections.defaultdict(list)     # 规范名 -> [(name, url, group, tag)]
skipped = collections.Counter()

for nm, u, grp, tag in entries:
    base = nm.lower()
    if any(b in base for b in BAD) or not nm:
        skipped['解析脏名'] += 1
        continue
    hit = None
    for v in variants(nm):
        if v in idx:
            hit = idx[v]; break
    if hit:
        extra[hit].append((u, tag))
        continue
    key = norm(clean(nm))
    if not key:
        skipped['空名'] += 1
        continue
    if not (CJK.search(nm) or is_domestic(tag)):
        skipped['非中文源条目'] += 1
        continue
    newch[key].append((clean(nm), u, grp, tag))

print('已有台可补备源：%d 个台 / %d 条线路' % (len(extra), sum(len(v) for v in extra.values())))
print('新台候选：%d 个 / %d 条线路' % (len(newch), sum(len(v) for v in newch.values())))
print('跳过：', dict(skipped))

# 候选：每台最多 6 条，按来源去重
CAND = {}
for k, v in extra.items():
    urls = []; seen = set()
    for u, tag in v:
        if u in seen: continue
        seen.add(u); urls.append(u)
        if len(urls) >= 6: break
    CAND[k] = urls

NEW = {}
for k, v in newch.items():
    urls = []; seen = set(); name = v[0][0]; grp = v[0][2]
    for nm, u, g, tag in v:
        if u in seen: continue
        seen.add(u); urls.append(u)
        if len(name) < 2 or (not CJK.search(name) and CJK.search(nm)): name = nm
        if len(urls) >= 6: break
    NEW[k] = {'name': name, 'group': grp, 'urls': urls}

json.dump({'extra': CAND, 'new': NEW}, open('cand_all.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
print('写出 cand_all.json')
