# -*- coding: utf-8 -*-
"""江戸川(03) EV検証 その2 — ヒモ側の値付け（6号艇・1号艇2着残し）

仕様書§5の検証課題:
  2) 6コース残り（全国最高の3連率27.1%）は適正価格か
  併せて、差し водоем フォームの根幹「X-1-Y（1号艇2着残し）」の値付けも測る。

当選組の逆引き:
  ed_races.csv は3連単の組番を保存していない（払戻と1着艇番のみ）。
  そこで「当選組の払戻 ÷ 100 ＝ その組の確定オッズ」の恒等式を使い、
  レース内の120通りから払戻/100 と一致するオッズの組を探す。
  一致が2通り以上ある場合（同オッズ）は曖昧なので捨てる（件数を報告）。

実行: python scripts/edogawa/ev_forms.py
"""
import os
import csv
import math
from collections import defaultdict

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
ODDS_DIR = os.path.join(REPO, 'data', 'odds', '03')
RACES = os.path.join(REPO, 'data', 'edogawa', 'ed_races.csv')


def load_odds():
    """{(date,rno): {combo: odds}}"""
    out = {}
    for fn in sorted(os.listdir(ODDS_DIR)):
        if not fn.endswith('.csv'):
            continue
        with open(os.path.join(ODDS_DIR, fn), encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row['odds']:
                    out.setdefault((row['date'], row['race']), {})[row['combo']] = float(row['odds'])
    return out


def implied(odds_map):
    """combo -> 正規化した含意確率"""
    inv = {c: 1.0 / o for c, o in odds_map.items() if o > 0}
    tot = sum(inv.values())
    return {c: v / tot for c, v in inv.items()} if tot > 0 else {}


def main():
    odds = load_odds()
    with open(RACES, encoding='utf-8') as f:
        races = [r for r in csv.DictReader(f) if r['win_teiban'] and r['payout']]

    # --- 当選組の逆引き ---
    joined, ambiguous, nomatch = [], 0, 0
    for r in races:
        om = odds.get((r['date'], r['rno']))
        if not om or len(om) < 100:
            continue
        target = int(r['payout']) / 100.0
        hits = [c for c, o in om.items() if abs(o - target) < 0.001]
        # 1着艇番が分かっているので、それで絞り込める（曖昧さがかなり減る）
        hits = [c for c in hits if c.split('-')[0] == r['win_teiban']]
        if len(hits) == 1:
            joined.append((r, hits[0], om))
        elif len(hits) > 1:
            ambiguous += 1
        else:
            nomatch += 1
    print('オッズとJOINできたレース: %d（曖昧で除外 %d ／ 不一致 %d）'
          % (len(joined), ambiguous, nomatch))
    print('※不一致は同着・返還などの特殊レース。曖昧は同オッズの組が複数。')
    print()

    def bucket(rows, label, pos, boat):
        """pos: 1=頭,2=2着,3=3着  boat: 艇番文字。実測と含意とROIを出す"""
        n = 0
        act = 0
        imp_sum = 0.0
        ret = 0.0
        for r, combo, om in rows:
            im = implied(om)
            p = sum(v for c, v in im.items() if c.split('-')[pos - 1] == boat)
            if p == 0:
                continue
            n += 1
            imp_sum += p
            hit = combo.split('-')[pos - 1] == boat
            act += 1 if hit else 0
            if hit:
                ret += int(r['payout'])
        if n == 0:
            print('  %-18s データなし' % label)
            return
        n_combos = 20   # 特定の艇を特定の着に固定した組は 5P2 = 20通り
        a, i = act / n, imp_sum / n
        s = math.sqrt(a * (1 - a) / n)
        z = (i - a) / s if s else 0
        print('  %-18s n=%4d  実測 %5.1f%%  市場含意 %5.1f%%  差 %+5.1fpt (z=%+.1f)  等額買い回収 %5.1f%%'
              % (label, n, a * 100, i * 100, (i - a) * 100, z, ret / (n * n_combos * 100) * 100))

    d1 = [(r, c, om) for r, c, om in joined if r['nichime'] == '1']
    zone = [(r, c, om) for r, c, om in joined if 2 <= int(r['rno']) <= 6]

    print('=== 6号艇のヒモの値付け（仕様書E-3: 3連率27.1%＝全国最高） ===')
    bucket(joined, '6号艇が2着(全)', 2, '6')
    bucket(joined, '6号艇が3着(全)', 3, '6')
    bucket(d1, '6号艇2着(初日)', 2, '6')
    bucket(zone, '6号艇2着(2-6R)', 2, '6')
    print()
    print('=== 1号艇の2着残し（X-1-Y フォームの根幹） ===')
    bucket(joined, '1号艇が2着(全)', 2, '1')
    bucket(d1, '1号艇2着(初日)', 2, '1')
    bucket(zone, '1号艇2着(2-6R)', 2, '1')
    print()
    print('=== 対照: 2号艇の頭（南風の受け皿・参考） ===')
    bucket(joined, '2号艇が頭(全)', 1, '2')
    print()
    print('読み方: 差プラス＝市場がその出目を実力より高く評価（買うと損しやすい）。')
    print('        差マイナス＝市場が軽視（歪みの候補）。等額買い回収100%超えが実利の目安。')


if __name__ == '__main__':
    main()
