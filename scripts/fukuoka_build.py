# -*- coding: utf-8 -*-
"""
福岡 穴党ツール：日次ビルド
  1) K/Bファイルのキャッシュ更新（直近370日・skip-if-exists）
  2) 博多QF天文潮位の取得
  3) 全国パース → 5表（ST・F持ち・絞りまくり・残し・壁）
  4) モーター世代の自動検出 → 現行世代モーター表
  5) うねり窓カレンダー（今後90日）
  出力: fukuoka/data/*.csv ＋ data/fukuoka_signals.json
実行: python scripts/fukuoka_build.py（GitHub Actionsから毎朝）
"""
import os, re, csv, json, glob, unicodedata, urllib.request
from datetime import date, timedelta, datetime, timezone
from collections import defaultdict

import pandas as pd
import numpy as np
import lhafile

# ================= 設定 =================
JCD = '22'                      # 福岡
WINDOW_DAYS = 370               # キャッシュ保持日数
LZH_K, LZH_B = 'data/lzh_k', 'data/lzh_b'
OUT_DIR = 'fukuoka/data'        # ページ用出力
SIG_JSON = 'data/fukuoka_signals.json'
TIDE_ST = 'QF'                  # 博多（※HKは別地点）
TIDE_DIR = 'data/tide'
GEN_FALLBACK = '2026-02-18'     # モーター世代起点（自動検出失敗時）
UA = {'User-Agent': 'Mozilla/5.0'}
JST = timezone(timedelta(hours=9))

def today_jst():
    return datetime.now(JST).date()

# ================= 1) ダウンロード =================
def fetch(url, path, min_size=1000):
    if os.path.exists(path) and os.path.getsize(path) > min_size:
        return True
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        if len(data) < min_size:
            return False
        with open(path, 'wb') as f:
            f.write(data)
        return True
    except Exception:
        return False

def update_cache():
    os.makedirs(LZH_K, exist_ok=True); os.makedirs(LZH_B, exist_ok=True)
    end = today_jst(); start = end - timedelta(days=WINDOW_DAYS - 1)
    d = start; got = 0
    while d <= end:
        ym, ymd = d.strftime('%Y%m'), d.strftime('%y%m%d')
        got += fetch(f'https://www1.mbrace.or.jp/od2/K/{ym}/k{ymd}.lzh', f'{LZH_K}/k{ymd}.lzh')
        got += fetch(f'https://www1.mbrace.or.jp/od2/B/{ym}/b{ymd}.lzh', f'{LZH_B}/b{ymd}.lzh')
        d += timedelta(days=1)
    # 窓より古いキャッシュを削除
    cutoff = start.strftime('%y%m%d')
    for p in glob.glob(f'{LZH_K}/k*.lzh') + glob.glob(f'{LZH_B}/b*.lzh'):
        if os.path.basename(p)[1:7] < cutoff:
            os.remove(p)

def update_tide():
    os.makedirs(TIDE_DIR, exist_ok=True)
    y = today_jst().year
    for yy in (y, y + 1):
        fetch(f'https://www.data.jma.go.jp/gmd/kaiyou/data/db/tide/suisan/txt/{yy}/{TIDE_ST}.txt',
              f'{TIDE_DIR}/{TIDE_ST}_{yy}.txt', min_size=1000)

# ================= 2) Kファイルパース =================
RE_HEADER = re.compile(r'^\s{0,6}(\d{1,2})R\s+(\S+)\s+H(\d+)m(.*)$')
RE_DAY = re.compile(r'第\s*(\d+)\s*日')

def is_finisher(line):
    return (len(line) >= 30 and line[0:2] == '  '
            and line[6:7].isdigit() and line[8:12].isdigit())

def parse_finisher(line):
    tail = line[21:].split()
    motor = exhib = course = st = None
    if len(tail) >= 5:
        motor = tail[0]
        try: exhib = float(tail[2])
        except Exception: pass
        if len(tail[3]) == 1 and tail[3] in '123456':
            course = tail[3]
        st = tail[4]
    return dict(rank=line[2:4].strip(), boat=line[6], regno=line[8:12],
                name=line[13:21].replace('\u3000', '').strip(),
                motor=motor, exhib=exhib, course=course, st=st)

