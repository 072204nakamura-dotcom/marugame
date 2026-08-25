# -*- coding: utf-8 -*-
"""平和島(04) EV検証 — 差し水面シグナル（2号艇のタイプ）は市場に織り込まれているか

仕様書§4-4の買い目方針（事前定義）をそのまま実オッズで検証する:
  2号艇=差し巧者●/食う型 → 本線2-1-全(4点)＋押さえ2-3-1・2-4-1（6点）
  2号艇=素通し型          → 3-1-全＋4-1-全（8点）
  2号艇=壁強●            → 見送り推奨（ここでは頭1帯の値付きを情報表示）
データ: data/odds/04 × hw_races_archive/hw_entries_archive（重なり期間のみ）
実行: python scripts/heiwajima/ev_sashi.py
"""
import os, csv, math
from collections import defaultdict

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
D = os.path.join(REPO, 'data', 'heiwajima')
ODDS_DIR = os.path.join(REPO, 'data', 'odds', '04')

def load(p, bom=True):
    with open(p, encoding='utf-8-sig' if bom else 'utf-8') as f:
        return list(csv.DictReader(f))

def load_odds():
    out = {}
    for fn in sorted(os.listdir(ODDS_DIR)):
        if not fn.endswith('.csv'): continue
        with open(os.path.join(ODDS_DIR, fn), encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row['odds']:
                    out.setdefault((row['date'], row['race']), {})[row['combo']] = float(row['odds'])
    return {k: v for k, v in out.items() if len(v) >= 100}

def implied(om):
    inv = {c: 1.0/o for c, o in om.items() if o > 0}
    t = sum(inv.values())
    return {c: v/t for c, v in inv.items()} if t else {}

BANDS = {
    '本線2-1-全(4点)':      ['2-1-3','2-1-4','2-1-5','2-1-6'],
    '本線+押さえ(6点)':     ['2-1-3','2-1-4','2-1-5','2-1-6','2-3-1','2-4-1'],
    '3-1全+4-1全(8点)':     ['3-1-2','3-1-4','3-1-5','3-1-6','4-1-2','4-1-3','4-1-5','4-1-6'],
    '頭2(20点)':            [f'2-{a}-{b}' for a in '13456' for b in '13456' if a != b],
    '頭1(20点)':            [f'1-{a}-{b}' for a in '23456' for b in '23456' if a != b],
}

def main():
    odds = load_odds()
    races = {(r['date'], r['race']): r for r in load(os.path.join(D, 'hw_races_archive.csv'))
             if r['combo'] and r['payout']}
    ent2 = {}
    for e in load(os.path.join(D, 'hw_entries_archive.csv')):
        if e['boat'] == '2':
            ent2[(e['date'], e['race'])] = e['regno']
    wall = {r['regno']: r for r in load(os.path.join(D, 'hw_wall.csv'))}
    sashi = {r['regno']: r for r in load(os.path.join(D, 'hw_c2sashi.csv'))}

    def c2type(reg):
        s = sashi.get(reg, {})
        w = wall.get(reg, {})
        if s.get('差し巧者') == '●': return '差し巧者●'
        if w.get('壁') == '壁弱●': return '壁弱●' + w.get('弱タイプ', '')
        if w.get('壁') == '壁強●': return '壁強●'
        return '印なし'

    groups = defaultdict(list)
    for k, r in races.items():
        if k not in odds or k not in ent2: continue
        groups[c2type(ent2[k])].append((r, odds[k]))
    print('オッズ×アーカイブの重なり: %d レース' % sum(len(v) for v in groups.values()))
    for g, v in sorted(groups.items(), key=lambda x: -len(x[1])):
        print('  %-14s n=%d' % (g, len(v)))
    print()

    def bucket(rows, band):
        n = hit = 0; imp = ret = 0.0
        for r, om in rows:
            im = implied(om)
            p = sum(im.get(c, 0) for c in band)
            if not p: continue
            n += 1; imp += p
            if r['combo'] in band:
                hit += 1; ret += int(r['payout'])
        if not n: return None
        a, i = hit/n, imp/n
        se = math.sqrt(a*(1-a)/n) if 0 < a < 1 else 0
        return dict(n=n, hit=hit, act=a, imp=i, z=((i-a)/se if se else 0),
                    roi=ret/(n*len(band)*100))

    def show(gname, bands):
        rows = groups.get(gname, [])
        if not rows: return
        print('=== 2号艇=%s (n=%d) ===' % (gname, len(rows)))
        for bn in bands:
            s = bucket(rows, BANDS[bn])
            if s:
                print('  %-18s 的中%3d 実測%5.1f%% 含意%5.1f%% 差%+5.1fpt(z=%+.1f) ROI%6.1f%%'
                      % (bn, s['hit'], s['act']*100, s['imp']*100, (s['imp']-s['act'])*100, s['z'], s['roi']*100))

    show('差し巧者●', ('本線2-1-全(4点)', '本線+押さえ(6点)', '頭2(20点)'))
    show('壁弱●食う型', ('本線2-1-全(4点)', '本線+押さえ(6点)', '頭2(20点)'))
    show('壁弱●素通し型', ('3-1全+4-1全(8点)', '頭2(20点)', '頭1(20点)'))
    show('壁強●', ('頭1(20点)',))
    show('印なし', ('本線2-1-全(4点)', '頭2(20点)', '頭1(20点)'))
    print()
    print('読み方: 仕様書§4-4の方針バンドそのままの事前定義検証。差プラス=市場が過大評価。')

if __name__ == '__main__':
    main()
