# -*- coding: utf-8 -*-
"""江戸川(03) 穴党ツール — 毎朝の自動実行スクリプト

正本：docs/edogawa/spec_edogawa.md（江戸川_穴党ツール_仕様書）
     docs/edogawa/HANDOVER.md   （アプリ実装仕様）

毎朝 GitHub Actions から実行され、次の順に処理します。

  1) データ更新   … 前回以降のKファイルだけを取得し、月×選手のカウンタに足し込む
                    （鳴門・戸田と同じ差分蓄積。cursor.txt が前回処理日を覚えている）
  2) テーブル生成 … 当地4表＋全国2表を毎朝作り直す
                      data/edogawa/江戸川_ST表.csv
                      data/edogawa/江戸川_絞りまくり表.csv
                      data/edogawa/江戸川_残し表.csv
                      data/edogawa/江戸川_壁表.csv
                      data/edogawa/全国_1コース地力表.csv
                      data/edogawa/全国_F持ち_当期.csv
  3) 当日出走表   … Bファイルから江戸川の出走表を取り、regnoでJOINして
                    edogawa/data.json を出力（edogawa/index.html が読む）

★江戸川で採点してよいのは仕様書§4の確定シグナルだけ。以下は棄却済み（実装禁止）:
    ・潮位・潮流（東京検潮所TK）… 風を固定すると独立効果ゼロ。R²増分+0.001
    ・向かい風×まくり艇の加点   … 南風はまくりを増やさない（受け皿は2コース差し）
    ・風の加点                  … 有意だが朝は未知＋織り込み濃厚。表示のみ
    ・レース番号 1R・9R の加点  … 1R=WFで減衰／9R=符号反転
    ・モーター(⑪)              … 交換月が未特定でスコープ外

TODO(将来): 6R単独の機構解明（なぜ5R・4Rでなく6Rが底か）。解明できれば⑭'を正式採用に格上げ
TODO(将来): モーター表（交換月特定→津方式のメンバー補正残差ウォークフォワード）
TODO(オッズ1年蓄積後): EV検証。最優先＝初日の1号艇が過小に嫌われているか（仕様書§5）

テスト実行: EDO_DATE=2026-07-15 python scripts/edogawa/edogawa_daily.py
初期構築  : python scripts/edogawa/edogawa_daily.py --backfill 365
"""
import os
import re
import csv
import sys
import json
import time
import datetime
import tempfile
import unicodedata
import urllib.request
from collections import defaultdict

import lhafile

# ==================================================================
# 設定
# ==================================================================
JCD = '03'                 # 江戸川
DATA = os.environ.get('EDO_DATA', 'data/edogawa')
OUT_JSON = os.environ.get('EDO_OUT', 'edogawa/data.json')
KCACHE = os.environ.get('EDO_KCACHE', os.path.join(tempfile.gettempdir(), 'edo_k'))

WINDOW_DAYS = 365
KEEP_DAYS = 396
ST_LATE = 0.18             # ①スロー遅れ（採用スローSTがこれ超）
ST_GOOD = 0.13             # スロー巧者
ST_LOCAL_MIN = 10          # 当地STを採用する最低走数（未満は全国で代替）
MAKURI_MIN = 15            # ④絞りまくりの最低走数（当地3-4コース）
MAKURI_RATE = 0.15         # ④絞りまくりの閾値
MAKURI_PROV = 20           # これ未満なら暫定フラグ
WALL_MIN = 40              # ⑫壁表の最低2コース進入数
ZAN1C_MIN = 40             # ⑥残す/飛ぶの最低1コース進入数
ZAN1C_LOSE_MIN = 20        # 同・最低負け数
ZAN6_MIN = 40              # ⑦6コース残しの最低6コース進入数
BOAT_MIN = 15              # 11-5 艇番5/6の最低乗艇数
BOAT6_LOW = 0.25           # 艇番6_3連対率がこれ未満で「6ヒモ外し●」
OUTER_MIN = 25             # ⑤外3着の最低外進入数
SHRINK_K = 20              # 顔ぶれ補正の経験ベイズ縮小

MAKURI_KEI = ('まくり', 'まくり差し')
UA = {'User-Agent': 'Mozilla/5.0 (edogawa-tool)'}


def jst_today():
    if os.environ.get('EDO_DATE'):
        return datetime.date.fromisoformat(os.environ['EDO_DATE'])
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).date()


TODAY = jst_today()


def period_start():
    """今の級別審査期間の開始日（前期5/1・後期11/1）。⑩F持ちは当期のみ数える。"""
    t = TODAY
    if 5 <= t.month <= 10:
        return datetime.date(t.year, 5, 1)
    if t.month >= 11:
        return datetime.date(t.year, 11, 1)
    return datetime.date(t.year - 1, 11, 1)


