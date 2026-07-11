# -*- coding: utf-8 -*-
"""
鳴門 穴党ツール - 毎朝の自動実行スクリプト（丸亀ツールの build.py + racecard.py に相当）

毎朝7時にGitHub Actionsから実行され、次の3つを順に行います:
  1) データ更新: 前回以降のKファイル(競走成績)をダウンロードして集計に追加
  2) シグナル表の構築: 地力・F持ち・ST・まくり型・艇番5/6率・レース番号表
  3) 当日出走表: 今日のBファイル(番組表)を取得し、シグナルを乗せて naruto/data.json に出力

必要なもの: Python3 + lhafile (pip install lhafile)
データの置き場所: data/naruto/ （このスクリプトが自動で読み書き）
表示ページ: naruto/index.html が naruto/data.json を読んで表示

テスト実行: NARUTO_DATE=2026-06-28 python3 scripts/naruto_daily.py
           （日付を指定するとその日を「今日」として動く）
"""
import os, re, csv, json, time, datetime, tempfile, unicodedata, collections
import urllib.request
import lhafile

# ============================================================
# 設定（閾値を変えたいときはここだけ触ればOK）
# ============================================================
JCD = '14'                 # 鳴門
DATA = 'data/naruto'       # データ置き場
OUT_JSON = 'naruto/data.json'
SHRINK_N0 = 20             # 地力の縮約強度（少走数選手を全国平均に寄せる）
ST_LATE = 0.18             # ST遅れの閾値（スロー平均STがこれ超）
ST_LOCAL_MIN = 10          # 当地STを採用する最低走数（未満は全国で代替）
ST_NATL_MIN = 20           # 全国STの最低走数
MAKURI_MIN = 15            # まくり型の最低走数（当地3-4コース）
MAKURI_RATE = 0.15         # まくり型の閾値（まくり系勝利÷3-4コース出走）
TEIBAN_MIN = 15            # 艇番5/6率の最低乗艇数
TEIBAN_LOW = 0.25          # これ未満で「外し候補」
UA = {"User-Agent": "Mozilla/5.0 (naruto-tool)"}

KIKAKU = {
    'とるならなる': ('鉄板企画', '穴党は基本見送り。イン72%・万舟11%の鉄板番組。1頭時の平均配当は1,700円台。'),
    'どーなるなる': ('穴の巣', '頭を2・3・4号艇に散らす番組（イン32%・万舟23%）。1号艇は相手まで。'),
    'どきどきなる': ('堅いか万舟', '二択番組。1頭時は平均1,576円と安く、飛ぶ35%が深く壊れる。買うなら1総外し側。'),
    'とにかくなる': ('中間', '企画の中では標準的。フラグ次第で判断。'),
}

def jst_today():
    override = os.environ.get('NARUTO_DATE')
    if override:
        return datetime.date.fromisoformat(override)
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).date()

def fetch_lzh(kind, d):
    """K/BファイルのLZHをダウンロードしてテキストを返す（無ければNone）"""
    ds = d.strftime('%y%m%d')
    lc = kind.lower()
    url = f'https://www1.mbrace.or.jp/od2/{kind}/{d.strftime("%Y%m")}/{lc}{ds}.lzh'
    path = os.path.join(tempfile.gettempdir(), f'{lc}{ds}.lzh')
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        for i in range(3):
            try:
                req = urllib.request.Request(url, headers=UA)
                data = urllib.request.urlopen(req, timeout=60).read()
                if len(data) < 1000:
                    return None
                open(path, 'wb').write(data)
                break
            except Exception:
                time.sleep(3 + i*3)
        else:
            return None
    try:
        f = lhafile.Lhafile(path)
        return f.read(f.infolist()[0].filename).decode('shift_jis', errors='replace')
    except Exception:
        try: os.remove(path)
        except OSError: pass
        return None

# ============================================================
# Kファイルのパース（仕様書2.5の桁位置方式）
# ============================================================
RACE_HDR = re.compile(r'^\s{2,}(\d{1,2})R\s+(.*?)\s+H(\d{3,4})m')
WIND_RE = re.compile(r'風[\s\u3000]*([東西南北]{1,3})[\s\u3000]*(\d+)m')
WIND_RE2 = re.compile(r'風[\s\u3000]*(\d+)m')
SANTAN = re.compile(r'３連単\s+([1-6]-[1-6]-[1-6])\s+(\d+)')
DAY_RE = re.compile(r'第\s*(\d+)\s*日')

