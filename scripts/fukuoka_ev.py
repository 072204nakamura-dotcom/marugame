# -*- coding: utf-8 -*-
"""
福岡 うねり窓EV検証：確定オッズ × 窓レース結果の照合（毎朝フル再計算）
出力:
  data/fukuoka_ev_log.csv     … 窓レース×バンドの明細（等額買い収支・合成オッズ）
  fukuoka/data/ev_summary.json … ページ表示用サマリー
実行: python scripts/fukuoka_ev.py  （fukuoka_racecard.py の後）
"""
import os, re, csv, json, glob, unicodedata
from itertools import permutations

import lhafile

JCD = '22'
ODDS_DIR = 'data/odds/22'
LZH_K, LZH_B = 'data/lzh_k', 'data/lzh_b'
TIDE_DIR, TIDE_ST = 'data/tide', 'QF'
LOG_CSV = 'data/fukuoka_ev_log.csv'
SUM_JSON = 'fukuoka/data/ev_summary.json'
TAKEOUT = 0.75  # 3連単の払戻率

S8 = [f'2-3-{x}' for x in '1456'] + [f'2-5-{x}' for x in '1346']
S20 = [f'2-{a}-{b}' for a, b in permutations('13456', 2)]

RE_PAY = re.compile(r'^\s+(\d{1,2})R\s+([1-6]-[1-6]-[1-6])\s+(\d+)')
RE_BRACE = re.compile(r'^\s*(\d{1,2})R\s.*締切予定(\d{1,2}):(\d{2})')


def read_lzh(path, tag):
    try:
        lf = lhafile.Lhafile(path)
        raw = lf.read(lf.infolist()[0].filename).decode('shift_jis', errors='replace')
    except Exception:
        return None
    key = f'{JCD}{tag}BGN'
    if key not in raw:
        return None
    return raw.split(key)[1].split(f'{JCD}{tag}END')[0]


def load_odds(path):
    """{(race:int, combo:str): odds:float}"""
    out = {}
    with open(path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            try:
                o = float(row['odds'])
            except (ValueError, TypeError, KeyError):
                continue
            out[(int(row['race']), row['combo'].strip())] = o
    return out


def deadlines(date):
    blk = read_lzh(f"{LZH_B}/b{date[2:4]}{date[5:7]}{date[8:10]}.lzh", 'B')
    if not blk:
        return {}
    out = {}
    for ln in blk.split('\n'):
        m = RE_BRACE.match(unicodedata.normalize('NFKC', ln))
        if m:
            out[int(m.group(1))] = (int(m.group(2)), int(m.group(3)))
    return out


def results(date):
    """{race:(combo, payout)} 3連単（ブロック冒頭の払戻一覧・各レース最初の組）"""
    blk = read_lzh(f"{LZH_K}/k{date[2:4]}{date[5:7]}{date[8:10]}.lzh", 'K')
    if not blk:
        return {}
    out = {}
    for ln in blk.split('\n'):
        m = RE_PAY.match(ln)
        if m and 'H' not in ln:
            r = int(m.group(1))
            if r not in out:
                out[r] = (m.group(2), int(m.group(3)))
    return out


def tide_table():
    t = {}
    for p in glob.glob(f'{TIDE_DIR}/{TIDE_ST}_*.txt'):
        for ln in open(p):
            if len(ln) < 80 or ln[78:80] != TIDE_ST:
                continue
            d = f"20{int(ln[72:74]):02d}-{int(ln[74:76]):02d}-{int(ln[76:78]):02d}"
            t[d] = [int(ln[i*3:i*3+3]) for i in range(24)]
    return t


def tide_at(vals, h, m):
    x = min(h + m / 60.0, 23.0)
    i = int(x); j = min(i + 1, 23); f = x - i
    return vals[i] * (1 - f) + vals[j] * f


def band_row(date, race, tide, odds, res, band, name):
    combo, pay = res
    olist = [odds.get((race, c)) for c in band]
    olist = [o for o in olist if o and o > 0]
    if len(olist) < len(band) - 2:      # 欠場等で帯が壊れている日は除外
        return None
    synth_p = sum(1 / o for o in olist)              # 帯の合成含意確率（控除込み）
    hit = combo in band
    ret = (odds.get((race, combo)) or 0) * 100 if hit else 0
    cost = len(band) * 100
    return dict(date=date, race=race, tide=round(tide, 1), band=name,
                cost=cost, hit=int(hit), ret=int(ret),
                synth_p=round(synth_p, 4), combo=combo, payout=pay)


def main():
    odds_files = sorted(glob.glob(f'{ODDS_DIR}/*.csv'))
    if not odds_files:
        raise SystemExit(f'オッズが見つかりません: {ODDS_DIR}/*.csv （data/odds/直下も確認のこと）')
    tides = tide_table()
    rows = []
    covered, windows = 0, 0
    for path in odds_files:
        date = os.path.basename(path)[:10]
        vals = tides.get(date)
        dl = deadlines(date)
        res = results(date)
        if not (vals and dl and res):
            continue
        covered += 1
        for race, (h, m) in dl.items():
            if race not in res:
                continue
            tv = tide_at(vals, h, m)
            if tv < 170:
                continue
            windows += 1
            odds = load_odds(path)
            for band, name in ((S8, 'S8'), (S20, 'S20')):
                r = band_row(date, race, tv, odds, res[race], band, name)
                if r:
                    rows.append(r)
    os.makedirs(os.path.dirname(LOG_CSV), exist_ok=True)
    with open(LOG_CSV, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['date', 'race', 'tide', 'band', 'cost',
                                          'hit', 'ret', 'synth_p', 'combo', 'payout'])
        w.writeheader(); w.writerows(rows)

    summary = {}
    for name in ('S8', 'S20'):
        rs = [r for r in rows if r['band'] == name]
        n = len(rs)
        cost = sum(r['cost'] for r in rs)
        ret = sum(r['ret'] for r in rs)
        hits = sum(r['hit'] for r in rs)
        mkt_p = sum(r['synth_p'] for r in rs) / n if n else 0          # 市場の帯含意確率（控除込み平均）
        summary[name] = dict(
            n=n, hits=hits,
            roi=round(ret / cost * 100, 1) if cost else None,
            hit_rate=round(hits / n * 100, 1) if n else None,
            mkt_implied=round(mkt_p * 100, 1),                          # そのまま（控除込み）
            mkt_implied_fair=round(mkt_p * TAKEOUT * 100, 1))           # 控除補正後の公正確率
    out = dict(covered_days=covered, window_races=windows, bands=summary)
    os.makedirs(os.path.dirname(SUM_JSON), exist_ok=True)
    with open(SUM_JSON, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print('判定基準：hit_rate > mkt_implied_fair なら市場は窓を織り込んでいない（エッジ残存）。'
          'roiが実オッズでの等額買い回収率。')


if __name__ == '__main__':
    main()
