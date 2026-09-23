# -*- coding: utf-8 -*-
"""
中穴路線 人気帯EV検証 v1（全レース × 確定オッズ照合・毎回フル再計算）

検証すること：
 A) 3連単を人気帯ごとに全部買った場合の回収率（51番人気以降カットの裏付け確認）
 B) 「1頭固定・2〜3着を4〜6号艇に寄せる」型の回収率
    （フィルタなし／50番人気まで／50番人気まで かつ 15倍以上 の3通り）

実行: python scripts/ninki_band_ev.py
出力:
  data/ninki_band_log.csv      … レース明細（計算した人気順位とKファイル人気の突き合わせ用）
  data/ninki_band_summary.json … 集計結果
前提: data/odds/{JCD}/YYYY-MM-DD.csv（読むだけ） / data/lzh_k/kYYMMDD.lzh（読むだけ）
"""
import os, re, sys, csv, json, glob

import lhafile

from ev_common import ninki_rank  # 人気順位の付け方は全スクリプト共通

ODDS_ROOT = 'data/odds'
LZH_K = 'data/lzh_k'
LOG_CSV = 'data/ninki_band_log.csv'
SUM_JSON = 'data/ninki_band_summary.json'

NINKI_MAX = 50      # 確定方針（2026-09-19）：51番人気以降は買わない
ODDS_MIN = 15.0     # 中穴の下限（15倍以上）
HAIRCUT = 5.0       # 確定→直前オッズのすべり想定（pt）

VENUES = {'15': '丸亀', '03': '江戸川', '14': '鳴門', '17': '宮島',
          '22': '福岡', '02': '戸田', '04': '平和島', '09': '津'}

BANDS = [(1, 1), (2, 5), (6, 12), (13, 24), (25, 36), (37, 50),
         (51, 70), (71, 90), (91, 120)]

# combo は '1-4-2' 形式。c[0]=1着 c[2]=2着 c[4]=3着
PATTERNS = {
    'P0_1頭ぜんぶ(基準)': lambda c: c[0] == '1',
    'P1_1-456-全':        lambda c: c[0] == '1' and c[2] in '456',
    'P2_1-全-56':         lambda c: c[0] == '1' and c[4] in '56',
    'P3_1頭で56絡み':     lambda c: c[0] == '1' and ('5' in c[2:] or '6' in c[2:]),
    'P4_2〜4頭(参考)':    lambda c: c[0] in '234',
}
FILTERS = {
    'F0_絞りなし':          lambda rank, odds: True,
    'F1_50番人気まで':      lambda rank, odds: rank <= NINKI_MAX,
    'F2_50番人気まで&15倍+': lambda rank, odds: rank <= NINKI_MAX and odds >= ODDS_MIN,
}

RE_PAY = re.compile(r'^\s+(\d{1,2})R\s+([1-6]-[1-6]-[1-6])\s+(\d+)')
RE_HEAD = re.compile(r'^\s{0,6}(\d{1,2})R\s+\S+.*H\d+m')
RE_3T = re.compile(r'３連単\s+([1-6]-[1-6]-[1-6])\s+(\d+)\s+人気\s+(\d+)')


def k_results(date, jcd):
    """{race: dict(combo, payout, k_ninki)} を返す。Kファイルが無ければ {}"""
    path = f"{LZH_K}/k{date[2:4]}{date[5:7]}{date[8:10]}.lzh"
    if not os.path.exists(path):
        return {}
    try:
        lf = lhafile.Lhafile(path)
        raw = lf.read(lf.infolist()[0].filename).decode('shift_jis', errors='replace')
    except Exception:
        return {}
    key = f'{jcd}KBGN'
    if key not in raw:
        return {}
    blk = raw.split(key)[1].split(f'{jcd}KEND')[0]
    out, cur = {}, None
    for line in blk.split('\n'):
        m = RE_PAY.match(line)
        if m and cur is None:                       # 冒頭の払戻一覧
            out.setdefault(int(m.group(1)), dict(combo=m.group(2), payout=int(m.group(3)), k_ninki=None))
            continue
        h = RE_HEAD.match(line)
        if h:
            cur = int(h.group(1))
            continue
        t = RE_3T.search(line)
        if t and cur in out and out[cur]['k_ninki'] is None and t.group(1) == out[cur]['combo']:
            out[cur]['k_ninki'] = int(t.group(3))
    return out


def odds_files(jcd):
    fs = sorted(glob.glob(f'{ODDS_ROOT}/{jcd}/*.csv'))
    if not fs and jcd == '15':                      # 丸亀だけ旧形式（直下）で残っている場合
        fs = sorted(glob.glob(f'{ODDS_ROOT}/*.csv'))
    return fs


def load_odds(path):
    """{race: [(combo, odds), ...]}（オッズ空欄＝欠場は除外）"""
    d = {}
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            try:
                o = float(r['odds'])
            except (ValueError, TypeError, KeyError):
                continue
            if o <= 0:
                continue
            d.setdefault(int(r['race']), []).append((r['combo'], o))
    return d


