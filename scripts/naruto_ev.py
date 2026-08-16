# -*- coding: utf-8 -*-
"""鳴門(14) EV検証 — 企画レースの値付けを市場はどこまで織り込んでいるか

鳴門の売りは企画レース（レース名で判定・各120R/年）:
  とるならなる … 鉄板企画（イン72%・万舟11%）
  どーなるなる … 穴の巣（イン32%・万舟23%）
  どきどきなる … 二択（堅いか万舟）
  とにかくなる … 中間

測るもの（江戸川EV検証 ev_day1.py / ev_forms.py と同じ流儀）:
  A) 頭側: 3連単オッズの含意確率（1/オッズを正規化）vs 実測頭1率、企画別
  B) ヒモ側: 1号艇2着・6号艇2着/3着の値付け（santanが保存済みなので逆引き不要）
  C) 等額買い回収率

実行: python scripts/naruto_ev.py
"""
import os
import csv
import math
from collections import defaultdict

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
ODDS_DIR = os.path.join(REPO, 'data', 'odds', '14')
RACES = os.path.join(REPO, 'data', 'naruto', 'naruto_races.csv')

KIKAKU = ('とるならなる', 'どーなるなる', 'どきどきなる', 'とにかくなる')


def load_odds():
    out = {}
    for fn in sorted(os.listdir(ODDS_DIR)):
        if not fn.endswith('.csv'):
            continue
        with open(os.path.join(ODDS_DIR, fn), encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row['odds']:
                    out.setdefault((row['date'], row['race']), {})[row['combo']] = float(row['odds'])
    return {k: v for k, v in out.items() if len(v) >= 100}


def implied(om):
    inv = {c: 1.0 / o for c, o in om.items() if o > 0}
    tot = sum(inv.values())
    return {c: v / tot for c, v in inv.items()} if tot > 0 else {}


def main():
    odds = load_odds()
    with open(RACES, encoding='utf-8') as f:
        races = [r for r in csv.DictReader(f) if r['santan'] and r['payout']]
    joined = [(r, odds[(r['date'], r['rno'])]) for r in races
              if (r['date'], r['rno']) in odds]
    print('オッズ保存日数: %d日 / JOINできたレース: %d'
          % (len({d for d, _ in odds}), len(joined)))
    print()

    def bucket(rows, label, pos, boat):
        """pos着に boat 号艇が来る出目の 実測/含意/等額買い回収"""
        n = act = 0
        imp_sum = ret = 0.0
        for r, om in rows:
            im = implied(om)
            p = sum(v for c, v in im.items() if c.split('-')[pos - 1] == boat)
            if p == 0:
                continue
            n += 1
            imp_sum += p
            hit = r['santan'].split('-')[pos - 1] == boat
            act += 1 if hit else 0
            if hit:
                ret += int(r['payout'])
        if n == 0:
            print('  %-22s データなし' % label)
            return
        a, i = act / n, imp_sum / n
        s = math.sqrt(a * (1 - a) / n)
        z = (i - a) / s if s else 0
        print('  %-22s n=%4d  実測 %5.1f%%  含意 %5.1f%%  差 %+5.1fpt (z=%+.1f)  等額買い回収 %5.1f%%'
              % (label, n, a * 100, i * 100, (i - a) * 100, z, ret / (n * 20 * 100) * 100))

    def pick(name=None, exclude=False):
        if name is None:
            return joined
        if exclude:
            return [(r, om) for r, om in joined if r['rname'] not in KIKAKU]
        return [(r, om) for r, om in joined if r['rname'] == name]

    print('=== 頭側: 1号艇の値付け（企画別） ===')
    bucket(joined, '全レース', 1, '1')
    for k in KIKAKU:
        bucket(pick(k), k, 1, '1')
    bucket(pick('x', exclude=True), '非企画レース', 1, '1')
    print()
    print('=== ヒモ側: 全レース ===')
    bucket(joined, '1号艇が2着', 2, '1')
    bucket(joined, '6号艇が2着', 2, '6')
    bucket(joined, '6号艇が3着', 3, '6')
    print()
    print('=== ヒモ側: 穴の巣（どーなるなる）だけ ===')
    dn = pick('どーなるなる')
    bucket(dn, '1号艇が2着', 2, '1')
    bucket(dn, '2号艇が頭', 1, '2')
    bucket(dn, '6号艇が3着', 3, '6')
    print()
    print('読み方: 差プラス＝市場がその出目を過大評価（買うと分が悪い）／マイナス＝軽視。')
    print('        等額買い回収100%超えが実利の目安（控除25%が壁）。')


if __name__ == '__main__':
    main()
