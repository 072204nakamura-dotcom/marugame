# -*- coding: utf-8 -*-
"""daily_build_wm.py の回帰テスト（ネットワーク不要）

実行:  python scripts/wakamatsu/test_daily_build_wm.py

ここが守っているのは「採点仕様を勝手に増減しない」こと（HANDOVER §2・spec §4）。
表の閾値や加点を触ったらこのテストが落ちます。落ちたら仕様書を確認してください。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_build_wm as d
from judge_wakamatsu import run_tests as judge_tests

FAILED = []


def check(name, cond, detail=''):
    print(('  OK  ' if cond else '  NG! ') + name + (('  << ' + detail) if (not cond and detail) else ''))
    if not cond:
        FAILED.append(name)


def first_regno(table, col, val, exclude=()):
    for k, row in table.items():
        if row.get(col) == val and k not in exclude:
            return k
    return None


def neutral_regno():
    """ST・壁・残しのどれにも印が付かない登番（表に無い番号）。"""
    return '0000'


def mkrace(rno, rname, regnos, grades, wins, fixed=False):
    boats = [dict(teiban=i + 1, regno=reg, name='選手%d' % (i + 1), grade=grades[i],
                  nat_win=wins[i], motor_no=None, motor2=None) for i, reg in enumerate(regnos)]
    r = dict(rno=rno, rname=rname, fixed=fixed, deadline='19:00', boats=boats)
    r['gap1'] = d.gap_of(boats)
    return r


def main():
    print('[1] 判定モジュール')
    check('judge_wakamatsu の回帰テスト', judge_tests())

    print('[2] 表の読込')
    check('ST表が読める', len(d.T_ST) > 1000, str(len(d.T_ST)))
    check('壁表が読める', len(d.T_WALL) > 300, str(len(d.T_WALL)))
    check('残し表が読める', len(d.T_ZAN) > 1000, str(len(d.T_ZAN)))
    check('全国1C表が読める', len(d.T_NAT1C) > 1000, str(len(d.T_NAT1C)))
    by_rno, kakusa = d.load_baselines()
    check('基礎率 12レース分', len([k for k, v in by_rno.items() if v and v['n'] >= 40]) == 11,
          str({k: v['n'] for k, v in by_rno.items()}))
    check('5Rは基礎率に入らない（進入固定戦隊）', 5 not in by_rno or by_rno[5]['n'] < 40)
    check('3R格差戦の基礎率 n≥100・イン<35%', kakusa and kakusa['n'] >= 100 and kakusa['in1'] < 35, str(kakusa))

    print('[3] 採点（spec §4）')
    N = neutral_regno()
    slow = first_regno(d.T_ST, 'スロー遅れ', '●')
    weak = first_regno(d.T_WALL, '壁', '壁弱●')
    strong = first_regno(d.T_WALL, '壁', '壁強●')
    check('表にスロー遅れ●・壁弱●・壁強●がいる', bool(slow and weak and strong))
    B6, A_OUT = ['B1'] * 6, ['B1', 'B1', 'B1', 'B1', 'A2', 'A1']

    r = mkrace(3, '一般戦', [N] * 6, A_OUT, [3.9, 5.3, 4.2, 3.8, 6.6, 6.7])
    sc = d.score_race(r)
    check('3R格差戦 = +2・穴の巣', sc[0] == 2.0 and d.label_for(sc[1], sc[0])[1] == '穴の巣', str(sc[:3]))

    r = mkrace(4, '一般戦', [N] * 6, A_OUT, [3.9, 5.3, 4.2, 3.8, 6.6, 6.7])
    check('4Rは同じ格差でも0点', d.score_race(r)[0] == 0.0)

    r = mkrace(3, '一般戦', [N] * 6, B6, [4.5, 5.0, 4.2, 3.8, 5.6, 5.0])
    check('3R格差1.1は0点', d.score_race(r)[0] == 0.0)

    r = mkrace(3, '一般戦', [slow] + [N] * 5, A_OUT, [3.9, 5.3, 4.2, 3.8, 6.6, 6.7])
    check('3R格差戦＋スロー遅れ● = +3', d.score_race(r)[0] == 3.0)

    r = mkrace(6, '予選', [N, weak, N, N, N, N], B6, [5.0, 5.5, 5, 5, 5, 5])
    sc = d.score_race(r)
    check('2号艇壁弱● = +1・崩れゾーン', sc[0] == 1.0 and d.label_for(sc[1], sc[0])[1] == '崩れゾーン', str(sc[:3]))

    r = mkrace(6, '予選', [N, strong, N, N, N, N], B6, [5.0, 5.5, 5, 5, 5, 5])
    check('2号艇壁強は表示のみ（0点）', d.score_race(r)[0] == 0.0)

    r = mkrace(9, '予選', [N] * 6, ['A1'] + ['B1'] * 5, [7.0, 5, 5, 5, 5, 5])
    sc = d.score_race(r)
    check('1号艇勝率最上位 = −1・鉄板寄り', sc[0] == -1.0 and d.label_for(sc[1], sc[0])[1] == '鉄板寄り')

    r = mkrace(5, '進入固定戦隊', [slow, weak, N, N, N, N], ['B1'] * 6, [3.0, 5, 5, 5, 6, 7], fixed=True)
    sc = d.score_race(r)
    check('進入固定は型があっても0点・鉄板・見送り', sc[0] == 0.0 and d.label_for(sc[1], sc[0])[1] == '鉄板・見送り')

    r = mkrace(11, '予選特選', [slow, weak, N, N, N, N], ['B1'] * 6, [3.0, 5, 5, 5, 6, 7])
    sc = d.score_race(r)
    check('予選特選は型があっても0点・鉄板寄り', sc[0] == 0.0 and d.label_for(sc[1], sc[0])[1] == '鉄板寄り')

    r = mkrace(9, '一般特選', [N] * 6, B6, [5.0, 5.5, 5, 5, 5, 5])
    sc = d.score_race(r)
    check('一般特選は通常戦（中立）', sc[1] == '通常戦' and d.label_for(sc[1], sc[0])[1] == '中立')

    r = mkrace(2, '一般戦', [N] * 6, B6, [5.0, 5.5, 5, 5, 5, 5])
    sc = d.score_race(r)
    pol = d.policy_for(sc[1], sc[2], sc[0], sc[4], sc[3])
    check('B級1号艇の方針に直前ルール（風5m・波5cm）', '風5m以上' in pol)

    print('[4] 実ファイル（fixtures/b261009_wm.txt：2026-10-09 第5日・最終日）')
    with open(os.path.join(HERE, 'fixtures', 'b261009_wm.txt'), encoding='shift_jis', errors='replace') as f:
        raw = f.read()
    parsed, by_rno, kakusa = d.build(raw)
    check('12レース読める', parsed and len(parsed['races']) == 12)
    check('第5日・最終日', parsed['day_n'] == 5 and parsed['is_final'])
    check('節タイトル', 'かっぱくん' in parsed['title'], parsed['title'])
    rs = {r['rno']: r for r in parsed['races']}
    check('5Rは進入固定', rs[5]['fixed'] and rs[5]['_sc'][1] == '進入固定')
    check('3R 格差 −2.82', abs(rs[3]['gap1'] + 2.82) < 1e-9, str(rs[3]['gap1']))
    check('3R は穴の巣（格差戦+2・スロー遅れ+1）', d.label_for(rs[3]['_sc'][1], rs[3]['_sc'][0])[1] == '穴の巣')
    check('優勝戦（この節は11R）は鉄板寄り', rs[11]['rname'] == '優勝戦' and rs[11]['_sc'][1] == '特選系')
    check('選抜戦A/Bは通常戦', rs[10]['_sc'][1] == '通常戦' and rs[12]['_sc'][1] == '通常戦')
    html = d.render_page(parsed, by_rno, kakusa)
    check('HTMLに会場ナビ（data-venue="wakamatsu"）', 'data-venue="wakamatsu"' in html)
    check('HTMLに直前ルールのバナー', '直前ルール' in html)
    check('HTMLに51番人気の注記', '51番人気' in html)
    check('非開催ページが作れる', '開催はありません' in d.render_page(None, by_rno, kakusa))

    print()
    if FAILED:
        print('FAILED:', len(FAILED), FAILED)
        sys.exit(1)
    print('ALL OK')


if __name__ == '__main__':
    main()