def parse_venue_block(blk):
    lines = blk.split('\n'); day_n = None
    races, cur = [], None
    for ln in lines:
        ln = ln.rstrip('\r')
        if day_n is None:
            m = RE_DAY.search(unicodedata.normalize('NFKC', ln))
            if m: day_n = int(m.group(1))
        mh = RE_HEADER.match(ln)
        if mh and 'm' in ln:
            if cur: races.append(cur)
            cur = dict(race=int(mh.group(1)), name=mh.group(2), kimarite=None, fins=[])
            continue
        if cur is not None and cur['kimarite'] is None and 'ﾚｰｽﾀｲﾑ' in ln:
            k = ln.split('ﾚｰｽﾀｲﾑ')[-1].replace('\u3000', '').strip()
            cur['kimarite'] = k or None
            continue
        if cur is not None and is_finisher(ln):
            cur['fins'].append(parse_finisher(ln))
    if cur: races.append(cur)
    return day_n, [r for r in races if len(r['fins']) >= 4]

def parse_all_k():
    """全国エントリー＋レース（12か月）"""
    ents, races = [], []
    for f in sorted(glob.glob(f'{LZH_K}/k*.lzh')):
        ymd = os.path.basename(f)[1:7]
        d = f'20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}'
        try:
            lf = lhafile.Lhafile(f)
            raw = lf.read(lf.infolist()[0].filename).decode('shift_jis', errors='replace')
        except Exception:
            continue
        for m in re.finditer(r'(\d{2})KBGN(.*?)\1KEND', raw, re.S):
            jcd, blk = m.group(1), m.group(2)
            _, rs = parse_venue_block(blk)
            for r in rs:
                c1 = [x for x in r['fins'] if x['course'] == '1']
                c2 = [x for x in r['fins'] if x['course'] == '2']
                win = [x for x in r['fins'] if x['rank'] == '01']
                races.append(dict(date=d, jcd=jcd, race=r['race'],
                                  kimarite=r['kimarite'] or '',
                                  win_course=win[0]['course'] if win else '',
                                  c1_regno=c1[0]['regno'] if len(c1) == 1 else '',
                                  c1_win=1 if (len(c1) == 1 and c1[0]['rank'] == '01') else 0,
                                  c2_regno=c2[0]['regno'] if len(c2) == 1 else ''))
                for x in r['fins']:
                    ents.append(dict(date=d, jcd=jcd, race=r['race'], regno=x['regno'],
                                     name=x['name'], boat=x['boat'], course=x['course'] or '',
                                     rank=x['rank'], st=x['st'] or '', motor=x['motor'],
                                     exhib=x['exhib']))
    return pd.DataFrame(ents), pd.DataFrame(races)

# ================= 3) モーター世代検出（B 2率リセット） =================
RE_BENT = re.compile(r'^([1-6])\s?(\d{4})')
RE_BTAIL = re.compile(r'(A1|A2|B1|B2)\s*(\d{1,2}\.\d\d)\s*(\d{1,3}\.\d\d)\s*(\d{1,2}\.\d\d)'
                      r'\s*(\d{1,3}\.\d\d)\s*(\d{1,3})\s*(\d{1,3}\.\d\d)(\d{1,3})\s*(\d{1,3}\.\d\d)')

def detect_gen_start():
    resets = []
    for f in sorted(glob.glob(f'{LZH_B}/b*.lzh')):
        ymd = os.path.basename(f)[1:7]
        d = f'20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}'
        try:
            lf = lhafile.Lhafile(f)
            raw = lf.read(lf.infolist()[0].filename).decode('shift_jis', errors='replace')
        except Exception:
            continue
        if f'{JCD}BBGN' not in raw:
            continue
        blk = raw.split(f'{JCD}BBGN')[1].split(f'{JCD}BEND')[0]
        vals = [float(m.group(7)) for ln in blk.split('\n')
                if RE_BENT.match(ln) and (m := RE_BTAIL.search(ln))]
        if vals and sum(vals) / len(vals) < 5.0:
            resets.append(d)
    return resets[0] if resets else GEN_FALLBACK  # 新品期間の初日＝世代起点

