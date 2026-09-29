# -*- coding: utf-8 -*-
"""買い目シグナル — 回帰テスト（ネット不要）

tests/fixtures/ の公式ページ保存HTMLと番組表で、オッズの並び・結果の読み取り・
KIR-A の買い目・最終日判定・候補判定が変わっていないことを確かめる。
Actions では build_targets.py の前に実行し、落ちたら候補を作らない。
"""
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FIX = os.path.abspath(os.path.join(HERE, '..', '..', 'tests', 'fixtures'))

from judge import parse_odds3t, parse_odds2tf, parse_odds3f, parse_wind, parse_result, build_bets, settle_bets  # noqa: E402
from build_targets import build, parse_venue, race_features  # noqa: E402
from rules import match_rules  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print(('OK  ' if ok else 'NG  ') + name + ('' if ok else '  got=%r want=%r' % (got, want)))
    if not ok:
        fails.append(name)


def read(name):
    with open(os.path.join(FIX, name), encoding='utf-8') as f:
        return f.read()


# 1〜4. オッズの並び・結果ページ（2026-09-20 桐生2R）
o3t = parse_odds3t(read('odds3t_01_20260920_2R.html'))
check('3連単 5-2-3', o3t['5-2-3'], 328.2)
t2, f2 = parse_odds2tf(read('odds2tf_01_20260920_2R.html'))
check('2連単 5-2', t2['5-2'], 81.4)
check('2連複 2-5', f2['2-5'], 53.8)
o3f = parse_odds3f(read('odds3f_01_20260920_2R.html'))
check('3連複 2-3-5', o3f['2-3-5'], 25.3)
res = parse_result(read('raceresult_01_20260920_2R.html'))
check('結果 3連単', res['3連単'], [('5-2-3', 32820)])
check('直前情報 風速', parse_wind(read('beforeinfo_01_20260920_2R.html'))[0], 2)

# 5. KIR-A の買い目（過去の実例・確定オッズで再現）
KIR_A = [
    ('odds3t_01_20260206_5R.html', ['2-1-4', '2-1-5', '2-1-6', '6-1-4'], [70.3, 76.7, 58.8, 43.0], '2-1-5', 7670),
    ('odds3t_01_20260308_2R.html', ['2-1-6', '3-1-2', '3-1-4'], [40.9, 52.3, 75.9], '3-1-2', 5230),
    ('odds3t_01_20260310_5R.html', ['2-1-5', '3-1-5'], [65.9, 57.1], '3-1-5', 5710),
]
for fn, combos, odds, win, pay in KIR_A:
    bets = build_bets('3t_X1Y_40_80_pop50', {}, odds3t=parse_odds3t(read(fn)))
    check('KIR-A ' + fn, ([b['combo'] for b in bets], [b['odds'] for b in bets]), (combos, odds))
    fake = {'3連単': [(win, pay)], '3連複': [], '2連単': [], 'henkan': [], 'cancelled': False}
    check('KIR-A 的中 ' + fn, settle_bets('3t_X1Y_40_80_pop50', bets, fake), (pay, [win]))

# 6. 最終日判定（2026-09-20 初日＝非最終、同節 9/25 優勝戦の日＝最終）
b0920 = read('b_01_20260920.txt')
b0925 = read('b_01_20260925.txt')
check('9/20 桐生 非最終', parse_venue(b0920, '01')[0], False)
check('9/25 桐生 最終', parse_venue(b0925, '01')[0], True)
check('9/20 1R 締切', parse_venue(b0920, '01')[1][0]['deadline'], '15:26')
check('9/20 1R 勝率', parse_venue(b0920, '01')[1][0]['wins'][1], 3.92)

# 7. 候補判定
sep = build(b0920, datetime(2026, 9, 20))
check('9月の桐生は KIR なし', [r for r in sep if any(x.startswith('KIR') for x in r['rules'])], [])
octo = build(b0920, datetime(2026, 10, 20))
check('10月なら桐生1〜5Rに KIR-A/B/C', [(r['race'], r['rules']) for r in octo],
      [(n, ['KIR-A', 'KIR-B', 'KIR-C']) for n in range(1, 6)])
check('最終日は KIR が付かない', build(b0925, datetime(2026, 10, 25)), [])
for m in (4, 9, 12):
    check('芦屋 ASH-Q 季節不問 %d月' % m, match_rules('21', m, False, 3, 4, None), ['ASH-Q'])
    check('丸亀 MAR-E 季節・R・日程不問 %d月' % m, match_rules('15', m, True, 11, 5, None), ['MAR-E'])
    check('若松 W1-Q 季節不問 %d月' % m, 'W1-Q' in match_rules('20', m, True, 12, 6, 1.0), True)
check('芦屋 1号艇3位は外れ', match_rules('21', 5, False, 3, 3, None), [])
check('W1-Q 差0.9は外れ', match_rules('09', 5, False, 3, 6, 0.9), [])
check('FUK-B R不問', match_rules('22', 1, False, 11, 4, None), ['FUK-B'])

# 特徴量（同率は上位扱い・外上位3艇は同率なら若番）
f = race_features({1: 5.0, 2: 6.0, 3: 5.0, 4: 6.0, 5: 4.0, 6: 3.0})
check('rank1 同率は上位扱い', f['rank1'], 3)
check('外上位3艇 同率は若番', f['outer_top3'], [2, 4, 3])
check('単独最下位の差', race_features({1: 3.0, 2: 4.5, 3: 5, 4: 6, 5: 7, 6: 4.2})['weakest_is_boat1_gap'], 1.2)
check('同率最下位は null', race_features({1: 3.0, 2: 3.0, 3: 5, 4: 6, 5: 7, 6: 4.2})['weakest_is_boat1_gap'], None)

# 買い目の形
race = {'outer_top3': [6, 3, 2]}
check('MAR-E BOX 6点', [b['combo'] for b in build_bets('2t_outer_top3_box', race, odds2t=t2)],
      ['6-3', '6-2', '3-6', '3-2', '2-6', '2-3'])
check('ASH-Q 1点', [b['combo'] for b in build_bets('3f_outer_top3', race, odds3f=o3f)], ['2-3-6'])
check('W1-Q 10点', len(build_bets('3f_1XY_all', race, odds3f=o3f)), 10)
check('WAK-C 20点', len(build_bets('3t_X1Y_all', race, odds3t=o3t)), 20)
check('KIR-B 5点', [b['combo'] for b in build_bets('2t_X1', race, odds2t=t2)], ['2-1', '3-1', '4-1', '5-1', '6-1'])

print()
if fails:
    print('FAILED: %d件' % len(fails))
    sys.exit(1)
print('ALL OK')