class Acc:
    """1つの買い方の成績をためる箱"""
    def __init__(self):
        self.rows = []                              # (date, race, cost, rev)

    def add(self, date, race, n_points, rev):
        if n_points > 0:
            self.rows.append((date, race, n_points * 100, rev))

    def stat(self):
        rows = sorted(self.rows)
        n = len(rows)
        if n == 0:
            return dict(races=0)
        cost = sum(r[2] for r in rows); rev = sum(r[3] for r in rows)
        hits = sum(1 for r in rows if r[3] > 0)
        half = n // 2

        def roi(sub):
            c = sum(r[2] for r in sub)
            return round(100 * sum(r[3] for r in sub) / c, 1) if c else None
        streak = worst = 0; bal = peak = dd = 0
        for r in rows:
            streak = 0 if r[3] > 0 else streak + 1
            worst = max(worst, streak)
            bal += r[3] - r[2]; peak = max(peak, bal); dd = max(dd, peak - bal)
        return dict(races=n, points_per_race=round(cost / 100 / n, 1), hits=hits,
                    hit_rate=round(100 * hits / n, 1), roi=roi(rows),
                    roi_haircut=round(roi(rows) - HAIRCUT, 1),
                    roi_first=roi(rows[:half]), roi_second=roi(rows[half:]),
                    max_losing_streak=worst, max_dd_yen=dd)


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')    # Windowsのcp932で落ちないように
    except Exception:
        pass
    band = {}       # (venue, 'lo-hi') -> Acc
    pat = {}        # (venue, pattern, filter) -> Acc
    log = []
    n_match = n_cmp = 0
    for jcd, name in VENUES.items():
        for path in odds_files(jcd):
            date = os.path.basename(path)[:10]
            odds_by_race = load_odds(path)
            res = k_results(date, jcd)
            for race, lst in odds_by_race.items():
                if race not in res or len(lst) < 60:       # 結果なし・オッズ欠損が大きい日は除外
                    continue
                r = res[race]
                rank = ninki_rank(lst)
                odds = dict(lst)
                win = r['combo']
                if win not in rank:
                    continue
                if r['k_ninki']:
                    n_cmp += 1
                    if abs(rank[win] - r['k_ninki']) <= 2:
                        n_match += 1
                log.append([date, jcd, race, win, r['payout'], rank[win], r['k_ninki'], odds[win]])
                for venue in (name, '8場合算'):
                    for lo, hi in BANDS:
                        pts = [c for c in rank if lo <= rank[c] <= hi]
                        band.setdefault((venue, f'{lo}-{hi}'), Acc()).add(
                            date, f'{jcd}-{race:02d}', len(pts), r['payout'] if win in pts else 0)
                    for pn, pf in PATTERNS.items():
                        for fn, ff in FILTERS.items():
                            pts = [c for c in rank if pf(c) and ff(rank[c], odds[c])]
                            pat.setdefault((venue, pn, fn), Acc()).add(
                                date, f'{jcd}-{race:02d}', len(pts), r['payout'] if win in pts else 0)

    os.makedirs('data', exist_ok=True)
    with open(LOG_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['date', 'jcd', 'race', 'combo', 'payout', 'rank_calc', 'k_ninki', 'final_odds'])
        w.writerows(sorted(log))

    summary = dict(
        params=dict(NINKI_MAX=NINKI_MAX, ODDS_MIN=ODDS_MIN, HAIRCUT=HAIRCUT),
        races_total=len(log),
        rank_check=dict(compared=n_cmp, within2=n_match,
                        rate=round(100 * n_match / n_cmp, 1) if n_cmp else None),
        bands={f'{v}|{b}': a.stat() for (v, b), a in band.items()},
        patterns={f'{v}|{p}|{fl}': a.stat() for (v, p, fl), a in pat.items()},
    )
    with open(SUM_JSON, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    print(f'対象レース {len(log)} / 人気順位の一致(±2以内) {summary["rank_check"]}')
    print('\n[A] 人気帯別の回収率（8場合算）')
    for lo, hi in BANDS:
        s = band.get(('8場合算', f'{lo}-{hi}'))
        if s:
            s = s.stat()
            print(f'  {lo:>3}-{hi:<3} 的中{s["hit_rate"]:>5}%  回収{s["roi"]:>6}%  前半{s["roi_first"]} 後半{s["roi_second"]}')
    print('\n[B] 買い方別（8場合算）')
    for pn in PATTERNS:
        for fn in FILTERS:
            s = pat.get(('8場合算', pn, fn))
            if s:
                s = s.stat()
                if s['races']:
                    print(f'  {pn:<16}{fn:<20} {s["races"]:>5}R 点数{s["points_per_race"]:>5} 的中{s["hit_rate"]:>5}% '
                          f'回収{s["roi"]:>6}% (−5pt後{s["roi_haircut"]}) 前半{s["roi_first"]} 後半{s["roi_second"]} '
                          f'最大連敗{s["max_losing_streak"]} 最大DD{s["max_dd_yen"]}円')


if __name__ == '__main__':
    main()