# ================= 4) 表の構築 =================
def build_tables(ne, nr):
    os.makedirs(OUT_DIR, exist_ok=True)
    names = ne.sort_values('date').groupby('regno')['name'].last()
    fe = ne[ne['jcd'] == JCD].copy()
    fr = nr[nr['jcd'] == JCD].copy()
    ne['st_n'] = pd.to_numeric(ne['st'], errors='coerce')
    ne['slow'] = ne['course'].isin(['1', '2', '3'])
    sig = defaultdict(dict)

    # --- ① ST（当地→全国フォールバック） ---
    def st_agg(d):
        g = d[d['st_n'].notna()].groupby(['regno', 'slow'])['st_n'].agg(['count', 'mean']).unstack()
        return g
    ga = st_agg(ne); gl = st_agg(ne[ne['jcd'] == JCD])
    st_rows = []
    for reg in ga.index:
        row = {'regno': reg, '選手名': names.get(reg, '')}
        for slow, lab in [(True, 'slow'), (False, 'dash')]:
            n_l = gl[('count', slow)].get(reg, 0) if reg in gl.index else 0
            v_l = gl[('mean', slow)].get(reg, np.nan) if reg in gl.index else np.nan
            v_a = ga[('mean', slow)].get(reg, np.nan)
            use_local = (n_l or 0) >= 10
            v = v_l if use_local else v_a
            row[f'{lab}_st'] = round(v, 3) if v == v else None
            row[f'{lab}_src'] = '当地' if use_local else '全国'
            row[f'{lab}_flag'] = ('遅れ' if v == v and v > 0.18 else
                                  '巧者' if v == v and v <= 0.13 else '')
        st_rows.append(row)
        sig[reg].update(name=row['選手名'], st_slow=row['slow_st'], st_slow_src=row['slow_src'],
                        st_slow_flag=row['slow_flag'], st_dash=row['dash_st'],
                        st_dash_flag=row['dash_flag'])
    pd.DataFrame(st_rows).to_csv(f'{OUT_DIR}/st.csv', index=False, encoding='utf-8-sig')

    # --- ② F持ち（当期：5/1 or 11/1起点） ---
    t = today_jst()
    period = date(t.year, 5, 1) if t.month >= 5 else date(t.year - 1, 11, 1)
    if t.month >= 11: period = date(t.year, 11, 1)
    cur = ne[ne['date'] >= period.isoformat()]
    fmap = cur[cur['rank'] == 'F'].groupby('regno').size()
    for reg, n in fmap.items():
        sig[reg]['f'] = int(n)
        sig[reg]['name'] = sig[reg].get('name') or names.get(reg, '')
    fdf = pd.DataFrame([{'regno': r, '選手名': names.get(r, ''), 'F本数': int(n),
                         '区分': 'F2+' if n >= 2 else 'F1'} for r, n in fmap.items()])
    fdf.to_csv(f'{OUT_DIR}/f_kitai.csv', index=False, encoding='utf-8-sig')

    # --- ④ 絞りまくり（当地12か月・15走・15-19暫定・率15%） ---
    f34 = fe[fe['course'].isin(['3', '4'])]
    n34 = f34.groupby('regno').size()
    kimmap = fr.set_index(['date', 'race'])['kimarite']
    w = f34[f34['rank'] == '01'].copy()
    w['kim'] = [kimmap.get((d, r), '') for d, r in zip(w['date'], w['race'])]
    mw = w[w['kim'].isin(['まくり', 'まくり差し'])].groupby('regno').size()
    mk_rows = []
    for reg in n34.index:
        n, m = int(n34[reg]), int(mw.get(reg, 0))
        rate = m / n if n else 0
        flag = '●' if (n >= 15 and rate >= 0.15) else ''
        prov = '暫定' if (flag and n <= 19) else ''
        mk_rows.append({'regno': reg, '選手名': names.get(reg, ''), 'n34': n,
                        'まくり系1着': m, '率': round(rate, 3), '判定': flag, '暫定': prov})
        if flag:
            sig[reg].update(makuri=True, makuri_rate=round(rate, 3), makuri_prov=bool(prov))
    pd.DataFrame(mk_rows).sort_values('率', ascending=False).to_csv(
        f'{OUT_DIR}/makuri.csv', index=False, encoding='utf-8-sig')

    # --- ⑤⑥⑦＋艇番5/6（残し表） ---
    def out3(d):
        o = d[d['course'].isin(['4', '5', '6'])]
        return o.groupby('regno')['rank'].agg(n='size', r3=lambda s: (s == '03').mean())
    o_l, o_a = out3(fe), out3(ne)
    c1 = ne[ne['course'] == '1'].groupby('regno')['rank'].agg(
        n1c='size', win=lambda s: (s == '01').sum(), p2=lambda s: (s == '02').sum())
    c1['lose'] = c1['n1c'] - c1['win']
    c1['rate'] = c1['p2'] / c1['lose'].replace(0, np.nan)
    valid = (c1['n1c'] >= 40) & (c1['lose'] >= 20)
    qh = c1.loc[valid, 'rate'].quantile(0.9); ql = c1.loc[valid, 'rate'].quantile(0.1)
    c6 = ne[ne['course'] == '6'].groupby('regno')['rank'].agg(
        n6='size', p2=lambda s: (s == '02').mean(), p3=lambda s: (s == '03').mean())
    b5 = ne[ne['boat'] == '5'].groupby('regno')['rank'].agg(
        n='size', t3=lambda s: s.isin(['01', '02', '03']).mean())
    b6 = ne[ne['boat'] == '6'].groupby('regno')['rank'].agg(
        n='size', t3=lambda s: s.isin(['01', '02', '03']).mean())
    nok_rows = []
    for reg in names.index:
        r = {'regno': reg, '選手名': names.get(reg, '')}
        if reg in o_l.index and o_l.loc[reg, 'n'] >= 25:
            r['外3着率'], r['外3着源'] = round(o_l.loc[reg, 'r3'], 3), '当地'
        elif reg in o_a.index:
            r['外3着率'], r['外3着源'] = round(o_a.loc[reg, 'r3'], 3), '全国'
        if reg in c1.index and valid.get(reg, False):
            rt = c1.loc[reg, 'rate']
            r['残し率'] = round(rt, 3)
            r['型'] = '残す型' if rt >= qh else ('飛ぶ型' if rt <= ql else '')
            if r['型']: sig[reg]['n1_type'] = r['型']; sig[reg]['n1_rate'] = r['残し率']
        if reg in c6.index and c6.loc[reg, 'n6'] >= 40:
            r['6コ2着率'], r['6コ3着率'] = round(c6.loc[reg, 'p2'], 3), round(c6.loc[reg, 'p3'], 3)
            sig[reg]['k6_p2'], sig[reg]['k6_p3'] = r['6コ2着率'], r['6コ3着率']
        for b, g in [('5', b5), ('6', b6)]:
            if reg in g.index and g.loc[reg, 'n'] >= 15:
                r[f'艇番{b}乗艇'], r[f'艇番{b}率'] = int(g.loc[reg, 'n']), round(g.loc[reg, 't3'], 3)
                sig[reg][f'b{b}_top3'] = r[f'艇番{b}率']
                if g.loc[reg, 't3'] < 0.25:
                    sig[reg][f'b{b}_low'] = True
        nok_rows.append(r)
    pd.DataFrame(nok_rows).to_csv(f'{OUT_DIR}/nokoshi.csv', index=False, encoding='utf-8-sig')

    # --- ⑫ 壁（全国12か月） ---
    p0 = c1['win'].sum() / c1['n1c'].sum()
    shrunk = ((c1['win'] + 20 * p0) / (c1['n1c'] + 20)).rename('shr')
    wr = nr[(nr['c1_regno'] != '') & (nr['c2_regno'] != '')].copy()
    wr = wr.join(shrunk, on='c1_regno')
    wr = wr[wr['shr'].notna()]
    g2 = wr.groupby('c2_regno').agg(n2=('c1_win', 'size'), nige=('c1_win', 'mean'),
                                    exp=('shr', 'mean'))
    g2['wall'] = (g2['nige'] - g2['exp']) * 100
    lost = wr[wr['c1_win'] == 0]
    g2 = g2.join(lost.groupby('c2_regno').agg(
        own=('win_course', lambda s: (s == '2').mean()),
        mak=('kimarite', lambda s: s.isin(['まくり', 'まくり差し']).mean())))
    q = g2['n2'] >= 40
    hi_t = g2.loc[q, 'wall'].quantile(0.9); lo_t = g2.loc[q, 'wall'].quantile(0.1)
    kb_rows = []
    for reg, r in g2[q].iterrows():
        flag = '壁強' if r['wall'] >= hi_t else ('壁弱' if r['wall'] <= lo_t else '')
        sub = ''
        if flag == '壁弱':
            sub = '食う型' if r['own'] >= 0.40 else ('素通し型' if r['mak'] >= 0.35 else '')
        kb_rows.append({'regno': reg, '選手名': names.get(reg, ''), 'n2': int(r['n2']),
                        '壁力': round(r['wall'], 1), '判定': flag, 'タイプ': sub})
        if flag:
            sig[reg].update(kabe=flag, kabe_val=round(r['wall'], 1), kabe_type=sub)
    pd.DataFrame(kb_rows).sort_values('壁力').to_csv(
        f'{OUT_DIR}/kabe.csv', index=False, encoding='utf-8-sig')

    # --- ⑪ モーター（現行世代） ---
    gen = detect_gen_start()
    fg = fe[fe['date'] >= gen].copy()
    fg['motor'] = pd.to_numeric(fg['motor'], errors='coerce')
    fg = fg[fg['motor'].notna()]
    fg['top2'] = fg['rank'].isin(['01', '02'])
    fg['top3'] = fg['rank'].isin(['01', '02', '03'])
    ex = fg.groupby(['date', 'race'])['exhib'].transform('mean')
    fg['exdev'] = fg['exhib'] - ex
    mt = fg.groupby('motor').agg(n=('top2', 'size'), r2=('top2', 'mean'),
                                 r3=('top3', 'mean'), ex=('exdev', 'mean'))
    qh2 = mt[mt['n'] >= 30]['r2'].quantile(0.8); ql2 = mt[mt['n'] >= 30]['r2'].quantile(0.2)
    motors = {}
    mt_rows = []
    for no, r in mt.iterrows():
        flag = ''
        if r['n'] >= 30:
            flag = '高●' if r['r2'] >= qh2 else ('低▲' if r['r2'] <= ql2 else '')
        motors[str(int(no))] = dict(n=int(r['n']), r2=round(r['r2'] * 100, 1),
                                    r3=round(r['r3'] * 100, 1), flag=flag)
        mt_rows.append({'motor': int(no), 'n': int(r['n']), '2連率': round(r['r2'] * 100, 1),
                        '3連率': round(r['r3'] * 100, 1), '展示偏差': round(r['ex'], 3), '判定': flag})
    pd.DataFrame(mt_rows).sort_values('2連率', ascending=False).to_csv(
        f'{OUT_DIR}/motor.csv', index=False, encoding='utf-8-sig')

    # --- レース番号ベースライン（表示用） ---
    fk1 = fe[fe['course'] == '1']
    rb = fk1.groupby('race')['rank'].agg(win=lambda s: (s == '01').mean()).round(3)
    race_base = {str(k): round(v * 100, 1) for k, v in rb['win'].items()} if isinstance(rb, pd.DataFrame) else {str(k): round(v * 100, 1) for k, v in rb.items()}

    return sig, motors, gen, race_base

