# -*- coding: utf-8 -*-
"""清洗源池：去脏条目录、统一分组名、合并同台异名（简繁/后缀差异）"""
import json, re, collections

TRAD = {'聞': '闻', '綜': '综', '頻': '频', '視': '视', '劇': '剧', '場': '场', '華': '华', '東': '东',
        '龍': '龙', '貓': '猫', '萬': '万', '縣': '县', '峽': '峡', '陽': '阳', '廣': '广', '寧': '宁',
        '遼': '辽', '蘇': '苏', '慶': '庆', '環': '环', '興': '兴', '島': '岛', '門': '门', '灣': '湾',
        '運': '运', '體': '体', '樂': '乐', '醫': '医', '學': '学', '園': '园', '國': '国', '會': '会',
        '區': '区', '節': '节', '藝': '艺', '術': '术', '業': '业', '產': '产', '團': '团', '隊': '队',
        '賽': '赛', '選': '选', '舉': '举', '將': '将', '後': '后', '發': '发', '現': '现', '實': '实',
        '紀': '纪', '錄': '录', '財': '财', '經': '经', '濟': '济', '衛': '卫', '際': '际', '兒': '儿',
        '數': '数', '碼': '码', '戲': '戏', '嶺': '岭', '寶': '宝', '鳳': '凤', '東': '东', '車': '车'}
SUF = ['超高清', '高清', '超清', '蓝光', '标清', 'HD', 'FHD', 'UHD', 'SD']
EMOJI = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]')
GMAP = {'卫视IPV4': '卫视频道', '央视IPV4': '央视频道', '央视台': '央视频道', '卫视': '卫视频道',
        '港澳台': '🌊港·澳·台', '央视付费频道': '央视频道'}
JUNK = re.compile(r'^(更新时间|支持作者|本站|声明|公告|通知|测试|备用|广告|主页|首页|更多)')


def trad(s):
    return ''.join(TRAD.get(c, c) for c in s)


def norm(s):
    s = trad((s or '').upper())
    s = re.sub(r'\[[^\]]*\]', '', s)
    s = re.sub(r'[（(][^)）]*[)）]', '', s)
    s = re.sub(r'[\s\-_.·]', '', s)
    ch = True
    while ch:
        ch = False
        for suf in SUF:
            if s.endswith(suf) and len(s) > len(suf) + 1:
                s = s[:-len(suf)]; ch = True
    return s


def merge_key(s):
    k = norm(s)
    return re.sub(r'(频道|台|电视台|直播)$', '', k)


d = json.load(open('pools.json', encoding='utf-8'))
pools, order = d['pools'], d['order']

kept = []
dropped = []
for k in order:
    ch = pools[k]
    nm = (ch['name'] or '').strip()
    if not nm or JUNK.match(nm) or re.match(r'^\d{4}-\d{2}-\d{2}', nm) or nm.lower().startswith('mozilla'):
        dropped.append(nm); continue
    ch['group'] = GMAP.get(ch['group'], EMOJI.sub('', ch['group'] or '').strip() or '其他')
    kept.append(ch)

# 合并同台异名：保留名字最短的，其余线路并进去
bykey = collections.OrderedDict()
for ch in kept:
    mk = merge_key(ch['name'])
    if mk not in bykey:
        bykey[mk] = ch
        continue
    a = bykey[mk]
    a['srcs'] += [s for s in ch['srcs'] if s.get('u') and s['u'] not in
                  [x.get('u') for x in a['srcs']]]
    if len(ch['name']) < len(a['name']):
        a['name'] = ch['name']
    if not a.get('lan') and ch.get('lan'):
        a['lan'] = ch['lan']
    dropped.append(ch['name'] + ' → ' + a['name'])

# 去空、限 3 条
used = {}; out = {}; keys = []
import hashlib
for mk, ch in bykey.items():
    srcs = []
    for s in ch['srcs']:
        if len(srcs) >= 3: break
        if s['t'] == 'lan' and not any(x['t'] == 'lan' for x in srcs):
            srcs.append(s)
        elif s['t'] == 'url' and s.get('u') not in [x.get('u') for x in srcs]:
            srcs.append(s)
    if not srcs:
        continue
    ch['srcs'] = srcs
    base = hashlib.md5(re.sub(r'[\s\-_.·]', '', ch['name'].upper()).encode()).hexdigest()[:10]
    key = base; used[key] = used.get(key, 0) + 1
    if used[key] > 1:
        key = base[:8] + '%02d' % used[key]
    out[key] = ch; keys.append(key)

json.dump({'order': keys, 'pools': out}, open('pools.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=0)
print('清洗后 %d 台（清洗前 %d），丢弃/合并 %d 条' % (len(keys), len(order), len(dropped)))
print('丢弃样例：', dropped[:12])
print('分组：', collections.Counter(v['group'] for v in out.values()).most_common(12))
