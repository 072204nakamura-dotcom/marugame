# -*- coding: utf-8 -*-
"""平和島 壁強●×頭1: 券種（賭け方の構造）の比較検討"""
import sys, os, csv, math, random
sys.path.insert(0, 'scripts/heiwajima')
import ev_sashi as S
from collections import defaultdict

odds = S.load_odds()
races = {(r['date'], r['race']): r for r in S.load(os.path.join(S.D, 'hw_races_archive.csv'))
         if r['combo'] and r['payout']}
ent2 = {}
for e in S.load(os.path.join(S.D, 'hw_entries_archive.csv')):
    if e['boat'] == '2':
        ent2[(e['date'], e['race'])] = e['regno']
wall = {r['regno']: r for r in S.load(os.path.join(S.D, 'hw_wall.csv'))}
KABE = sorted([(k, races[k], odds[k]) for k in races
               if k in odds and k in ent2 and wall.get(ent2[k], {}).get('壁') == '壁強●'],
              key=lambda x: x[0][0])
print('壁強●レース n=%d' % len(KABE))

HEAD1 = [f'1-{a}-{b}' for a in '23456' for b in '23456' if a != b]

def equal(rows, band):
    cost = ret = 0.0
    for k, r, om in rows:
        avail = [c for c in band if c in om]
        if len(avail) < len(band) - 4: continue
        cost += len(avail) * 100
        if r['combo'] in avail: ret += int(r['payout'])
    return ret / cost * 100 if cost else 0

def proportional(rows, band):
    """1/オッズ比例で配分（=帯の合成オッズを固定で受け取る合成券）"""
    cost = ret = 0.0
    for k, r, om in rows:
        avail = {c: om[c] for c in band if c in om}
        if len(avail) < len(band) - 4: continue
        synth_p = sum(1/o for o in avail.values())
        cost += 100
        if r['combo'] in avail:
            ret += 100 / synth_p    # どの組でも払戻一定 = 合成オッズ×100円
    return ret / cost * 100 if cost else 0

print()
print('=== 戦略比較（壁強●・n=%d） ===' % len(KABE))
print('  %-28s 等額     比例配分(合成)' % '帯')
print('  %-28s %5.1f%%   %5.1f%%' % ('頭1(20点)', equal(KABE, HEAD1), proportional(KABE, HEAD1)))
for s in '23456':
    band = [f'1-{s}-{t}' for t in '23456' if t != s]
    print('  %-28s %5.1f%%   %5.1f%%' % (f'1-{s}-全(4点)', equal(KABE, band), proportional(KABE, band)))
b23 = [f'1-{s}-{t}' for s in '23' for t in '23456' if t != s]
print('  %-28s %5.1f%%   %5.1f%%' % ('1-{2,3}-全(8点)', equal(KABE, b23), proportional(KABE, b23)))

print()
print('=== 2着の分布（頭1のとき、2着はどこに来て、市場はどう見ているか） ===')
n1 = 0
act2 = defaultdict(int); imp2 = defaultdict(float)
for k, r, om in KABE:
    im = S.implied(om)
    tot1 = sum(v for c, v in im.items() if c.startswith('1-'))
    for s in '23456':
        imp2[s] += sum(v for c, v in im.items() if c.startswith(f'1-{s}-')) / tot1 if tot1 else 0
    if r['combo'].startswith('1-'):
        n1 += 1; act2[r['combo'].split('-')[1]] += 1
for s in '23456':
    print('  2着=%s  実測 %5.1f%%  市場(頭1内訳) %5.1f%%' % (s, act2[s]/n1*100 if n1 else 0, imp2[s]/len(KABE)*100))

print()
print('=== 最良戦略の頑健性 ===')
h = len(KABE) // 2
for lbl, part in (('前半', KABE[:h]), ('後半', KABE[h:])):
    print('  %s n=%2d (%s〜%s): 頭1比例 %5.1f%% / 1-{2,3}比例 %5.1f%%'
          % (lbl, len(part), part[0][0][0], part[-1][0][0],
             proportional(part, HEAD1), proportional(part, b23)))
# ブートストラップ（比例・頭1）
random.seed(1)
outs = []
for k, r, om in KABE:
    avail = {c: om[c] for c in HEAD1 if c in om}
    if len(avail) < 16: continue
    sp = sum(1/o for o in avail.values())
    outs.append(100/sp if r['combo'] in avail else 0.0)
sims = sorted(sum(random.choice(outs) for _ in outs)/(100*len(outs))*100 for _ in range(2000))
print('  頭1比例ブートストラップ: 中央値%.0f%% 90%%区間[%.0f,%.0f] 100%%超%.0f%%'
      % (sims[1000], sims[100], sims[1900], sum(s > 100 for s in sims)/20))