# ==================================================================
# 1. ファイル取得
# ==================================================================
def fetch_lzh(kind, d):
    ds = d.strftime('%y%m%d')
    lc = kind.lower()
    os.makedirs(KCACHE, exist_ok=True)
    path = os.path.join(KCACHE, '%s%s.lzh' % (lc, ds))
    if not (os.path.exists(path) and os.path.getsize(path) > 1000):
        url = 'https://www1.mbrace.or.jp/od2/%s/%s/%s%s.lzh' % (kind, d.strftime('%Y%m'), lc, ds)
        for i in range(3):
            try:
                raw = urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=90).read()
                if len(raw) < 1000:
                    return None
                with open(path, 'wb') as f:
                    f.write(raw)
                break
            except Exception:
                time.sleep(2 + i * 2)
        else:
            return None
    try:
        lf = lhafile.Lhafile(path)
        return lf.read(lf.infolist()[0].filename).decode('shift_jis', errors='replace')
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        return None


# ==================================================================
# 2. Kファイルのパース
# ==================================================================
RACE_HDR = re.compile(r'^\s{2,}(\d{1,2})R\s+(.*?)\s+H(\d{3,4})m')
WIND_RE = re.compile(r'風[\s　]*([東西南北]{1,3})[\s　]*(\d+)m')
SANTAN = re.compile(r'3連単\s+([1-6]-[1-6]-[1-6])\s+(\d+)\s+人気\s+(\d+)')
DAY_RE = re.compile(r'第\s*(\d+)\s*日')
FL_RE = re.compile(r'^[FL]')


def is_finisher(line):
    return (len(line) > 21 and line[:2] == '  '
            and line[6].isdigit() and line[8:12].isdigit())


def parse_k_day(raw, date):
    """1日分のKファイル → (全国エントリ, 壁ペア, 江戸川レース, F/L事故, 名前)"""
    nat, wall, ed_races, fl, names = [], [], [], [], {}
    for vm in re.finditer(r'(\d{2})KBGN(.*?)\1KEND', raw, re.S):
        vcd, blk = vm.group(1), vm.group(2)
        is_ed = (vcd == JCD)
        nichime = ''
        md = DAY_RE.search(unicodedata.normalize('NFKC', blk[:400]))
        if md:
            nichime = int(md.group(1))
        cur, races = None, []
        for line in blk.split('\n'):
            hm = RACE_HDR.match(line)
            if hm and ('風' in line or '波' in line):
                if cur:
                    races.append(cur)
                wm = WIND_RE.search(line)
                cur = dict(rno=int(hm.group(1)),
                           rname=hm.group(2).replace('　', '').strip(),
                           wdir=(wm.group(1) if wm else ''),
                           wspd=(int(wm.group(2)) if wm else ''),
                           kimarite='', boats=[], payout='', ninki='', nichime=nichime)
                continue
            if cur is None:
                continue
            if 'ﾚｰｽﾀｲﾑ' in line:
                cur['kimarite'] = line.split('ﾚｰｽﾀｲﾑ')[-1].replace('　', '').strip()
                continue
            if is_finisher(line):
                tail = line[21:].split()
                course = tail[3] if (len(tail) >= 4 and len(tail[3]) == 1
                                     and tail[3] in '123456') else ''
                st, st_raw = None, (tail[4] if len(tail) >= 5 else '')
                if st_raw and not FL_RE.match(st_raw):
                    try:
                        v = float(st_raw)
                        if 0.0 <= v <= 1.0:
                            st = v
                    except ValueError:
                        pass
                nm = line[13:21].replace('　', '').strip()
                if nm:
                    names[line[8:12]] = nm
                cur['boats'].append(dict(chaku=line[2:4].strip(), teiban=line[6],
                                         regno=line[8:12], course=course, st=st,
                                         st_raw=st_raw))
                continue
            sm = SANTAN.search(unicodedata.normalize('NFKC', line))
            if sm:
                cur['payout'], cur['ninki'] = int(sm.group(2)), int(sm.group(3))
        if cur:
            races.append(cur)

        for r in races:
            mk = r['kimarite'] in MAKURI_KEI
            c1 = next((b for b in r['boats'] if b['course'] == '1'), None)
            c2 = next((b for b in r['boats'] if b['course'] == '2'), None)
            if c1 and c2:
                wall.append((c2['regno'], c1['regno'],
                             1 if c1['chaku'] == '01' else 0,
                             1 if c2['chaku'] == '01' else 0,
                             1 if mk else 0))
            for b in r['boats']:
                # ⑩F持ちは全国・当期。事故はコース不明でも数える
                if b['st_raw'].startswith('F'):
                    fl.append((b['regno'], 'F'))
                elif b['st_raw'].startswith('L'):
                    fl.append((b['regno'], 'L'))
                if not b['course']:
                    continue
                nat.append((b['regno'], int(b['course']), int(b['teiban']),
                            b['chaku'], b['st'], 1 if (mk and b['chaku'] == '01') else 0, is_ed))
            if is_ed:
                win = next((b for b in r['boats'] if b['chaku'] == '01'), None)
                ed_races.append(dict(
                    date=date.isoformat(), rno=r['rno'], rname=r['rname'],
                    nichime=r['nichime'], kimarite=r['kimarite'],
                    wdir=r['wdir'], wspd=r['wspd'], payout=r['payout'], ninki=r['ninki'],
                    win_course=(win['course'] if win else ''),
                    win_teiban=(win['teiban'] if win else ''),
                    entries=len(r['boats'])))
    return nat, wall, ed_races, fl, names