def is_finisher(line):
    return (len(line) > 21 and line[:2] == '  ' and len(line) > 6
            and line[6].isdigit() and line[8:12].isdigit())

def parse_k_day(raw, date):
    """1日分のKファイル → (全国更新用イベント, 鳴門レース行, 鳴門艇行)"""
    events = dict(in_=[], st=[], tb=[], fl=[])
    n_races, n_boats = [], []
    for vm in re.finditer(r'(\d{2})KBGN(.*?)\1KEND', raw, re.S):
        vcd, blk = vm.group(1), vm.group(2)
        nichime = ''
        m = DAY_RE.search(unicodedata.normalize('NFKC', blk[:400]))
        if m: nichime = int(m.group(1))
        cur = None
        races = []
        for line in blk.split('\n'):
            hm = RACE_HDR.match(line)
            if hm and ('風' in line or '波' in line):
                if cur: races.append(cur)
                wm = WIND_RE.search(line)
                if wm: wdir, wspd = wm.group(1), int(wm.group(2))
                else:
                    wm2 = WIND_RE2.search(line)
                    wdir, wspd = '無', (int(wm2.group(1)) if wm2 else '')
                cur = dict(rno=int(hm.group(1)), rname=hm.group(2).replace('\u3000','').strip(),
                           wdir=wdir, wspd=wspd, kimarite='', boats=[], santan='', payout='')
                continue
            if cur is None: continue
            if 'ﾚｰｽﾀｲﾑ' in line:
                cur['kimarite'] = line.split('ﾚｰｽﾀｲﾑ')[1].replace('\u3000','').strip(); continue
            if is_finisher(line):
                chaku = line[2:4].strip(); teiban = line[6]; touban = line[8:12]
                name = line[13:21].replace('\u3000','').strip()
                tail = line[21:].split()
                shinnyu = tail[3] if len(tail)>=4 and len(tail[3])==1 and tail[3] in '123456' else ''
                st = ''
                if len(tail)>=5:
                    try:
                        v = float(tail[4])
                        if 0 <= v <= 1.0: st = v
                    except ValueError: pass
                tenji = ''
                if len(tail)>=3:
                    try:
                        v = float(tail[2])
                        if 6.0 <= v <= 8.0: tenji = v
                    except ValueError: pass
                motor = tail[0] if tail else ''
                cur['boats'].append(dict(chaku=chaku, teiban=teiban, touban=touban, name=name,
                                         motor=motor, tenji=tenji, shinnyu=shinnyu, st=st))
                continue
            sm = SANTAN.search(line)
            if sm: cur['santan'] = sm.group(1); cur['payout'] = int(sm.group(2))
        if cur: races.append(cur)
        # 全国イベント
        for r in races:
            c1 = [b for b in r['boats'] if b['shinnyu']=='1']
            if len(c1)==1:
                events['in_'].append((touban_ym(date), c1[0]['touban'], 1, 1 if c1[0]['chaku']=='01' else 0))
            for b in r['boats']:
                if b['shinnyu'] and b['st'] != '':
                    slow = b['shinnyu'] in '123'
                    events['st'].append((touban_ym(date), b['touban'], slow, b['st']))
                if b['teiban'] in '56':
                    top3 = 1 if b['chaku'] in ('01','02','03') else 0
                    events['tb'].append((touban_ym(date), b['touban'], b['teiban'], top3))
                if b['chaku']=='F': events['fl'].append((date.isoformat(), b['touban'], 'F'))
                elif b['chaku']=='L0': events['fl'].append((date.isoformat(), b['touban'], 'L'))
        # 鳴門の行
        if vcd == JCD:
            for r in races:
                if len(r['boats']) < 5: continue
                c1 = [b for b in r['boats'] if b['shinnyu']=='1']
                n_races.append(dict(date=date.isoformat(), rno=r['rno'], rname=r['rname'],
                    nichime=nichime, wdir=r['wdir'], wspd=r['wspd'], kimarite=r['kimarite'],
                    santan=r['santan'], payout=r['payout'],
                    win_teiban=(r['santan'].split('-')[0] if r['santan'] else ''),
                    c1_touban=(c1[0]['touban'] if len(c1)==1 else ''),
                    c1_win=(1 if len(c1)==1 and c1[0]['chaku']=='01' else 0)))
                for b in r['boats']:
                    n_boats.append(dict(date=date.isoformat(), rno=r['rno'], **b))
    return events, n_races, n_boats

