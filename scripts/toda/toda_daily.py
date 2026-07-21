# -*- coding: utf-8 -*-
"""戸田(02) 穴党ツール — 毎朝の自動実行スクリプト

正本：docs/toda/spec_toda.md（戸田_穴党ツール_仕様書）
毎朝 GitHub Actions から実行され、次の順に処理します。

  1) データ更新   … 前回以降のKファイル（競走成績）だけを取得し、
                    「月×選手」のカウンタCSVに足し込む（鳴門方式の差分蓄積）
  2) 選手表の生成 … カウンタから2表を毎朝作り直す
                      data/toda/toda_makuriya.csv  … 4コースまくり屋表（仕様書 5-1）
                      data/toda/toda_nokoshi6.csv  … 6コース残し表    （仕様書 5-2）
  3) 当日出走表   … 今日のBファイルを取得し、2表をregnoでJOINして
                    toda/data.json を出力（toda/index.html が読んで表示）

★採点に使ってよいのは仕様書§2の採用シグナルだけ。以下は検証して却下済みなので
  実装してはいけない（仕様書§3）:
    ・北西風のイン崩し   … 風速との二重交絡で z=−1.28（有意でない）
    ・25-50人気帯の機械買い … ROI 80.3%が天井。控除の壁を越えない
    ・強風→まくり        … 6m以上で逆戻りし単調でない
    ・STばらつきによる荒れ … 戸田のST SDは江戸川の約半分。移植不可

TODO(半年ごと): 2表は毎朝再生成しているので自動的に最新化される（仕様書 5-4）。
TODO(2〜3年後): 二枚重ね（まくり屋カド×6残す）はn=11で不足。n>=30で再検証（仕様書 5-3）。
TODO(次フェーズ): data/odds/02/ が貯まったらEV検証。回収率100%超えの唯一の経路（仕様書§8）。

テスト実行: TODA_DATE=2026-06-27 python scripts/toda/toda_daily.py
初期構築  : python scripts/toda/toda_daily.py --backfill 365
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
# 設定（閾値を変えたいときはここだけ触る。ただし仕様書の根拠を確認すること）
# ==================================================================
JCD = '02'                 # 戸田
DATA = os.environ.get('TODA_DATA', 'data/toda')
OUT_JSON = os.environ.get('TODA_OUT', 'toda/data.json')
KCACHE = os.environ.get('TODA_KCACHE', os.path.join(tempfile.gettempdir(), 'toda_k'))

MAKURIYA_TH = 8.0          # まくり力 +8以上 → まくり屋カド（仕様書 5-1）
KADOKESHI_TH = -4.0        # まくり力 −4以下 → まくらない型＝カド消し
NOKOSHI_TH = 6.0           # 残し残差 +6以上 → 6残す（仕様書 5-2）
KIERU_TH = -6.0            # 残し残差 −6以下 → 6切り
MIN_C4 = 15                # 全国4コース15走未満は表から除外
MIN_C6 = 15                # 全国6コース15走未満は表から除外
MIN_JIRIKI = 30            # 地力（全コース通算3連対率）は30走以上
SHRINK_K = 15              # ベイズ収縮の強さ K=15
BIN = 0.05                 # 地力ビンの刻み（0.05刻みで四捨五入＝境界は2.5,7.5,12.5…）
WINDOW_DAYS = 365          # 集計窓
KEEP_DAYS = 396            # カウンタを保持する日数（窓より少し長く持つ）

MAKURI_KEI = ('まくり', 'まくり差し')
UA = {'User-Agent': 'Mozilla/5.0 (toda-tool)'}


def jst_today():
    if os.environ.get('TODA_DATE'):
        return datetime.date.fromisoformat(os.environ['TODA_DATE'])
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).date()


TODAY = jst_today()


# ==================================================================
# 1. ファイル取得（K=競走成績 / B=番組表）
# ==================================================================
def fetch_lzh(kind, d):
    """LZHを取ってテキストで返す。取れなければ None。取得済みはキャッシュから。"""
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
            os.remove(path)      # 壊れたキャッシュは捨てて次回取り直す
        except OSError:
            pass
        return None


# ==================================================================
# 2. Kファイルのパース
# ==================================================================
# レースヘッダは「H1800m」の距離表記を同一行に要求する。
# `^\s*\d+R\s` だけだと払戻金一覧の「1R…」に誤マッチする（仕様書 7-2 の落とし穴）
RACE_HDR = re.compile(r'^\s{2,}(\d{1,2})R\s+(.*?)\s+H(\d{3,4})m')
WIND_RE = re.compile(r'風[\s　]*([東西南北]{1,3})[\s　]*(\d+)m')
WIND_RE2 = re.compile(r'風[\s　]*(\d+)m')
# NFKC正規化後は「３連単」が「3連単」になる（仕様書 7-4 のバグ注意）
SANTAN = re.compile(r'3連単\s+([1-6]-[1-6]-[1-6])\s+(\d+)\s+人気\s+(\d+)')
DAY_RE = re.compile(r'第\s*(\d+)\s*日')


def is_finisher(line):
    return (len(line) > 21 and line[:2] == '  '
            and line[6].isdigit() and line[8:12].isdigit())


def parse_k_day(raw):
    """1日分のKファイルを解析して (全国エントリ一覧, 戸田レース一覧) を返す。

    全国エントリ: (登番, 進入コース, 着, ST, まくり系決着か, 戸田か)
    """
    entries, toda_races, toda_ents, names = [], [], [], {}
    for vm in re.finditer(r'(\d{2})KBGN(.*?)\1KEND', raw, re.S):
        vcd, blk = vm.group(1), vm.group(2)
        is_toda = (vcd == JCD)
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
                if wm:
                    wdir, wspd = wm.group(1), int(wm.group(2))
                else:
                    wm2 = WIND_RE2.search(line)
                    wdir, wspd = '無', (int(wm2.group(1)) if wm2 else '')
                cur = dict(rno=int(hm.group(1)),
                           rname=hm.group(2).replace('　', '').strip(),
                           wdir=wdir, wspd=wspd, kimarite='', boats=[],
                           santan='', payout='', ninki='', nichime=nichime)
                continue
            if cur is None:
                continue
            # 決まり手は列見出し行の末尾にある（仕様書 7-1）
            if 'ﾚｰｽﾀｲﾑ' in line:
                cur['kimarite'] = line.split('ﾚｰｽﾀｲﾑ')[-1].replace('　', '').strip()
                continue
            if is_finisher(line):
                tail = line[21:].split()
                course = tail[3] if (len(tail) >= 4 and len(tail[3]) == 1
                                     and tail[3] in '123456') else ''
                st = None
                if len(tail) >= 5:
                    try:
                        v = float(tail[4])
                        if 0 <= v <= 1.0:
                            st = v
                    except ValueError:
                        pass
                nm = line[13:21].replace('　', '').strip()
                if nm:
                    names[line[8:12]] = nm
                cur['boats'].append(dict(chaku=line[2:4].strip(), teiban=line[6],
                                         touban=line[8:12], course=course, st=st))
                continue
            nl = unicodedata.normalize('NFKC', line)
            sm = SANTAN.search(nl)
            if sm:
                cur['santan'], cur['payout'], cur['ninki'] = \
                    sm.group(1), int(sm.group(2)), int(sm.group(3))
        if cur:
            races.append(cur)

        for r in races:
            mk = r['kimarite'] in MAKURI_KEI
            for b in r['boats']:
                if not b['course']:
                    continue
                entries.append((b['touban'], int(b['course']), b['chaku'], b['st'],
                                mk and b['chaku'] == '01', is_toda))
            if is_toda:
                win = next((b for b in r['boats'] if b['chaku'] == '01'), None)
                # 前づけ＝進入1〜3コースに枠番4〜6の艇が居る（仕様書 2-④）
                zenzuke = any(b['course'] and int(b['course']) <= 3 and int(b['teiban']) >= 4
                              for b in r['boats'])
                toda_races.append(dict(
                    rno=r['rno'], rname=r['rname'], nichime=r['nichime'],
                    kimarite=r['kimarite'], wdir=r['wdir'], wspd=r['wspd'],
                    santan=r['santan'], payout=r['payout'], ninki=r['ninki'],
                    win_course=(win['course'] if win else ''),
                    win_teiban=(win['teiban'] if win else ''),
                    zenzuke=1 if zenzuke else 0))
                for b in r['boats']:
                    toda_ents.append(dict(rno=r['rno'], teiban=b['teiban'],
                                          course=b['course'], touban=b['touban'],
                                          chaku=b['chaku'], st=(b['st'] if b['st'] is not None else '')))
    return entries, toda_races, toda_ents, names


# ==================================================================
# 3. カウンタ（月×選手）の読み書き
# ==================================================================
# 1行 = ある選手のある月の集計。古い月を捨てるだけで365日窓を維持できる。
CNT_COLS = ['tot_n', 'tot_top3', 'c1n', 'c1w',
            'c4n', 'c4w', 'c4mk', 'c4st_sum', 'c4st_n',
            'c6n', 'c6w2', 'c6w3', 'c6st_sum', 'c6st_n',
            't4n', 't4mk', 't6n', 't6_23']
CNT_PATH = lambda: os.path.join(DATA, 'nat_counts.csv')
RACES_PATH = lambda: os.path.join(DATA, 'toda_races.csv')
CURSOR_PATH = lambda: os.path.join(DATA, 'cursor.txt')
RACE_COLS = ['date', 'rno', 'rname', 'nichime', 'kimarite', 'wdir', 'wspd',
             'santan', 'payout', 'ninki', 'win_course', 'win_teiban', 'zenzuke']
ENT_COLS = ['date', 'rno', 'teiban', 'course', 'touban', 'chaku', 'st']
ENTS_PATH = lambda: os.path.join(DATA, 'toda_entries.csv')


def load_counts():
    out = {}
    p = CNT_PATH()
    if not os.path.exists(p):
        return out
    with open(p, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            key = (row['ym'], row['touban'])
            out[key] = [float(row[c]) for c in CNT_COLS]
    return out


def save_counts(counts):
    os.makedirs(DATA, exist_ok=True)
    with open(CNT_PATH(), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['ym', 'touban'] + CNT_COLS)
        for (ym, tb) in sorted(counts):
            v = counts[(ym, tb)]
            w.writerow([ym, tb] + [('%.3f' % x).rstrip('0').rstrip('.') if isinstance(x, float)
                                   else x for x in v])


def add_entries(counts, ym, entries):
    for touban, course, chaku, st, mk_win, is_toda in entries:
        rec = counts.setdefault((ym, touban), [0.0] * len(CNT_COLS))
        i = {c: n for n, c in enumerate(CNT_COLS)}
        fin = chaku in ('01', '02', '03')
        rec[i['tot_n']] += 1
        if fin:
            rec[i['tot_top3']] += 1
        if course == 1:
            rec[i['c1n']] += 1
            if chaku == '01':
                rec[i['c1w']] += 1
        if course == 4:
            rec[i['c4n']] += 1
            if chaku == '01':
                rec[i['c4w']] += 1
            if mk_win:
                rec[i['c4mk']] += 1
            if st is not None:
                rec[i['c4st_sum']] += st
                rec[i['c4st_n']] += 1
            if is_toda:
                rec[i['t4n']] += 1
                if mk_win:
                    rec[i['t4mk']] += 1
        if course == 6:
            rec[i['c6n']] += 1
            if chaku == '02':
                rec[i['c6w2']] += 1
            if chaku == '03':
                rec[i['c6w3']] += 1
            if st is not None:
                rec[i['c6st_sum']] += st
                rec[i['c6st_n']] += 1
            if is_toda:
                rec[i['t6n']] += 1
                if chaku in ('02', '03'):
                    rec[i['t6_23']] += 1


def load_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def save_rows(path, rows, cols):
    os.makedirs(DATA, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x['date'], int(x['rno']),
                                             int(x.get('teiban') or 0))):
            w.writerow({k: r.get(k, '') for k in cols})


# ==================================================================
# 4. 選手表2枚の生成（仕様書 5-1 / 5-2）
# ==================================================================
def jiriki_bin(j):
    """地力を0.05刻みで四捨五入したビンに落とす（境界が2.5, 7.5, 12.5…になる）。"""
    return round(round(j / BIN) * BIN, 4)


def build_tables(counts, names):
    """カウンタから (まくり屋表, 6コース残し表) を作る。

    手順（両表共通）:
      1) 地力 = 全コース通算3連対率（30走以上）
      2) 地力ビンごとに、そのコースの実績を合算して「期待カーブ」を作る
      3) 各選手の実績を期待値へベイズ収縮（K=15）
      4) 指標 = 収縮値 − 期待値（ポイント表記）
    """
    agg = defaultdict(lambda: [0.0] * len(CNT_COLS))
    for (ym, tb), v in counts.items():
        a = agg[tb]
        for k in range(len(CNT_COLS)):
            a[k] += v[k]
    i = {c: n for n, c in enumerate(CNT_COLS)}

    jiriki = {}
    for tb, a in agg.items():
        if a[i['tot_n']] >= MIN_JIRIKI:
            jiriki[tb] = a[i['tot_top3']] / a[i['tot_n']]

    def curve(n_col, hit_col, min_n):
        """地力ビン別の期待率（該当者の実績を合算した率）"""
        num, den = defaultdict(float), defaultdict(float)
        for tb, a in agg.items():
            if tb not in jiriki or a[i[n_col]] < min_n:
                continue
            b = jiriki_bin(jiriki[tb])
            num[b] += a[i[hit_col]]
            den[b] += a[i[n_col]]
        return {b: (num[b] / den[b]) for b in den if den[b] > 0}

    def shrink(hit, n, exp):
        return (hit + SHRINK_K * exp) / (n + SHRINK_K)

    # --- 4コースまくり屋表 ---
    c4 = curve('c4n', 'c4mk', MIN_C4)
    mak = []
    for tb, a in agg.items():
        if tb not in jiriki or a[i['c4n']] < MIN_C4:
            continue
        exp = c4.get(jiriki_bin(jiriki[tb]))
        if exp is None:
            continue
        n, hit = a[i['c4n']], a[i['c4mk']]
        power = (shrink(hit, n, exp) - exp) * 100
        st = (a[i['c4st_sum']] / a[i['c4st_n']]) if a[i['c4st_n']] else None
        mak.append(dict(
            touban=tb, name=names.get(tb, ''), jiriki=round(jiriki[tb] * 100, 1),
            n4=int(n), rate4=round(hit / n * 100, 1), exp4=round(exp * 100, 1),
            power=round(power, 1), win4=round(a[i['c4w']] / n * 100, 1),
            st4=(round(st, 3) if st is not None else ''),
            t4n=int(a[i['t4n']]),
            t4mk=(round(a[i['t4mk']] / a[i['t4n']] * 100, 1) if a[i['t4n']] else '')))
    mak.sort(key=lambda r: -r['power'])

    # --- 6コース残し表 ---
    def curve6(hit_cols):
        num, den = defaultdict(float), defaultdict(float)
        for tb, a in agg.items():
            if tb not in jiriki or a[i['c6n']] < MIN_C6:
                continue
            b = jiriki_bin(jiriki[tb])
            num[b] += sum(a[i[c]] for c in hit_cols)
            den[b] += a[i['c6n']]
        return {b: (num[b] / den[b]) for b in den if den[b] > 0}

    c6 = curve6(['c6w2', 'c6w3'])
    c6_2 = curve6(['c6w2'])          # 補正2着率を出すための「2着だけ」の期待カーブ
    nok = []
    for tb, a in agg.items():
        if tb not in jiriki or a[i['c6n']] < MIN_C6:
            continue
        exp = c6.get(jiriki_bin(jiriki[tb]))
        if exp is None:
            continue
        n = a[i['c6n']]
        hit = a[i['c6w2']] + a[i['c6w3']]
        sh = shrink(hit, n, exp)
        st = (a[i['c6st_sum']] / a[i['c6st_n']]) if a[i['c6st_n']] else None
        nok.append(dict(
            touban=tb, name=names.get(tb, ''), jiriki=round(jiriki[tb] * 100, 1),
            n6=int(n), rate6_2=round(a[i['c6w2']] / n * 100, 1),
            rate6_3=round(a[i['c6w3']] / n * 100, 1), rate6_23=round(hit / n * 100, 1),
            exp6=round(exp * 100, 1), resid=round((sh - exp) * 100, 1),
            adj2=round(shrink(a[i['c6w2']], n, c6_2.get(jiriki_bin(jiriki[tb]), 0.063)) * 100, 1),
            st6=(round(st, 3) if st is not None else ''),
            t6n=int(a[i['t6n']]),
            t6_23=(round(a[i['t6_23']] / a[i['t6n']] * 100, 1) if a[i['t6n']] else '')))
    nok.sort(key=lambda r: -r['resid'])
    return mak, nok


MAK_COLS = [('touban', '登番'), ('name', '選手名'), ('jiriki', '地力3連対'), ('n4', '全国4走'),
            ('rate4', '実4まくり率'), ('exp4', '期待まくり率'), ('power', 'まくり力'),
            ('win4', '実4_1着率'), ('st4', '全国4ST'), ('t4n', '当地4走'), ('t4mk', '当地4まくり率')]
NOK_COLS = [('touban', '登番'), ('name', '選手名'), ('jiriki', '地力3連対'), ('n6', '全国6走'),
            ('rate6_2', '実6_2着率'), ('rate6_3', '実6_3着率'), ('rate6_23', '実6_2_3'),
            ('exp6', '期待6_2_3'), ('resid', '残し残差'), ('adj2', '補正2着率'),
            ('st6', '全国6ST'), ('t6n', '当地6走'), ('t6_23', '当地6_2_3')]


def write_table(path, rows, cols):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow([jp for _, jp in cols])
        for r in rows:
            w.writerow([r[k] for k, _ in cols])


# ==================================================================
# 5. 当地ベースライン（アーカイブから算出・表示専用）
# ==================================================================
def base_stats(races, ents=None):
    """仕様書§1・§4の当地ベース値を、蓄積したレースから計算し直す。"""
    rs = [r for r in races if r.get('win_course')]
    n = len(rs)
    if not n:
        return {}
    six = {}
    if ents:
        # 仕様書 4-4「6号艇は2着と3着で配当が倍違う」を実データから出す
        pay = {(r['date'], r['rno']): int(r['payout']) for r in rs if r.get('payout')}
        by = defaultdict(list)
        for e in ents:
            if e['teiban'] == '6' and e['chaku'] in ('02', '03'):
                p = pay.get((e['date'], e['rno']))
                if p:
                    by[e['chaku']].append(p)
        for ch, key in (('02', 'six2'), ('03', 'six3')):
            v = sorted(by[ch])
            if v:
                six[key] = dict(n=len(v), median=v[len(v) // 2],
                                man=round(sum(1 for p in v if p >= 10000) / len(v) * 100, 1))
    pays = sorted(int(r['payout']) for r in rs if r.get('payout'))
    kim = defaultdict(int)
    for r in rs:
        kim[r['kimarite']] += 1
    med = pays[len(pays) // 2] if pays else 0
    return dict(
        days=len({r['date'] for r in rs}), races=n,
        in1=round(sum(1 for r in rs if r['win_course'] == '1') / n * 100, 1),
        man=round(sum(1 for p in pays if p >= 10000) / len(pays) * 100, 1) if pays else 0,
        median=med,
        makuri=round(kim['まくり'] / n * 100, 1),
        makurizashi=round(kim['まくり差し'] / n * 100, 1),
        makuri_kei=round((kim['まくり'] + kim['まくり差し']) / n * 100, 1),
        nige=round(kim['逃げ'] / n * 100, 1),
        sashi=round(kim['差し'] / n * 100, 1),
        nuki=round(kim['抜き'] / n * 100, 1),
        zenzuke=round(sum(1 for r in rs if r.get('zenzuke') in ('1', 1)) / n * 100, 1),
        **six)


# ==================================================================
# 6. Bファイル（当日出走表）
# ==================================================================
B_HEAD = re.compile(r'^\s*(\d{1,2})R\s+(\S+)')
B_DEADLINE = re.compile(r'締切予定\s*(\d{1,2}:\d{2})')
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
                       deadline=md.group(1) if md else '', boats=[])
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
# 7. 判定（仕様書§6＝朝の運用フロー。ここに書いていない材料は使わない）
# ==================================================================
def judge_race(r, T_MAK, T_NOK):
    """戻り値: (スコア, フラグ一覧, 艇ごとのバッジ, 買い目方針テキスト)"""
    score = 0
    flags = []
    badges = {b['teiban']: [] for b in r['boats']}
    subs = {b['teiban']: [] for b in r['boats']}
    boats = {b['teiban']: b for b in r['boats']}

    kado, nokoshi = None, None

    # --- 4号艇（枠なり前提）→ まくり屋表 ---
    b4 = boats.get(4)
    if b4:
        row = T_MAK.get(b4['regno'])
        if row:
            p = float(row['まくり力'])
            subs[4].append('まくり力 %+.1f' % p)
            if p >= MAKURIYA_TH:
                score += 2
                kado = 'makuriya'
                flags.append('まくり屋カド')
                badges[4].append('まくり屋●')
            elif p <= KADOKESHI_TH:
                score -= 1
                kado = 'keshi'
                flags.append('カド消し')
                badges[4].append('まくらない型')

    # --- 6号艇 → 6コース残し表 ---
    b6 = boats.get(6)
    if b6:
        row = T_NOK.get(b6['regno'])
        if row:
            v = float(row['残し残差'])
            subs[6].append('残し残差 %+.1f' % v)
            if v >= NOKOSHI_TH:
                score += 1
                nokoshi = 'nokosu'
                flags.append('6残す')
                badges[6].append('6残す●')
            elif v <= KIERU_TH:
                nokoshi = 'kieru'          # スコアは動かさない（ヒモ整理の表示のみ）
                flags.append('6切り')
                badges[6].append('6消える▲')

    # --- 買い目方針（指示書 §2-(B)）---
    if kado == 'makuriya' and nokoshi == 'nokosu':
        policy = ('本線 4-6-x / 4-5-x / 4-1-x。'
                  '二枚重ねは過去1年でn=11のためサンプル不足。'
                  '単独シグナル2本の重なりとして扱う。')
    elif kado == 'makuriya':
        policy = ('本線 4-5-x / 4-1-x / 4-3-x（4コースまくり時の2着は5コース26%・1コース・3コース）。'
                  '1号艇はまくり決着なら着外57%。頭は4、1は薄く。')
    elif nokoshi == 'nokosu':
        policy = ('ヒモ強調：6を2-3着に厚く。'
                  'まくり決着なら2着づけ、まくり差し決着なら3着づけ。')
    elif kado == 'keshi':
        policy = '4コース勝率6.7%。カドを消してヒモを絞れる。'
    else:
        policy = '見送り。'
    if kado == 'keshi' and nokoshi == 'nokosu':
        policy += ' 4は消し寄り（4コース勝率6.7%）。'
    if nokoshi == 'kieru':
        policy += ' 6は消える型（2-3連対15.8%）＝ヒモから外して点数を絞れる。'

    for b in r['boats']:
        b['badges'] = badges[b['teiban']]
        b['sub'] = ' ／ '.join(subs[b['teiban']])
    return score, flags, policy


def label_for(score, flags):
    if 'まくり屋カド' in flags and '6残す' in flags:
        return 'ana', 'カド×6残し'
    if 'まくり屋カド' in flags:
        return 'ana', 'まくり屋カド'
    if '6残す' in flags:
        return 'nitaku', '6残す'
    if 'カド消し' in flags:
        return 'katame', 'カド消し'
    return 'chukan', '中立'


# ==================================================================
# 8. メイン
# ==================================================================
def load_names():
    p = os.path.join(DATA, 'names.csv')
    if not os.path.exists(p):
        return {}
    with open(p, encoding='utf-8') as f:
        return {r['touban']: r['name'] for r in csv.DictReader(f)}


def save_names(names):
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, 'names.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['touban', 'name'])
        for tb in sorted(names):
            w.writerow([tb, names[tb]])


def update_data(backfill_days=None):
    """Kファイルを差分で取り込み、カウンタ・レースアーカイブ・名前表を更新する。"""
    counts, names = load_counts(), load_names()
    races, ents = load_rows(RACES_PATH()), load_rows(ENTS_PATH())
    seen = {(r['date'], r['rno']) for r in races}

    if backfill_days:
        start = TODAY - datetime.timedelta(days=backfill_days)
    elif os.path.exists(CURSOR_PATH()):
        start = datetime.date.fromisoformat(open(CURSOR_PATH()).read().strip()) \
            + datetime.timedelta(days=1)
    else:
        start = TODAY - datetime.timedelta(days=WINDOW_DAYS)

    end = TODAY - datetime.timedelta(days=1)      # 当日のKファイルはまだ出ていない
    if start > end:
        print('  データ更新: 追加分なし')
        return counts, races, names, ents

    d, got, miss = start, 0, 0
    while d <= end:
        raw = fetch_lzh('K', d)
        if raw:
            nat, trs, tes, nms = parse_k_day(raw)
            add_entries(counts, d.strftime('%Y-%m'), nat)
            names.update(nms)
            ds = d.isoformat()
            for r in trs:
                if (ds, str(r['rno'])) not in seen:
                    r['date'] = ds
                    races.append(r)
                    seen.add((ds, str(r['rno'])))
                    for e in tes:
                        if e['rno'] == r['rno']:
                            e['date'] = ds
                            ents.append(e)
            got += 1
        else:
            miss += 1
        d += datetime.timedelta(days=1)
    print('  データ更新: %s〜%s 取得%d日 / 欠測%d日' % (start, end, got, miss))

    # 窓の維持（古い月・古いレースを捨てる）
    cutoff_ym = (TODAY - datetime.timedelta(days=KEEP_DAYS)).strftime('%Y-%m')
    counts = {k: v for k, v in counts.items() if k[0] >= cutoff_ym}
    cutoff_d = (TODAY - datetime.timedelta(days=WINDOW_DAYS)).isoformat()
    races = [r for r in races if r['date'] >= cutoff_d]
    ents = [e for e in ents if e['date'] >= cutoff_d]

    save_counts(counts)
    save_rows(RACES_PATH(), races, RACE_COLS)
    save_rows(ENTS_PATH(), ents, ENT_COLS)
    save_names(names)
    with open(CURSOR_PATH(), 'w', encoding='utf-8') as f:
        f.write(end.isoformat())
    return counts, races, names, ents


def main():
    backfill = None
    if '--backfill' in sys.argv:
        i = sys.argv.index('--backfill')
        backfill = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else WINDOW_DAYS

    print('戸田(02) 日次パイプライン', TODAY.isoformat())
    counts, races, names, ents = update_data(backfill)

    mak, nok = build_tables(counts, names)
    write_table(os.path.join(DATA, 'toda_makuriya.csv'), mak, MAK_COLS)
    write_table(os.path.join(DATA, 'toda_nokoshi6.csv'), nok, NOK_COLS)
    n_my = sum(1 for r in mak if r['power'] >= MAKURIYA_TH)
    n_kk = sum(1 for r in mak if r['power'] <= KADOKESHI_TH)
    n_nk = sum(1 for r in nok if r['resid'] >= NOKOSHI_TH)
    n_ki = sum(1 for r in nok if r['resid'] <= KIERU_TH)
    print('  選手表: まくり屋表%d人（まくり屋%d/カド消し%d） 残し表%d人（残す%d/消える%d）'
          % (len(mak), n_my, n_kk, len(nok), n_nk, n_ki))

    base = base_stats(races, ents)
    if base:
        print('  当地ベース: %d日 %dレース イン%.1f%% 万舟%.1f%% まくり系%.1f%%'
              % (base['days'], base['races'], base['in1'], base['man'], base['makuri_kei']))

    T_MAK = {r['touban']: {'まくり力': r['power']} for r in mak}
    T_NOK = {r['touban']: {'残し残差': r['resid']} for r in nok}

    data = dict(date=TODAY.isoformat(),
                updated=(datetime.datetime.now(datetime.timezone.utc)
                         + datetime.timedelta(hours=9)).strftime('%Y-%m-%d %H:%M JST'),
                kaisai=False, base=base,
                tables=dict(makuriya=len(mak), makuriya_hit=n_my,
                            nokoshi=len(nok), nokoshi_hit=n_nk))

    raw_b = fetch_lzh('B', TODAY)
    parsed = parse_b(raw_b) if raw_b else None
    if parsed:
        data.update(kaisai=True, title=parsed['title'], nichime=parsed['day_n'])
        out = []
        for r in parsed['races']:
            score, flags, policy = judge_race(r, T_MAK, T_NOK)
            lab_cls, lab_txt = label_for(score, flags)
            out.append(dict(rno=r['rno'], rname=r['rname'], deadline=r['deadline'],
                            score=score, flags=flags, policy=policy,
                            label=lab_txt, label_cls=lab_cls, boats=r['boats']))
        data['races'] = out
        print('  開催あり: %s 第%s日 / %dレース（フラグ付き%d）'
              % (parsed['title'], parsed['day_n'], len(out),
                 sum(1 for r in out if r['flags'])))
    else:
        print('  本日は戸田の開催なし')

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    print('  ->', OUT_JSON)


if __name__ == '__main__':
    main()