# ==================================================================
# 3. 蓄積ファイルの読み書き
# ==================================================================
# 全国・当地とも「月×選手×コース」のカウンタ。古い月を捨てて365日窓を維持する。
CRS_COLS = ['n', 'r1', 'r2', 'r3', 'st_sum', 'st_n', 'mk1']
BOAT_COLS = ['n', 'top3']
P = lambda f: os.path.join(DATA, f)
ED_RACE_COLS = ['date', 'rno', 'rname', 'nichime', 'kimarite', 'wdir', 'wspd',
                'payout', 'ninki', 'win_course', 'win_teiban', 'entries']


def load_counter(fname, keys, cols):
    out = {}
    if not os.path.exists(P(fname)):
        return out
    with open(P(fname), encoding='utf-8') as f:
        for row in csv.DictReader(f):
            out[tuple(row[k] for k in keys)] = [float(row[c]) for c in cols]
    return out


def save_counter(fname, keys, cols, data):
    os.makedirs(DATA, exist_ok=True)
    with open(P(fname), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(list(keys) + list(cols))
        for k in sorted(data):
            w.writerow(list(k) + [('%g' % v) for v in data[k]])


def load_rows(fname):
    if not os.path.exists(P(fname)):
        return []
    with open(P(fname), encoding='utf-8') as f:
        return list(csv.DictReader(f))


def save_rows(fname, rows, cols, sortkey):
    os.makedirs(DATA, exist_ok=True)
    with open(P(fname), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in sorted(rows, key=sortkey):
            w.writerow({c: r.get(c, '') for c in cols})


def update_data(backfill_days=None):
    nat = load_counter('nat_course.csv', ('ym', 'regno', 'course'), CRS_COLS)
    edc = load_counter('ed_course.csv', ('ym', 'regno', 'course'), CRS_COLS)
    boat = load_counter('nat_boat.csv', ('ym', 'regno', 'boat'), BOAT_COLS)
    wall = load_counter('nat_wall.csv', ('ym', 'c2', 'c1'), ['n', 'c1won', 'c2won', 'mk'])
    flc = load_counter('nat_fl.csv', ('ymd', 'regno'), ['F', 'L'])
    races = load_rows('ed_races.csv')
    names = {r['regno']: r['name'] for r in load_rows('names.csv')}
    seen = {(r['date'], r['rno']) for r in races}

    if backfill_days:
        start = TODAY - datetime.timedelta(days=backfill_days)
    elif os.path.exists(P('cursor.txt')):
        start = datetime.date.fromisoformat(open(P('cursor.txt')).read().strip()) \
            + datetime.timedelta(days=1)
    else:
        start = TODAY - datetime.timedelta(days=WINDOW_DAYS)
    end = TODAY - datetime.timedelta(days=1)
    if start > end:
        print('  データ更新: 追加分なし')
        return nat, edc, boat, wall, flc, races, names

    d, got, miss = start, 0, 0
    while d <= end:
        raw = fetch_lzh('K', d)
        if raw:
            n_, w_, r_, f_, nm_ = parse_k_day(raw, d)
            ym = d.strftime('%Y-%m')
            names.update(nm_)
            for regno, course, teiban, chaku, st, mk1, is_ed in n_:
                fin = chaku in ('01', '02', '03')
                for tgt in ((nat,) + ((edc,) if is_ed else ())):
                    rec = tgt.setdefault((ym, regno, str(course)), [0.0] * len(CRS_COLS))
                    rec[0] += 1
                    if chaku == '01':
                        rec[1] += 1
                    elif chaku == '02':
                        rec[2] += 1
                    elif chaku == '03':
                        rec[3] += 1
                    if st is not None:
                        rec[4] += st
                        rec[5] += 1
                    rec[6] += mk1
                b = boat.setdefault((ym, regno, str(teiban)), [0.0, 0.0])
                b[0] += 1
                if fin:
                    b[1] += 1
            for c2, c1, c1won, c2won, mk in w_:
                rec = wall.setdefault((ym, c2, c1), [0.0] * 4)
                rec[0] += 1
                rec[1] += c1won
                rec[2] += c2won
                rec[3] += mk
            for regno, kind in f_:
                rec = flc.setdefault((d.isoformat(), regno), [0.0, 0.0])
                rec[0 if kind == 'F' else 1] += 1
            for r in r_:
                if (r['date'], str(r['rno'])) not in seen:
                    races.append(r)
                    seen.add((r['date'], str(r['rno'])))
            got += 1
        else:
            miss += 1
        d += datetime.timedelta(days=1)
    print('  データ更新: %s〜%s 取得%d日 / 欠測%d日' % (start, end, got, miss))

    cut_ym = (TODAY - datetime.timedelta(days=KEEP_DAYS)).strftime('%Y-%m')
    cut_d = (TODAY - datetime.timedelta(days=WINDOW_DAYS)).isoformat()
    nat = {k: v for k, v in nat.items() if k[0] >= cut_ym}
    edc = {k: v for k, v in edc.items() if k[0] >= cut_ym}
    boat = {k: v for k, v in boat.items() if k[0] >= cut_ym}
    wall = {k: v for k, v in wall.items() if k[0] >= cut_ym}
    flc = {k: v for k, v in flc.items() if k[0] >= cut_d}
    races = [r for r in races if r['date'] >= cut_d]

    save_counter('nat_course.csv', ('ym', 'regno', 'course'), CRS_COLS, nat)
    save_counter('ed_course.csv', ('ym', 'regno', 'course'), CRS_COLS, edc)
    save_counter('nat_boat.csv', ('ym', 'regno', 'boat'), BOAT_COLS, boat)
    save_counter('nat_wall.csv', ('ym', 'c2', 'c1'), ['n', 'c1won', 'c2won', 'mk'], wall)
    save_counter('nat_fl.csv', ('ymd', 'regno'), ['F', 'L'], flc)
    save_rows('ed_races.csv', races, ED_RACE_COLS, lambda x: (x['date'], int(x['rno'])))
    save_rows('names.csv', [dict(regno=k, name=v) for k, v in names.items()],
              ['regno', 'name'], lambda x: x['regno'])
    with open(P('cursor.txt'), 'w', encoding='utf-8') as f:
        f.write(end.isoformat())
    return nat, edc, boat, wall, flc, races, names


# ==================================================================
# 4. テーブル生成
# ==================================================================
def agg_course(counter):
    """(ym, regno, course) のカウンタを (regno, course) へ畳む"""
    out = defaultdict(lambda: [0.0] * len(CRS_COLS))
    for (ym, regno, c), v in counter.items():
        a = out[(regno, int(c))]
        for i in range(len(CRS_COLS)):
            a[i] += v[i]
    return out


def pct(sorted_vals, p):
    return sorted_vals[int(len(sorted_vals) * p)] if sorted_vals else 0


def rate(a, b, nd=3):
    return round(a / b, nd) if b else ''


def build_tables(nat, edc, boat, wall, flc, names):
    """当地4表＋全国2表を作る。作り方は既存4場（丸亀・福岡・津・平和島）と同じ手順。"""
    N = agg_course(nat)
    E = agg_course(edc)
    B = agg_boat(boat)
    i = {c: k for k, c in enumerate(CRS_COLS)}
    nm = lambda r: names.get(r, '')

    regnos = sorted({r for r, _ in N})
    tables = {}

    # ---- 全国_1コース地力表（顔ぶれ補正の土台） ----
    jiriki = {}
    rows = []
    for r in regnos:
        a = N.get((r, 1))
        if not a or a[i['n']] == 0:
            continue
        jiriki[r] = (a[i['n']], a[i['r1']])
        rows.append([r, int(a[i['n']]), int(a[i['r1']])])
    tables['全国_1コース地力表.csv'] = (['touban', 'n1c', 'win1c'], rows)
    tot_n = sum(v[0] for v in jiriki.values())
    tot_w = sum(v[1] for v in jiriki.values())
    P0 = tot_w / tot_n if tot_n else 0.552

    def nige_exp(r):
        """その選手が1コースなら逃げる期待値（経験ベイズ縮小 k=20）"""
        n, w = jiriki.get(r, (0, 0))
        return (w + SHRINK_K * P0) / (n + SHRINK_K)

    # ---- 全国_F持ち_当期（⑩） ----
    ps = period_start().isoformat()
    fcnt = defaultdict(lambda: [0, 0])
    for (ymd, r), v in flc.items():
        if ymd >= ps:
            fcnt[r][0] += int(v[0])
            fcnt[r][1] += int(v[1])
    rows = []
    for r in sorted(fcnt):
        f_, l_ = fcnt[r]
        if f_ == 0 and l_ == 0:
            continue
        rows.append([r, nm(r), f_, l_, 'F2+' if f_ >= 2 else ('F1' if f_ == 1 else '')])
    tables['全国_F持ち_当期.csv'] = (['regno', '選手名', 'F本数', 'L本数', '区分'], rows)
    F_MOCHI = {r[0]: r[4] for r in rows}

    # ---- ①江戸川_ST表 ----
    def st_of(src, r, courses):
        n = sum(src[(r, c)][i['st_n']] for c in courses if (r, c) in src)
        s = sum(src[(r, c)][i['st_sum']] for c in courses if (r, c) in src)
        return (n, round(s / n, 3) if n else None)

    rows = []
    for r in regnos:
        gn, gs = st_of(N, r, (1, 2, 3))
        ln, ls = st_of(E, r, (1, 2, 3))
        gdn, gds = st_of(N, r, (4, 5, 6))
        ldn, lds = st_of(E, r, (4, 5, 6))
        use_l = ln >= ST_LOCAL_MIN and ls is not None
        S, ssrc = (ls, '当地') if use_l else (gs, '全国')
        use_ld = ldn >= ST_LOCAL_MIN and lds is not None
        D, dsrc = (lds, '当地') if use_ld else (gds, '全国')
        if S is None and D is None:
            continue
        rows.append([r, nm(r), int(gn), gs if gs is not None else '', int(ln),
                     ls if ls is not None else '', S if S is not None else '', ssrc,
                     '●' if (S is not None and S > ST_LATE) else '',
                     '●' if (S is not None and S <= ST_GOOD) else '',
                     int(gdn), gds if gds is not None else '', int(ldn),
                     lds if lds is not None else '', D if D is not None else '', dsrc,
                     '●' if (D is not None and D > ST_LATE) else '',
                     '●' if (D is not None and D <= ST_GOOD) else ''])
    tables['江戸川_ST表.csv'] = (
        ['regno', '選手名', '全国スローn', '全国スローST', '当地スローn', '当地スローST',
         '採用スローST', 'スロー源', 'スロー遅れ', 'スロー巧者', '全国ダッシュn', '全国ダッシュST',
         '当地ダッシュn', '当地ダッシュST', '採用ダッシュST', 'ダッシュ源', 'ダッシュ遅れ',
         'ダッシュ巧者'], rows)
    T_ST = {r[0]: dict(採用スローST=r[6], スロー遅れ=r[8]) for r in rows}

    # ---- ④江戸川_絞りまくり表（当地3-4コース） ----
    rows = []
    for r in regnos:
        n34 = sum(E[(r, c)][i['n']] for c in (3, 4) if (r, c) in E)
        mk = sum(E[(r, c)][i['mk1']] for c in (3, 4) if (r, c) in E)
        if n34 < MAKURI_MIN:
            continue
        rt = mk / n34
        rows.append([r, nm(r), int(n34), int(mk), round(rt, 3),
                     '●' if rt >= MAKURI_RATE else '',
                     '暫定' if n34 < MAKURI_PROV else ''])
    rows.sort(key=lambda x: -x[4])
    tables['江戸川_絞りまくり表.csv'] = (
        ['regno', '選手名', 'n34', 'まくり系1着', '率', '絞りまくり', '暫定'], rows)
    T_MAK = {r[0]: dict(絞りまくり=r[5], 暫定=r[6]) for r in rows}

    # ---- ⑤⑥⑦＋11-5 江戸川_残し表 ----
    zan = {}
    for r in regnos:
        a1 = N.get((r, 1), [0.0] * len(CRS_COLS))
        n1c = a1[i['n']]
        lose = n1c - a1[i['r1']]
        p2 = a1[i['r2']]
        zan[r] = (n1c, lose, p2)
    vals = sorted(p2 / lose for (n1c, lose, p2) in zan.values()
                  if n1c >= ZAN1C_MIN and lose >= ZAN1C_LOSE_MIN)
    HI, LO = pct(vals, 0.90), pct(vals, 0.10)   # デシル（平和島メモと同じ）

    rows = []
    for r in regnos:
        gon = sum(N[(r, c)][i['n']] for c in (4, 5, 6) if (r, c) in N)
        go3 = sum(N[(r, c)][i['r1']] + N[(r, c)][i['r2']] + N[(r, c)][i['r3']]
                  for c in (4, 5, 6) if (r, c) in N)
        lon = sum(E[(r, c)][i['n']] for c in (4, 5, 6) if (r, c) in E)
        lo3 = sum(E[(r, c)][i['r1']] + E[(r, c)][i['r2']] + E[(r, c)][i['r3']]
                  for c in (4, 5, 6) if (r, c) in E)
        g_rate = rate(go3, gon) if gon >= OUTER_MIN else ''
        l_rate = rate(lo3, lon) if lon >= OUTER_MIN else ''
        adopt, src = (l_rate, '当地') if l_rate != '' else (g_rate, '全国')
        n1c, lose, p2 = zan[r]
        if n1c >= ZAN1C_MIN and lose >= ZAN1C_LOSE_MIN:
            rr = p2 / lose
            typ = '残す型' if rr >= HI else ('飛ぶ型' if rr <= LO else '')
            rr_s, valid = round(rr, 3), '○'
        else:
            rr_s, typ, valid = '', '', ''
        a6 = N.get((r, 6), [0.0] * len(CRS_COLS))
        n6 = a6[i['n']]
        r62 = rate(a6[i['r2']], n6) if n6 >= ZAN6_MIN else ''
        r63 = rate(a6[i['r3']], n6) if n6 >= ZAN6_MIN else ''
        b5 = boat_stat(B, r, 5)
        b6 = boat_stat(B, r, 6)
        if adopt == '' and rr_s == '' and r62 == '' and b5[1] == '' and b6[1] == '':
            continue
        rows.append([r, nm(r), int(gon), g_rate, int(lon), l_rate, adopt, src,
                     int(n1c), int(lose), rr_s, valid, typ,
                     int(n6), r62, r63, '○' if n6 >= ZAN6_MIN else '',
                     b5[0], b5[1], b6[0], b6[1],
                     '●' if (b6[1] != '' and b6[1] < BOAT6_LOW) else '',
                     '●' if (b5[1] != '' and b5[1] < BOAT6_LOW) else ''])
    tables['江戸川_残し表.csv'] = (
        ['regno', '選手名', '全国外n', '全国外3着率', '当地外n', '当地外3着率', '採用外3着率',
         '外3着源', 'n1c', '負け', '残し率', '残し有効', '型', 'n6', '6コ2着率', '6コ3着率',
         '6残し有効', '艇番5乗艇', '艇番5_3連対率', '艇番6乗艇', '艇番6_3連対率',
         '6ヒモ外し候補', '艇番5低率'], rows)
    T_ZAN = {r[0]: dict(型=r[12], **{'艇番6_3連対率': r[20], '6ヒモ外し候補': r[21]}) for r in rows}

    # ---- ⑫江戸川_壁表（全国・2コース進入40走以上） ----
    w_n, w_c1won, w_exp, w_c2won, w_mk = (defaultdict(float) for _ in range(5))
    for (ym, c2, c1), v in wall.items():
        n, c1won, c2won, mk = v
        w_n[c2] += n
        w_c1won[c2] += c1won
        w_exp[c2] += nige_exp(c1) * n
        w_c2won[c2] += c2won
        w_mk[c2] += mk
    powers = sorted((w_c1won[t] / w_n[t] - w_exp[t] / w_n[t]) * 100
                    for t in w_n if w_n[t] >= WALL_MIN)
    WHI, WLO = pct(powers, 0.90), pct(powers, 0.10)
    rows = []
    for t in sorted(w_n):
        n = w_n[t]
        if n < WALL_MIN:
            continue
        nige = w_c1won[t] / n
        exp = w_exp[t] / n
        power = round((nige - exp) * 100, 1)
        lose = n - w_c1won[t]
        sw = w_c2won[t] / lose if lose else 0
        mkd = w_mk[t] / lose if lose else 0
        kabe = '壁強●' if power >= WHI else ('壁弱●' if power <= WLO else '')
        wt = ''
        if kabe == '壁弱●' and lose:
            wt = '食う型' if sw >= 0.40 else ('素通し型' if mkd >= 0.35 else '混合')
        rows.append([t, nm(t), int(n), round(nige, 4), round(exp, 4), power,
                     int(lose), round(sw, 3), round(mkd, 3), kabe, wt])
    rows.sort(key=lambda x: x[5])
    tables['江戸川_壁表.csv'] = (
        ['regno', '選手名', 'n2', 'nige', 'exp', '壁力', '負けn', '自分勝ち率',
         'まくり決着率', '壁', '弱タイプ'], rows)
    T_WALL = {r[0]: dict(壁=r[9], 弱タイプ=r[10]) for r in rows}

    lookups = dict(st=T_ST, mak=T_MAK, zan=T_ZAN, wall=T_WALL, f=F_MOCHI,
                   jiriki=jiriki, P0=P0)
    return tables, lookups


def agg_boat(boat):
    """(ym, regno, boat) を (regno, boat) へ畳む"""
    out = defaultdict(lambda: [0.0, 0.0])
    for (ym, r, b), v in boat.items():
        a = out[(r, int(b))]
        a[0] += v[0]
        a[1] += v[1]
    return out


def boat_stat(B, regno, bno):
    n, t3 = B.get((regno, bno), (0.0, 0.0))
    return (int(n), round(t3 / n, 3) if n >= BOAT_MIN else '')


def write_tables(tables):
    os.makedirs(DATA, exist_ok=True)
    for fname, (cols, rows) in tables.items():
        with open(P(fname), 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)


# ==================================================================
# 5. 当地ベースライン（表示・地形図用。採点には使わない）
# ==================================================================
def base_stats(races):
    rs = [r for r in races if r.get('win_course')]
    n = len(rs)
    if not n:
        return {}, []
    pays = sorted(int(r['payout']) for r in rs if r.get('payout'))
    kim = defaultdict(int)
    for r in rs:
        kim[r['kimarite']] += 1
    byr = defaultdict(list)
    for r in rs:
        byr[int(r['rno'])].append(r)
    rno_table = []
    for rno in sorted(byr):
        g = byr[rno]
        gp = [int(x['payout']) for x in g if x.get('payout')]
        rno_table.append(dict(
            rno=rno, n=len(g),
            in1=round(sum(1 for x in g if x['win_course'] == '1') / len(g) * 100, 1),
            man=round(sum(1 for p in gp if p >= 10000) / len(gp) * 100, 1) if gp else 0))
    day1 = [r for r in rs if str(r.get('nichime')) == '1']
    return dict(
        days=len({r['date'] for r in rs}), races=n,
        in1=round(sum(1 for r in rs if r['win_course'] == '1') / n * 100, 1),
        man=round(sum(1 for p in pays if p >= 10000) / len(pays) * 100, 1) if pays else 0,
        median=pays[len(pays) // 2] if pays else 0,
        makuri_kei=round((kim['まくり'] + kim['まくり差し']) / n * 100, 1),
        kimarite={k: v for k, v in sorted(kim.items(), key=lambda x: -x[1]) if v},
        day1_in1=round(sum(1 for r in day1 if r['win_course'] == '1') / len(day1) * 100, 1)
        if day1 else None,
        day1_n=len(day1)), rno_table


# ==================================================================
# 6. Bファイル（当日出走表）
# ==================================================================
B_HEAD = re.compile(r'^\s*(\d{1,2})R\s+(\S+)')
B_DEADLINE = re.compile(r'締切予定\s*(\d{1,2}):(\d{1,2})')
B_BOAT = re.compile(r'^([1-6]) (\d{4})(.{4})(\d{2})(..)(\d{2})([AB][12])(.*)$')


def parse_b(raw):
    m = re.search(r'%sBBGN(.*?)%sBEND' % (JCD, JCD), raw, re.S)
    if not m:
        return None
    lines = m.group(1).split('\n')
    title, day_n = '', None
    for ln in lines[:12]:
        nl = unicodedata.normalize('NFKC', ln)
        md = DAY_RE.search(nl)
        if md and day_n is None:
            day_n = int(md.group(1))
        s = nl.strip()
        if s and not title and not re.match(r'^\d', s) \
                and 'BBGN' not in s and '番組表' not in s and 'ボートレース' not in s:
            title = s
    races, cur = [], None
    for ln in lines:
        nl = unicodedata.normalize('NFKC', ln)
        mh = B_HEAD.match(nl)
        if mh:
            if cur:
                races.append(cur)
            md = B_DEADLINE.search(nl)
            cur = dict(rno=int(mh.group(1)), rname=mh.group(2),
                       deadline=('%s:%s' % (md.group(1), md.group(2).zfill(2))) if md else '',
                       boats=[])
            continue
        mb = B_BOAT.match(ln)
        if mb and cur is not None:
            cur['boats'].append(dict(teiban=int(ln[0]), regno=ln[2:6].strip(),
                                     name=ln[6:10].replace('　', '').strip(),
                                     grade=ln[16:18]))
    if cur:
        races.append(cur)
    races = [r for r in races if len(r['boats']) >= 4]
    if not races:
        return None
    return dict(title=title, day_n=day_n, races=races)


# ==================================================================
# 7. 採点（仕様書§4の確定シグナルのみ。風・潮・1R・9Rは入れない）
# ==================================================================
def score_race(r, nichime, L):
    score, badges, notes = 0, {b['teiban']: [] for b in r['boats']}, []
    forms = []
    rno = r['rno']
    boats = {b['teiban']: b for b in r['boats']}

    # ⑨ 初日（江戸川固有・最重要。丸亀⑨の2倍の深さなので +2）
    if nichime == 1:
        score += 2
        forms.append('day1')      # 文言は policy_for が組み立てる（重複させない）

    # ⑭ 前半戦ゾーン(2-6R) +1 ／ ⑭' 6R はさらに +1（計+2）
    if 2 <= rno <= 6:
        score += 1
        forms.append('zone')
        if rno == 6:
            score += 1
            forms.append('r6')

    for b in r['boats']:
        tb, reg = b['teiban'], b['regno']
        sub = []
        # ① 1号艇のスローST > .18
        st = L['st'].get(reg)
        if st:
            v = st.get('採用スローST')
            if v != '' and v is not None:
                sub.append('平均ST %.2f' % float(v))
                if tb == 1 and float(v) > ST_LATE:
                    badges[tb].append('ST遅れ')
                    score += 1
                    notes.append('1号艇のスローST %.2f＝出足で遅れやすい。' % float(v))
        # ⑩ 1号艇のF持ち（当期）
        kb = L['f'].get(reg, '')
        if kb == 'F2+':
            badges[tb].append('F2持ち')
            if tb == 1:
                score += 2
        elif kb == 'F1':
            badges[tb].append('F1')
            if tb == 1:
                score += 1
        # ④ 3・4号艇が絞りまくり型
        mk = L['mak'].get(reg)
        if tb in (3, 4) and mk and mk.get('絞りまくり') == '●':
            badges[tb].append('まくり' + ('(暫)' if mk.get('暫定') else ''))
            score += 1
        # ⑫ 2号艇が壁弱（素通し型）
        wl = L['wall'].get(reg)
        if tb == 2 and wl:
            if wl.get('壁') == '壁弱●' and wl.get('弱タイプ') == '素通し型':
                badges[tb].append('壁弱')
                score += 1
                notes.append('2号艇が素通し型＝外の攻めがそのまま通る。')
            elif wl.get('壁') == '壁強●':
                badges[tb].append('壁強')
        # ⑥ 1号艇の残す/飛ぶ ＆ 11-5 6ヒモ外し
        zn = L['zan'].get(reg)
        if zn:
            if tb == 1 and zn.get('型') == '飛ぶ型':
                badges[tb].append('飛ぶ型')
                forms.append('tobu')
            if tb == 1 and zn.get('型') == '残す型':
                badges[tb].append('残す型')
                forms.append('nokosu')
            if tb == 6:
                tr = zn.get('艇番6_3連対率')
                if tr != '' and tr is not None:
                    b['teiban_rate'] = round(float(tr) * 100, 1)
                if zn.get('6ヒモ外し候補') == '●':
                    badges[tb].append('外し')
        if tb == 1:
            n1, w1 = L['jiriki'].get(reg, (0, 0))
            b['jiriki'] = round((w1 + SHRINK_K * L['P0']) / (n1 + SHRINK_K) * 100, 1) if n1 else None
        b['st_avg'] = ('%.2f' % float(st['採用スローST'])) if (
            st and st.get('採用スローST') not in ('', None)) else None
        b['badges'] = badges[tb]
        b.setdefault('teiban_rate', None)
    return score, forms, notes


def label_for(score):
    if score >= 4:
        return '穴の巣'
    if score >= 2:
        return 'イン受難ゾーン'
    if score == 1:
        return '中間'
    return 'イン堅め'


def policy_for(score, forms, notes):
    """買い目フォーム（仕様書§5）。処理順は 日目・番号 → 選手加点 → 方針テキスト。"""
    head = []
    if 'day1' in forms and 'r6' in forms:
        head.append('初日の6R＝江戸川で最も1号艇が飛ぶ組合せ（初日の前半戦は実測32.5%）。頭≠1を本線に。')
    elif 'day1' in forms and 'zone' in forms:
        head.append('初日の前半戦＝実測32.5%。江戸川で最も1号艇が飛ぶ組合せ。頭≠1を本線に。')
    elif 'day1' in forms:
        head.append('初日＝イン最弱日（実測40.5%）。頭≠1を主軸、1は2着以下に置く。')
    elif 'r6' in forms:
        head.append('6R＝江戸川で最もインが飛ぶ番号（実測34.9%）。頭≠1を主軸に。')
    elif 'zone' in forms:
        head.append('前半戦はB級中心でイン受難ゾーン（実測39.3%）。イン信頼度を下げる。')
    if 'day1' in forms and 'tobu' in forms:
        head.append('1号艇が飛ぶ型＝1総外し検討。')
    elif 'day1' in forms and 'nokosu' in forms:
        head.append('1号艇が残す型＝X-1-Y主体（配当は伸びない点に注意）。')
    if not head:
        head.append('中立。基礎率どおり。')
    # 6は江戸川の土台ヒモ（3連率27.1%＝全国最高）。ただし日目では動かない
    head.append('6コースは3連率27.1%（全国最高）＝常にヒモに厚く。3着は絞り、妙味は2着側。')
    return ' '.join(head + notes)


# ==================================================================
# 8. メイン
# ==================================================================
def main():
    backfill = None
    if '--backfill' in sys.argv:
        k = sys.argv.index('--backfill')
        backfill = int(sys.argv[k + 1]) if len(sys.argv) > k + 1 else WINDOW_DAYS

    print('江戸川(03) 日次パイプライン', TODAY.isoformat())
    nat, edc, boat, wall, flc, races, names = update_data(backfill)

    tables, L = build_tables(nat, edc, boat, wall, flc, names)
    write_tables(tables)
    print('  テーブル: ' + ' / '.join('%s %d行' % (k.replace('.csv', ''), len(v[1]))
                                    for k, v in tables.items()))

    base, rno_table = base_stats(races)
    if base:
        print('  当地ベース: %d開催日 %dレース イン%.1f%% 万舟%.1f%% 初日イン%.1f%%'
              % (base['days'], base['races'], base['in1'], base['man'],
                 base['day1_in1'] or 0))

    data = dict(date=TODAY.isoformat(),
                updated=(datetime.datetime.now(datetime.timezone.utc)
                         + datetime.timedelta(hours=9)).strftime('%Y-%m-%d %H:%M JST'),
                kaisai=False, base=base, rno_table=rno_table)

    raw_b = fetch_lzh('B', TODAY)
    parsed = parse_b(raw_b) if raw_b else None
    if parsed:
        nichime = parsed['day_n']
        data.update(kaisai=True, title=parsed['title'], nichime=nichime)
        out = []
        for r in parsed['races']:
            sc, forms, notes = score_race(r, nichime, L)
            out.append(dict(rno=r['rno'], rname=r['rname'], deadline=r['deadline'],
                            label=label_for(sc), score=max(sc, 0),
                            base_in1=next((x['in1'] for x in rno_table
                                           if x['rno'] == r['rno']), base.get('in1')),
                            policy=policy_for(sc, forms, notes), boats=r['boats']))
        data['races'] = out
        print('  開催あり: %s 第%s日 / %dレース（スコア2以上 %d）'
              % (parsed['title'], nichime, len(out),
                 sum(1 for r in out if r['score'] >= 2)))
    else:
        print('  本日は江戸川の開催なし')

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    print('  ->', OUT_JSON)


if __name__ == '__main__':
    main()