# ================= 5) うねり窓カレンダー =================
def tide_days(year):
    path = f'{TIDE_DIR}/{TIDE_ST}_{year}.txt'
    out = {}
    if not os.path.exists(path):
        return out
    for ln in open(path):
        if len(ln) < 80 or ln[78:80] != TIDE_ST:
            continue
        d = f"20{int(ln[72:74]):02d}-{int(ln[74:76]):02d}-{int(ln[76:78]):02d}"
        out[d] = [int(ln[i*3:i*3+3]) for i in range(24)]
    return out

def unari_calendar():
    t = today_jst()
    tides = tide_days(t.year); tides.update(tide_days(t.year + 1))
    cal = []
    for i in range(90):
        d = (t + timedelta(days=i)).isoformat()
        vals = tides.get(d)
        if not vals:
            continue
        hrs = [h for h in range(11, 18) if vals[h] >= 170]
        if hrs:
            cal.append(dict(date=d, start=min(hrs), end=max(hrs) + 1,
                            peak=max(vals[h] for h in hrs)))
    return cal

# ================= main =================
def main():
    print('cache update...'); update_cache(); update_tide()
    print('parse K...'); ne, nr = parse_all_k()
    print(f'  national: {len(nr)} races / {len(ne)} entries')
    sig, motors, gen, race_base = build_tables(ne, nr)
    cal = unari_calendar()
    os.makedirs(os.path.dirname(SIG_JSON), exist_ok=True)
    with open(SIG_JSON, 'w', encoding='utf-8') as f:
        json.dump(dict(updated=datetime.now(JST).isoformat(timespec='minutes'),
                       gen_start=gen, racers=sig, motors=motors,
                       race_base=race_base, unari=cal),
                  f, ensure_ascii=False)
    print(f'signals: {len(sig)}人 / motors: {len(motors)}機 / 世代起点: {gen} / 窓: {len(cal)}日')

if __name__ == '__main__':
    main()
