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
        '港澳台': '港·澳·台', '央视付费频道': '央视频道', '央视付费': '央视频道',
        '付费频道': '央视频道', 'CCTV': '央视频道', '纪录片': '纪录频道', '纪实': '纪录频道',
        '动画': '少儿动画', '少儿': '少儿动画', '卡通': '少儿动画', '体育': '体育频道',
        '电影': '电影频道', '电视剧': '电视剧频道', '音乐': '音乐频道', '戏曲': '其他',
        '新闻': '其他', '财经': '其他', '综合': '其他', 'Lifestyle': '其他',
        '更新时间': '其他', '其他': '其他'}
GROUP_ORDER = ['央视频道', '卫视频道', '省市频道', '港·澳·台', '体育频道', '电影频道',
               '电视剧频道', '纪录频道', '少儿动画', '音乐频道', '国际频道', '其他']
PROV = re.compile(r'^(北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|'
                  r'河南|湖北|湖南|广东|广西|海南|四川|贵州|云南|西藏|陕西|甘肃|青海|宁夏|新疆|'
                  r'内蒙古|香港|澳门|台湾)')
JUNK = re.compile(r'^(更新时间|支持作者|本站|声明|公告|通知|测试|备用|广告|主页|首页|更多)')


def gmap(raw):
    """先剥 emoji 再查表；省级频道归到省市频道，认不出的进其他"""
    g = EMOJI.sub('', raw or '').strip()
    if g in GMAP:
        return GMAP[g]
    if PROV.match(g):
        return '省市频道'
    if '国际' in g or '海外' in g or 'International' in g:
        return '国际频道'
    if g in GROUP_ORDER:
        return g
    return '其他'


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


ALIAS = {
    'CCTV4中文国际': 'CCTV4',
    'CCTV9纪录': 'CCTV9',
    'CCTV文化精品': 'CCTV央视文化精品',
    '文化精品': 'CCTV央视文化精品',
    'CGTN纪录': 'CGTN纪录片',
    'CGTNDOCUMENTARY': 'CGTN纪录片',
}
# 假源/死源域名：264788 是拿上传视频冒充直播，kwimgs 是快手 CDN，一律不留
FAKE = re.compile(r'(kwimgs\.com|264788)')
# 央广 cnr.cn 是广播音频流：只有声音没有画面，不能当电视频道
AUDIO = re.compile(r'(satellitepull\.cnr\.cn|cnr\.cn)')


def merge_key(s):
    k = norm(s)
    if k in ALIAS:
        k = ALIAS[k]
    stripped = re.sub(r'^CCTV', '', k)
    k = stripped or k          # 去掉 CCTV 前缀，让「CCTV风云音乐」和「风云音乐」判为同台
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
    ch['group'] = gmap(ch['group'])
    if re.match(r'^EBC\b', nm, re.I):
        ch['group'] = '国际频道'      # 柬埔寨 EBC 混进了央视组
    # 假源、纯音频源就地清掉（去掉后没线路的台下面会被自然丢弃）
    ch['srcs'] = [s for s in ch['srcs']
                  if not (s['t'] == 'url' and (FAKE.search(s['u']) or AUDIO.search(s['u'])))]
    kept.append(ch)

# 合并同台异名：保留名字最短的，其余线路并进去
bykey = collections.OrderedDict()
for ch in kept:
    mk = merge_key(ch['name'])
    if mk not in bykey:
        bykey[mk] = ch
        continue
    a = bykey[mk]
    # 有内网线路的台当主体：名字用它的、分组也跟着它走，避免被同名劣质源顶替
    if ch.get('lan') and not a.get('lan'):
        bykey[mk] = ch
        a, ch = ch, a
    a['srcs'] += [s for s in ch['srcs'] if s.get('u') and s['u'] not in
                  [x.get('u') for x in a['srcs']]]
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

# 分组名统一后重新排序：国内各组在前、国际频道压到最后（组内保持原顺序，稳定排序）
# 省市频道组内再按地域细排：河南省级 → 河南各地市 → 信阳及下辖县区 → 其他省
XINYANG = ('信阳', '浉河', '平桥', '罗山', '光山', '新县', '商城', '固始', '潢川', '淮滨', '息县', '羊山')
HENAN_CITY = ('郑州', '开封', '洛阳', '平顶山', '安阳', '鹤壁', '新乡', '焦作', '濮阳', '许昌',
              '漯河', '三门峡', '南阳', '商丘', '周口', '驻马店', '济源')


def _sub(k):
    ch = out[k]
    if ch['group'] != '省市频道':
        return 0
    n = ch['name']
    if '河南' in n:
        return 0                      # 河南省级台
    if any(c in n for c in XINYANG):
        return 2                      # 信阳及下辖县区
    if any(c in n for c in HENAN_CITY):
        return 1                      # 河南其它地市
    return 3


def _gk(k):
    g = out[k]['group']
    return GROUP_ORDER.index(g) if g in GROUP_ORDER else GROUP_ORDER.index('其他')


keys.sort(key=lambda k: (_gk(k), _sub(k)))

json.dump({'order': keys, 'pools': out}, open('pools.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=0)
seq = []
for k in keys:
    g = out[k]['group']
    if not seq or seq[-1] != g:
        seq.append(g)
print('清洗后 %d 台（清洗前 %d），丢弃/合并 %d 条' % (len(keys), len(order), len(dropped)))
print('分组顺序：', seq)
print('丢弃样例：', dropped[:12])
print('分组：', collections.Counter(v['group'] for v in out.values()).most_common(12))