def touban_ym(date):
    return date.strftime('%Y-%m')

# ============================================================
# データ置き場の読み書き
# ============================================================
def load_counts(name, keyfields, valfields):
    path = os.path.join(DATA, name)
    out = {}
    if os.path.exists(path):
        for row in csv.DictReader(open(path, encoding='utf-8')):
            k = tuple(row[f] for f in keyfields)
            out[k] = [float(row[f]) if '.' in row[f] else int(row[f]) for f in valfields]
    return out

def save_counts(name, keyfields, valfields, d):
    path = os.path.join(DATA, name)
    with open(path, 'w', newline='', encoding='utf-8') as fo:
        w = csv.writer(fo); w.writerow(list(keyfields)+list(valfields))
        for k in sorted(d): w.writerow(list(k)+[round(v,2) if isinstance(v,float) else v for v in d[k]])

def load_rows(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path): return []
    return list(csv.DictReader(open(path, encoding='utf-8')))

def save_rows(name, rows, fields):
    path = os.path.join(DATA, name)
    with open(path, 'w', newline='', encoding='utf-8') as fo:
        w = csv.DictWriter(fo, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for r in rows: w.writerow(r)

# ============================================================
# 1) データ更新
# ============================================================
def update_data(today):
    cur_path = os.path.join(DATA, 'cursor.txt')
    cursor = datetime.date.fromisoformat(open(cur_path).read().strip())
    nat_in = load_counts('nat_in.csv', ['ym','touban'], ['n','w'])
    nat_st = load_counts('nat_st.csv', ['ym','touban'], ['slow_n','slow_sum','dash_n','dash_sum'])
    nat_tb = load_counts('nat_teiban.csv', ['ym','touban'], ['t5n','t5top3','t6n','t6top3'])
    f_rows = load_rows('f_log.csv')
    races = load_rows('naruto_races.csv')
    boats = load_rows('naruto_boats.csv')

    d = cursor + datetime.timedelta(days=1)
    updated = False
    while d < today:   # 昨日まで
        raw = fetch_lzh('K', d)
        if raw is None:
            if (today - d).days > 3:
                print('取得不可(スキップ確定):', d)
                d += datetime.timedelta(days=1); cursor = max(cursor, d - datetime.timedelta(days=1))
                continue
            print('未公開(明日再試行):', d)
            break
        ev, nr, nb = parse_k_day(raw, d)
        for ym, tb, n, w in ev['in_']:
            rec = nat_in.setdefault((ym,tb),[0,0]); rec[0]+=n; rec[1]+=w
        for ym, tb, slow, st in ev['st']:
            rec = nat_st.setdefault((ym,tb),[0,0.0,0,0.0])
            if slow: rec[0]+=1; rec[1]+=st
            else: rec[2]+=1; rec[3]+=st
        for ym, tb, teiban, top3 in ev['tb']:
            rec = nat_tb.setdefault((ym,tb),[0,0,0,0])
            if teiban=='5': rec[0]+=1; rec[1]+=top3
            else: rec[2]+=1; rec[3]+=top3
        for date_s, tb, code in ev['fl']:
            f_rows.append(dict(date=date_s, touban=tb, code=code))
        races.extend(nr); boats.extend(nb)
        print(f'{d}: 全国{len(ev["st"])}艇 / 鳴門{len(nr)}R を追加')
        cursor = d
        updated = True
        d += datetime.timedelta(days=1)
        time.sleep(1)

    # 13か月より古い月次集計・400日より古い鳴門データを削除
    cutoff_ym = (today.replace(day=1) - datetime.timedelta(days=396)).strftime('%Y-%m')
    cutoff_d = (today - datetime.timedelta(days=400)).isoformat()
    nat_in = {k:v for k,v in nat_in.items() if k[0] >= cutoff_ym}
    nat_st = {k:v for k,v in nat_st.items() if k[0] >= cutoff_ym}
    nat_tb = {k:v for k,v in nat_tb.items() if k[0] >= cutoff_ym}
    f_rows = [r for r in f_rows if r['date'] >= cutoff_d]
    races = [r for r in races if r['date'] >= cutoff_d]
    boats = [r for r in boats if r['date'] >= cutoff_d]

    save_counts('nat_in.csv', ['ym','touban'], ['n','w'], nat_in)
    save_counts('nat_st.csv', ['ym','touban'], ['slow_n','slow_sum','dash_n','dash_sum'], nat_st)
    save_counts('nat_teiban.csv', ['ym','touban'], ['t5n','t5top3','t6n','t6top3'], nat_tb)
    save_rows('f_log.csv', f_rows, ['date','touban','code'])
    save_rows('naruto_races.csv', races,
              ['date','rno','rname','nichime','wdir','wspd','kimarite','santan','payout','win_teiban','c1_touban','c1_win'])
    save_rows('naruto_boats.csv', boats,
              ['date','rno','chaku','teiban','touban','name','motor','tenji','shinnyu','st'])
    open(cur_path,'w').write(cursor.isoformat())
    return nat_in, nat_st, nat_tb, f_rows, races, boats

# ============================================================
# 2) シグナル表の構築
# ============================================================
def build_tables(today, nat_in, nat_st, nat_tb, f_rows, races, boats):
    yr = (today - datetime.timedelta(days=365)).isoformat()
    ym12 = [(today.replace(day=1) - datetime.timedelta(days=30*i)).strftime('%Y-%m') for i in range(13)]

    # 地力（全国1コース逃げ率・12か月・縮約）
    agg = collections.defaultdict(lambda:[0,0])
    for (ym,tb),(n,w) in nat_in.items():
        if ym in ym12: agg[tb][0]+=n; agg[tb][1]+=w
    tot_n = sum(v[0] for v in agg.values()); tot_w = sum(v[1] for v in agg.values())
    gmean = tot_w/tot_n if tot_n else 0.552
    jiriki = {tb:(w+gmean*SHRINK_N0)/(n+SHRINK_N0) for tb,(n,w) in agg.items()}
    jiriki_n = {tb:n for tb,(n,w) in agg.items()}

    # 全国スローST
    st_nat = {}
    aggst = collections.defaultdict(lambda:[0,0.0])
    for (ym,tb),v in nat_st.items():
        if ym in ym12: aggst[tb][0]+=v[0]; aggst[tb][1]+=v[1]
    for tb,(n,s) in aggst.items():
        if n >= ST_NATL_MIN: st_nat[tb] = s/n

    # 当地（鳴門）スローST
    st_local = {}
    aggl = collections.defaultdict(lambda:[0,0.0])
    for b in boats:
        if b['date'] >= yr and b['shinnyu'] in ('1','2','3') and b['st'] not in ('', None):
            try: v = float(b['st'])
            except ValueError: continue
            aggl[b['touban']][0]+=1; aggl[b['touban']][1]+=v
    for tb,(n,s) in aggl.items():
        if n >= ST_LOCAL_MIN: st_local[tb] = s/n

    # まくり型（当地・3-4コース）: そのレースがまくり系決着 かつ 3/4コースの艇が1着
    km_races = {(r['date'], str(r['rno'])) for r in races
                if r['date'] >= yr and r['kimarite'] in ('まくり','まくり差し')}
    mk_n = collections.defaultdict(int)
    mk_w = collections.defaultdict(int)
    for b in boats:
        if b['date'] >= yr and b['shinnyu'] in ('3','4'):
            mk_n[b['touban']] += 1
            if b['chaku'] == '01' and (b['date'], str(b['rno'])) in km_races:
                mk_w[b['touban']] += 1
    makuri = {}
    for tb, n in mk_n.items():
        if n >= MAKURI_MIN:
            rate = mk_w.get(tb,0)/n
            if rate >= MAKURI_RATE:
                makuri[tb] = (rate, '暫定' if n < 20 else '')

    # 艇番5/6の3連対率（全国12か月）
    tb5, tb6 = {}, {}
    aggt = collections.defaultdict(lambda:[0,0,0,0])
    for (ym,tb),v in nat_tb.items():
        if ym in ym12:
            for i in range(4): aggt[tb][i]+=v[i]
    for tb,(n5,t5,n6,t6) in aggt.items():
        if n5 >= TEIBAN_MIN: tb5[tb] = t5/n5
        if n6 >= TEIBAN_MIN: tb6[tb] = t6/n6

    # F持ち（当期: 5/1 or 11/1 以降）
    if today.month >= 11 or today.month <= 4:
        kishu = datetime.date(today.year if today.month >= 11 else today.year-1, 11, 1)
    else:
        kishu = datetime.date(today.year, 5, 1)
    fcount = collections.defaultdict(int)
    for r in f_rows:
        if r['date'] >= kishu.isoformat(): fcount[r['touban']] += 1

    # レース番号表（鳴門・直近12か月）
    rno_table = []
    for rno in range(1, 13):
        rs = [r for r in races if r['date'] >= yr and int(r['rno'])==rno]
        if not rs: continue
        in1 = sum(int(r['c1_win']) for r in rs)/len(rs)
        pays = [int(r['payout']) for r in rs if r['payout']]
        man = sum(1 for p in pays if p>=10000)/len(pays) if pays else 0
        rno_table.append(dict(rno=rno, n=len(rs), in1=round(in1*100,1), man=round(man*100,1)))

    # 企画レース表
    kikaku_table = {}
    for name in KIKAKU:
        rs = [r for r in races if r['date'] >= yr and r['rname']==name]
        if rs:
            in1 = sum(int(r['c1_win']) for r in rs)/len(rs)
            pays = [int(r['payout']) for r in rs if r['payout']]
            man = sum(1 for p in pays if p>=10000)/len(pays) if pays else 0
            kikaku_table[name] = dict(n=len(rs), in1=round(in1*100,1), man=round(man*100,1))

    return dict(jiriki=jiriki, jiriki_n=jiriki_n, st_nat=st_nat, st_local=st_local,
                st_local_n={tb:n for tb,(n,s) in aggl.items()},
                makuri=makuri, tb5=tb5, tb6=tb6, fcount=fcount, gmean=gmean,
                rno_table=rno_table, kikaku_table=kikaku_table)

# ============================================================
# 3) 当日出走表 → data.json
# ============================================================
B_HDR = re.compile(r'(\d{1,2})R\s+(.*?)\s*H\d{3,4}m.*?電話投票締切予定(\d{1,2}):(\d{2})')

def build_racecard(today, T):
    raw = fetch_lzh('B', today)
    result = dict(updated=(datetime.datetime.now(datetime.timezone.utc)
                           + datetime.timedelta(hours=9)).strftime('%Y-%m-%d %H:%M JST'),
                  date=today.isoformat(), kaisai=False, races=[],
                  rno_table=T['rno_table'], kikaku_table=T['kikaku_table'])
    if raw is None or (JCD+'BBGN') not in raw:
        return result
    blk = raw.split(JCD+'BBGN')[1].split(JCD+'BEND')[0]
    hdr = unicodedata.normalize('NFKC', blk[:300])
    m = DAY_RE.search(hdr)
    result['nichime'] = int(m.group(1)) if m else ''
    title = ''
    for l in blk.split('\n')[:10]:
        l2 = l.replace('\u3000','').strip()
        if l2 and '競走' in l2 and '照合' not in l2 and '成績' not in l2:
            title = l2; break
    result['title'] = title
    result['kaisai'] = True

    races = []
    cur = None
    for line in blk.split('\n'):
        nl = unicodedata.normalize('NFKC', line)
        hm = B_HDR.search(nl)
        if hm:
            if cur: races.append(cur)
            cur = dict(rno=int(hm.group(1)), rname=hm.group(2).strip(),
                       deadline=f'{int(hm.group(3)):02d}:{hm.group(4)}', boats=[])
            continue
        if cur is None: continue
        if len(line) > 18 and line[0] in '123456' and line[1]==' ' and line[2:6].isdigit():
            tks = line[18:].split()
            cur['boats'].append(dict(
                teiban=line[0], touban=line[2:6],
                name=line[6:10].replace('\u3000',''),
                grade=line[16:18],
                natl_rate=tks[0] if len(tks)>0 else '',
                motor=tks[4] if len(tks)>4 else '', motor2=tks[5] if len(tks)>5 else ''))
    if cur: races.append(cur)

    rno_in1 = {r['rno']: r['in1'] for r in T['rno_table']}
    for r in races:
        score = 0; flags = []
        for b in r['boats']:
            tb = b['touban']; badges = []
            # F持ち（全艇表示・スコアは1号艇のみ）
            fc = T['fcount'].get(tb, 0)
            if fc >= 2:
                badges.append('F2持ち')
                if b['teiban']=='1': score += 2; flags.append('1号艇F2持ち')
            elif fc == 1:
                badges.append('F1持ち')
                if b['teiban']=='1': score += 1; flags.append('1号艇F1持ち')
            # ST遅れ（1号艇のみ判定）
            if b['teiban']=='1':
                stv = T['st_local'].get(tb)
                src = '当地'
                if stv is None:
                    stv = T['st_nat'].get(tb); src = '全国'
                if stv is not None:
                    b['st_avg'] = f'{stv:.2f}({src})'
                    if stv > ST_LATE:
                        score += 1; flags.append(f'1号艇ST遅れ {stv:.2f}({src})')
                        badges.append('ST遅れ')
                j = T['jiriki'].get(tb)
                if j is not None:
                    b['jiriki'] = round(j*100)
            # まくり型（3・4号艇）
            if b['teiban'] in '34' and tb in T['makuri']:
                rate, prov = T['makuri'][tb]
                badges.append('まくり型' + ('△' if prov else ''))
                if 'まくり型(3/4)' not in flags:
                    score += 1; flags.append('まくり型(3/4)')
            # 艇番5/6の外し候補
            if b['teiban']=='6':
                r6 = T['tb6'].get(tb)
                if r6 is not None:
                    b['teiban_rate'] = round(r6*100)
                    if r6 < TEIBAN_LOW: badges.append('6ヒモ外し●')
            if b['teiban']=='5':
                r5 = T['tb5'].get(tb)
                if r5 is not None:
                    b['teiban_rate'] = round(r5*100)
                    if r5 < TEIBAN_LOW: badges.append('5低率')
            b['badges'] = badges
        # ラベルと方針
        base_in1 = rno_in1.get(r['rno'])
        if r['rname'] in KIKAKU:
            label, policy = KIKAKU[r['rname']]
            kt = T['kikaku_table'].get(r['rname'])
            if kt: base_in1 = kt['in1']
        elif base_in1 is not None and base_in1 < 40:
            label, policy = 'イン受難ゾーン', f'基礎イン率{base_in1:.0f}%。アンチイン（頭2〜4）を検討する枠。'
        elif base_in1 is not None and base_in1 >= 58:
            label, policy = 'イン堅め', f'基礎イン率{base_in1:.0f}%。穴は控えめに。'
        else:
            label, policy = '中間', '基礎率は平均圏。フラグ次第で判断。'
        if score >= 2:
            policy += f' 崩れ筋スコア{score}: 1号艇を疑う（アンチイン厚め）。'
        outs = [b for b in r['boats'] if '6ヒモ外し●' in b.get('badges',[])]
        if outs:
            policy += ' 6号艇は3着からも外して点数圧縮。'
        r['label'] = label; r['policy'] = policy
        r['base_in1'] = base_in1; r['score'] = score; r['flags'] = flags
    result['races'] = races
    return result

# ============================================================
def main():
    today = jst_today()
    print('=== 鳴門ツール 日次実行:', today, '===')
    nat_in, nat_st, nat_tb, f_rows, races, boats = update_data(today)
    T = build_tables(today, nat_in, nat_st, nat_tb, f_rows, races, boats)
    print(f'表構築: 地力{len(T["jiriki"])}人 / 当地ST{len(T["st_local"])}人 / '
          f'まくり型{len(T["makuri"])}人 / F持ち{sum(1 for v in T["fcount"].values() if v>=1)}人')
    card = build_racecard(today, T)
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump(card, open(OUT_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('開催:', card['kaisai'], '/ レース数:', len(card['races']))
    print('保存:', OUT_JSON)

if __name__ == '__main__':
    main()
