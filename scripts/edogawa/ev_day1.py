# -*- coding: utf-8 -*-
"""江戸川(03) EV検証 その1 — 「初日の1号艇は過小に嫌われているか」

仕様書 §5 のEV検証・最優先課題。data/odds/03/（確定オッズ）と
data/edogawa/ed_races.csv（結果）を突き合わせて測る。

測るもの:
  A) 市場の含意確率: 3連単オッズから「頭=艇番1」20通りの含意確率を合算
     （1/オッズ を全120通りで正規化 → 控除率が自動で消える）
  B) 実測の頭率: win_teiban=='1' の割合
  C) 回収率: 「頭1の20点を各100円」「頭≠1の100点を各100円」を等額買いした場合
     （確定オッズ＝締切直前に買った場合の近似。自分の投票がオッズを動かす分は無視）

読み方:
  市場含意 > 実測  → 1号艇は過剰人気（頭≠1側に妙味の可能性）
  市場含意 ≈ 実測  → 織り込み済み（エッジなし）

実行: python scripts/edogawa/ev_day1.py
"""
import os
import csv
import math
from collections import defaultdict

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
ODDS_DIR = os.path.join(REPO, 'data', 'odds', '03')
RACES = os.path.join(REPO, 'data', 'edogawa', 'ed_races.csv')


def load_market():
    """日付ごとの {(date,rno): 頭別の含意確率dict} を作る"""
    out = {}
    if not os.path.isdir(ODDS_DIR):
        return out
    for fn in sorted(os.listdir(ODDS_DIR)):
        if not fn.endswith('.csv'):
            continue
        by_race = defaultdict(list)
        with open(os.path.join(ODDS_DIR, fn), encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row['odds']:
                    by_race[row['race']].append((row['combo'], float(row['odds'])))
        for rno, rows in by_race.items():
            if len(rows) < 100:          # 欠場で組数が減った日は割合が歪むので外す
                continue
            inv = [(c, 1.0 / o) for c, o in rows if o > 0]
            tot = sum(v for _, v in inv)
            if tot <= 0:
                continue
            head_p = defaultdict(float)
            for c, v in inv:
                head_p[c.split('-')[0]] += v / tot
            out[(fn[:-4], rno)] = dict(head_p)
    return out


def load_results():
    with open(RACES, encoding='utf-8') as f:
        return [r for r in csv.DictReader(f) if r['win_teiban']]


def se(p, n):
    return math.sqrt(p * (1 - p) / n) if n else 0


def bucket_stats(rows, market):
    """レース集合に対して 実測頭1率 / 市場含意 / 回収率 を返す"""
    n = imp_sum = won1 = 0
    ret1 = ret_not1 = 0.0
    for r in rows:
        m = market.get((r['date'], r['rno']))
        if m is None or '1' not in m:
            continue
        n += 1
        imp_sum += m['1']
        w1 = (r['win_teiban'] == '1')
        won1 += 1 if w1 else 0
        pay = int(r['payout']) if r['payout'] else 0
        if w1:
            ret1 += pay          # 頭1の20点セットに当たりが含まれる
        else:
            ret_not1 += pay      # 頭≠1の100点セット側
    if n == 0:
        return None
    return dict(n=n, act=won1 / n, imp=imp_sum / n,
                roi1=ret1 / (n * 20 * 100),         # 20点×100円
                roi_not1=ret_not1 / (n * 100 * 100))  # 100点×100円


def show(label, s):
    if not s:
        print('  %-16s データなし' % label)
        return
    gap = (s['imp'] - s['act']) * 100
    z = gap / 100 / se(s['act'], s['n']) if se(s['act'], s['n']) else 0
    print('  %-16s n=%3d  実測頭1率 %5.1f%%  市場含意 %5.1f%%  差 %+5.1fpt (z=%+.1f)'
          % (label, s['n'], s['act'] * 100, s['imp'] * 100, gap, z))
    print('  %-16s        回収率: 頭1等額買い %5.1f%% / 頭≠1等額買い %5.1f%%'
          % ('', s['roi1'] * 100, s['roi_not1'] * 100))


def main():
    market = load_market()
    races = load_results()
    days_with_odds = len({d for d, _ in market})
    print('オッズ保存日数: %d日 / 結果とJOINできたレースで集計' % days_with_odds)
    print()

    def pick(cond):
        return [r for r in races if cond(r)]

    print('=== 全体 ===')
    show('全レース', bucket_stats(races, market))
    print()
    print('=== 日目別（仕様書E-4: 初日の実測イン40.5%） ===')
    show('初日', bucket_stats(pick(lambda r: r['nichime'] == '1'), market))
    show('2日目以降', bucket_stats(pick(lambda r: r['nichime'] not in ('', '1')), market))
    print()
    print('=== レース番号別（仕様書E-5: 2-6Rが谷・6Rが底） ===')
    show('1R', bucket_stats(pick(lambda r: r['rno'] == '1'), market))
    show('2-6R', bucket_stats(pick(lambda r: 2 <= int(r['rno']) <= 6), market))
    show('6R単独', bucket_stats(pick(lambda r: r['rno'] == '6'), market))
    show('9-12R', bucket_stats(pick(lambda r: int(r['rno']) >= 9), market))
    print()
    print('=== 重ね掛け（最濃条件） ===')
    show('初日×2-6R', bucket_stats(
        pick(lambda r: r['nichime'] == '1' and 2 <= int(r['rno']) <= 6), market))
    show('初日×6R', bucket_stats(
        pick(lambda r: r['nichime'] == '1' and r['rno'] == '6'), market))
    print()
    print('読み方: 差がプラス＝市場は1号艇を実力より高く評価（過剰人気）。')
    print('        回収率は等額買いの実測。100%超えが出るかどうかが本題。')
    print('注意: 確定オッズ＝締切直前に買えた場合の近似。オッズ日数が少ないうちは幅を持って見る。')


if __name__ == '__main__':
    main()
