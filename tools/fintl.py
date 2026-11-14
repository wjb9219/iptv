# -*- coding: utf-8 -*-
"""筛出境外重点候选：港澳台全量 + 新闻分类全量 + 各国头部媒体白名单"""
import glob, json, re, os, collections

TAG = re.compile(r'\[[^\]]*\]')
FLAGS = ('Geo-blocked', 'Not 24/7', 'Offline', 'Stream Error')

def norm_name(s):
    s = TAG.sub('', s or '').strip()
    s = re.sub(r'\s+', ' ', s)
    return s

def parse(f):
    out, cur = [], None
    for l in open(f, encoding='utf-8', errors='ignore'):
        l = l.rstrip('\r\n')
        if l.startswith('#EXTINF'):
            m = re.search(r'tvg-name="([^"]*)"', l)
            g = re.search(r'group-title="([^"]*)"', l)
            lg = re.search(r'tvg-logo="([^"]*)"', l)
            nm = m.group(1).strip() if m and m.group(1).strip() else (l.split(',', 1)[1].strip() if ',' in l else '')
            cur = {'name': norm_name(nm), 'group': g.group(1) if g else '',
                   'logo': lg.group(1) if lg else '', 'raw': l}
        elif l.startswith('http') and cur is not None and 'url' not in cur:
            cur['url'] = l.strip(); out.append(cur); cur = None
    return out

# 各国头部媒体白名单（名称包含即收，大小写不敏感）
BRANDS = [
    'BBC', 'ITV', 'Channel 4', 'Channel 5', 'Sky News', 'Sky Sports', 'GB News', 'STV', 'Dave',
    'CNN', 'Fox News', 'Fox Business', 'MSNBC', 'ABC News', 'CBS News', 'NBC News', 'Bloomberg',
    'CNBC', 'PBS', 'Newsmax', 'NewsNation', 'C-SPAN', 'The Weather Channel', 'NBC', 'ABC', 'CBS',
    'DW', 'ZDF', 'ARD', 'RTL', 'ProSieben', 'Sat.1',
    'France 24', 'France 2', 'France 3', 'TF1', 'M6', 'BFM', 'LCI', 'CNews',
    'Euronews', 'Rai', 'Mediaset', 'TVE', 'Antena 3', 'RTVE', 'NOS', 'RTL Nieuws', 'VRT',
    'Al Jazeera', 'Al Arabiya', 'Sky News Arabia', 'i24', 'TRT', 'Haberturk', 'NTV',
    'NHK', 'KBS', 'MBC', 'SBS', 'TV Asahi', 'TBS', 'Fuji', 'Nippon TV', 'Tokyo MX',
    'CCTV', 'CGTN', 'Phoenix', 'TVBS', 'CTV', 'FTV', 'TTV', 'SET', 'EBC', 'PTS', 'Hakka',
    'TVB', 'ViuTV', 'HOY', 'RTHK', 'Now TV', 'Cable TV', 'i-Cable', 'TDM', 'Macau',
    'RT', 'Rossiya', 'NTV', 'Channel One', 'CTC',
    'TVP', 'Polsat', 'ČT', 'RTVS', 'MTV3', 'Yle', 'NRK', 'SVT', 'DR', 'TV2',
    'ERT', 'Skai', 'Mega', 'ANT1', 'Star',
    'Globo', 'Record', 'SBT', 'Band', 'Televisa', 'TV Azteca', 'Caracol', 'RCN', 'Telefe',
    'Canal 13', 'TVN', 'Mega', 'America TV', 'Panamericana', 'Ecuavisa', 'TC Televisión',
    'ABS-CBN', 'GMA', 'TV5', 'PTV', 'RCTI', 'SCTV', 'Trans7', 'Metro TV', 'Kompas',
    'MediaCorp', 'Channel NewsAsia', 'Suria', 'Vasantham',
    'Astro', 'RTM', 'TV3', 'NTV7', 'Bernama',
    'Thai PBS', 'Channel 3', 'Channel 7', 'Channel 5', 'One 31', 'GMM 25', 'MCOT', 'NBT',
    'VTV', 'HTV', 'VTC', 'VOV', 'THP',
    'Arirang', 'YTN', 'MBN', 'JTBC', 'Channel A', 'TV Chosun',
    'Doordarshan', 'NDTV', 'Zee', 'Star Plus', 'Colors', 'Sony', 'ABP', 'Aaj Tak', 'Republic',
    'Geo News', 'ARY', 'Dunya', 'Express', 'Hum', 'PTV',
    'Somoy', 'Jamuna', 'Channel i', 'ATN', 'Ekattor',
    'Al Ekhbariya', 'Dubai', 'Abu Dhabi', 'MBC', 'Rotana', 'Saudi',
    'Kanal', 'Habertürk', 'Show TV', 'Fox TV', 'Star TV',
    'KBS World', 'Arirang', 'NHK World',
]

# 港澳台按地区整组收，不看品牌
REGION = {'hk': '🌊港·澳·台', 'mo': '🌊港·澳·台', 'tw': '🌊港·澳·台'}

def main():
    cands = {}
    stat = collections.Counter()
    # 1) 港澳台全量
    for cc, grp in REGION.items():
        f = '_wr_%s.m3u' % cc
        if not os.path.exists(f):
            continue
        for x in parse(f):
            if any(fl in x['raw'] for fl in FLAGS):
                stat['geo'] += 1
                continue
            cands.setdefault(x['url'], dict(x, grp=grp, cc=cc))
            stat['region'] += 1
    # 2) 新闻分类全量
    if os.path.exists('_wr_news.m3u'):
        for x in parse('_wr_news.m3u'):
            if any(fl in x['raw'] for fl in FLAGS):
                stat['geo'] += 1
                continue
            if x['url'] in cands:
                continue
            cands[x['url']] = dict(x, grp='🌍国际·新闻', cc='news')
            stat['news'] += 1
    # 3) 各国头部媒体
    low = [(b.lower(), b) for b in BRANDS]
    for f in glob.glob('_wr_*.m3u'):
        cc = f[4:-4]
        if cc in REGION or cc == 'news':
            continue
        for x in parse(f):
            if any(fl in x['raw'] for fl in FLAGS):
                continue
            nm = x['name'].lower()
            if not any(b in nm for b, _ in low):
                continue
            if x['url'] in cands:
                continue
            cands[x['url']] = dict(x, grp='🌍国际·综合', cc=cc)
            stat['brand'] += 1
    out = list(cands.values())
    json.dump(out, open('cand_intl.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print('境外候选', len(out), dict(stat))
    c = collections.Counter(x['grp'] for x in out)
    print(dict(c))

if __name__ == '__main__':
    main()
