# -*- coding: utf-8 -*-
"""戸田(02) EV検証 — まくり屋カド時の買い目は市場にどこまで織り込まれているか

仕様書§8 検証キュー筆頭：「まくり屋カド時の『4-6』『4-5』のオッズが実確率をどこまで織り込むか」
仕様書§2-②の注意：まくり屋カド時の万舟率は14.9%と全体17.6%より低い＝市場も「まくり屋がカドなら4」を
見ている。単体はROI改善でなく確率土台、という前提を実オッズで検証する。

判定フラグ（アプリ実装と同じ定義）:
  まくり屋カド … 4号艇の選手の 実4コースまくり率>=20% かつ 全国4コース10走以上（仕様書§2-②）
  カド消し     … 4号艇のまくり力 <= -4
  6残す        … 6号艇の残し残差 >= +6
  ※表は直近365日の全国成績から毎朝再生成される＝検証対象レースの結果を含む「インサンプル」判定。
    仕様書の検証値（61.2%）も同条件。将来の運用は前向きだが、ここでは市場との比較が目的なので許容。

測るもの（バンドごと）:
  実測的中率 ／ 市場含意（1/オッズを120通りで正規化した確率の合計）／ 等額買い回収率
  同じバンドを「まくり屋でない日」にも当てて対照とする。

実行: python scripts/toda/ev_makuriya.py
"""
import os
import csv
import math
from collections import defaultdict

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
D = os.path.join(REPO, 'data', 'toda')
ODDS_DIR = os.path.join(REPO, 'data', 'odds', '02')

MAKURIYA_RATE, MAKURIYA_MIN_N, KADOKESHI_TH, NOKOSHI_TH = 20.0, 10, -4.0, 6.0

BANDS = {
    '4頭(20点)':        [f'4-{a}-{b}' for a in '12356' for b in '12356' if a != b],
    '4-5-x(4点)':       [f'4-5-{x}' for x in '1236'],
    '4-6-x(4点)':       [f'4-6-{x}' for x in '1235'],
    '4-1-x(4点)':       [f'4-1-{x}' for x in '2356'],
    '4-3-x(4点)':       [f'4-3-{x}' for x in '1256'],
    '方針:4-5/4-1/4-3(12点)': [f'4-{a}-{b}' for a in '513' for b in '12356' if a != b],
    '方針:4-6/4-5/4-1(12点)': [f'4-{a}-{b}' for a in '651' for b in '12356' if a != b],
}


def load(path, bom=False):
    with open(path, encoding='utf-8-sig' if bom else 'utf-8') as f:
        return list(csv.DictReader(f))


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
    t = sum(inv.values())
    return {c: v / t for c, v in inv.items()} if t else {}


def main():
    odds = load_odds()
    races = {(r['date'], r['rno']): r for r in load(os.path.join(D, 'toda_races.csv'))
             if r['santan'] and r['payout']}
    ents = defaultdict(dict)
    for e in load(os.path.join(D, 'toda_entries.csv')):
        ents[(e['date'], e['rno'])][e['teiban']] = e['touban']
    mak = {r['登番']: r for r in load(os.path.join(D, 'toda_makuriya.csv'), bom=True)}
    nok = {r['登番']: float(r['残し残差']) for r in load(os.path.join(D, 'toda_nokoshi6.csv'), bom=True)}

    def is_makuriya(tb):
        m = mak.get(tb)
        return bool(m) and float(m['実4まくり率']) >= MAKURIYA_RATE and int(m['全国4走']) >= MAKURIYA_MIN_N

    def is_keshi(tb):
        m = mak.get(tb)
        return bool(m) and float(m['まくり力']) <= KADOKESHI_TH

    groups = defaultdict(list)
    for key, r in races.items():
        if key not in odds or key not in ents:
            continue
        b4, b6 = ents[key].get('4'), ents[key].get('6')
        if not b4:
            continue
        item = (r, odds[key])
        if is_makuriya(b4):
            groups['まくり屋カド'].append(item)
            if b6 and nok.get(b6, 0) >= NOKOSHI_TH:
                groups['二枚重ね(まくり屋×6残す)'].append(item)
        elif is_keshi(b4):
            groups['カド消し'].append(item)
        else:
            groups['対照(4号艇が無印)'].append(item)

    print('オッズ保存日数 %d / JOINできたレース %d' % (len({d for d, _ in odds}), sum(len(v) for v in groups.values())))
    for g in ('まくり屋カド', '対照(4号艇が無印)', 'カド消し'):
        print('  %-18s n=%d' % (g, len(groups[g])))
    print('  %-18s n=%d' % ('二枚重ね', len(groups['二枚重ね(まくり屋×6残す)'])))
    print()

    def bucket(rows, band):
        n = hit = 0
        imp = ret = 0.0
        for r, om in rows:
            im = implied(om)
            p = sum(im.get(c, 0) for c in band)
            if not p:
                continue
            n += 1
            imp += p
            if r['santan'] in band:
                hit += 1
                ret += int(r['payout'])
        if not n:
            return None
        a, i = hit / n, imp / n
        se = math.sqrt(a * (1 - a) / n) if 0 < a < 1 else 0
        return dict(n=n, hit=hit, act=a, imp=i, z=((i - a) / se if se else 0),
                    roi=ret / (n * len(band) * 100))

    print('=== 4号艇の頭（仕様書§2-②: まくり屋カドで4コース勝率 13.4%→30.1%） ===')
    for g in ('まくり屋カド', '対照(4号艇が無印)', 'カド消し'):
        s = bucket(groups[g], BANDS['4頭(20点)'])
        if s:
            print('  %-18s n=%4d 実測%5.1f%% 市場含意%5.1f%% 差%+5.1fpt (z=%+.1f) 等額買い回収%6.1f%%'
                  % (g, s['n'], s['act'] * 100, s['imp'] * 100, (s['imp'] - s['act']) * 100, s['z'], s['roi'] * 100))
    print()
    print('=== まくり屋カド時の買い目バンド（仕様書§4-2: 4コースまくり時の2着は5コース26%） ===')
    print('  %-24s %5s %4s %7s %7s %8s %8s' % ('バンド', 'n', '的中', '実測', '含意', '回収率', '対照回収'))
    for name, band in BANDS.items():
        if name.startswith('4頭'):
            continue
        s = bucket(groups['まくり屋カド'], band)
        c = bucket(groups['対照(4号艇が無印)'], band)
        if s:
            print('  %-24s %5d %4d %6.1f%% %6.1f%% %7.1f%% %7.1f%%'
                  % (name, s['n'], s['hit'], s['act'] * 100, s['imp'] * 100, s['roi'] * 100, (c['roi'] * 100) if c else 0))
    print()
    print('=== 二枚重ね（仕様書§5-3: n=11で保留。本線4-6-x/4-5-x/4-1-x） ===')
    for name in ('4-6-x(4点)', '方針:4-6/4-5/4-1(12点)'):
        s = bucket(groups['二枚重ね(まくり屋×6残す)'], BANDS[name])
        if s:
            print('  %-24s n=%3d 的中%2d 実測%5.1f%% 含意%5.1f%% 回収%6.1f%%'
                  % (name, s['n'], s['hit'], s['act'] * 100, s['imp'] * 100, s['roi'] * 100))
    print()
    print('読み方: 差プラス＝市場がその出目を過大評価（買うと分が悪い）／マイナス＝軽視。')
    print('        回収率100%超が実利の目安。対照回収と比べて「まくり屋カド」の日だけ良いかを見る。')


if __name__ == '__main__':
    main()
