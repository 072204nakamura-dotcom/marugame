# -*- coding: utf-8 -*-
"""daily_build_om.py の回帰テスト（ネットワーク不要）

実行:  python scripts/omura/test_daily_build_om.py

ここが守っているのは「採点仕様を勝手に増減しない」こと（HANDOVER §2・spec §4）。
表の閾値や加点を触ったらこのテストが落ちます。落ちたら仕様書を確認してください。
"""
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily_build_om as d
from judge_omura import run_tests as judge_tests

FAILED = []


def check(name, cond, detail=''):
    print(('  OK  ' if cond else '  NG! ') + name + (('  << ' + detail) if (not cond and detail) else ''))
    if not cond:
        FAILED.append(name)


def mkrace(rno, rname, regnos, fixed=False, grades=None, wins=None, rank1=None):
    """テスト用のレース（1〜6号艇に登番を並べる）。grades/wins は6要素のリスト。"""
    grades = grades or ['B1'] * 6
    wins = wins or [5.0] * 6
    r = dict(rno=rno, rname=rname, fixed=fixed, deadline='18:00',
             boats=[dict(teiban=i + 1, regno=reg, name='選手%d' % (i + 1), grade=grades[i],
                         nat_win=wins[i], motor_no=None, motor2=None)
                    for i, reg in enumerate(regnos)])
    if rank1 is None:
        rank1 = 1 + sum(1 for w in wins if w > wins[0])
    r['rank1'] = rank1
    return r


def neutral_regnos(n):
    """印のない（＝加点ゼロの）登番を表から探す"""
    out = []
    for reg in d.T_ST:
        st = d.T_ST.get(reg, {})
        v = d.fnum(st.get('採用スローST'))
        if v is None or v > 0.18 or v <= 0.13:
            continue
        if d.T_ZAN.get(reg, {}).get('型') or d.T_WALL.get(reg, {}).get('壁'):
            continue
        if d.T_SHIBORI.get(reg, {}).get('絞りまくり') == '●':
            continue
        out.append(reg)
        if len(out) >= n:
            break
    return out


def find(pred):
    for reg in d.T_ST:
        if pred(reg):
            return reg
    return None


NEU = neutral_regnos(6)
R_ST_LATE = find(lambda r: (d.fnum(d.T_ST[r].get('採用スローST')) or 0) > 0.18
                 and not d.T_ZAN.get(r, {}).get('型') and not d.T_WALL.get(r, {}).get('壁'))
R_ST_GOOD = find(lambda r: d.fnum(d.T_ST[r].get('採用スローST')) is not None
                 and d.fnum(d.T_ST[r].get('採用スローST')) <= 0.13
                 and not d.T_ZAN.get(r, {}).get('型') and not d.T_WALL.get(r, {}).get('壁'))
R_SUDOSHI = find(lambda r: d.T_WALL.get(r, {}).get('弱タイプ') == '素通し型'
                 and 0.13 < (d.fnum(d.T_ST[r].get('採用スローST')) or 0) <= 0.18)
R_KUU = find(lambda r: d.T_WALL.get(r, {}).get('弱タイプ') == '食う型'
             and 0.13 < (d.fnum(d.T_ST[r].get('採用スローST')) or 0) <= 0.18)
R_KABE = find(lambda r: d.T_WALL.get(r, {}).get('壁') == '壁強●'
              and 0.13 < (d.fnum(d.T_ST[r].get('採用スローST')) or 0) <= 0.18)
R_TOBU = find(lambda r: d.T_ZAN.get(r, {}).get('型') == '飛ぶ型'
              and 0.13 < (d.fnum(d.T_ST[r].get('採用スローST')) or 0) <= 0.18 and not d.T_WALL.get(r, {}).get('壁'))
R_SHIBORI = find(lambda r: d.T_SHIBORI.get(r, {}).get('絞りまくり') == '●')

A = ['A1'] + ['B1'] * 5
TOP = [7.0, 5.0, 5.0, 5.0, 5.0, 5.0]      # 1号艇が勝率1位
LOW = [4.0, 6.0, 6.0, 6.0, 5.0, 5.0]      # 1号艇が勝率4位


def sc(r, day_n=3, is_final=False):
    return d.score_race(r, day_n, is_final)[0]


def main():
    print('=== 1. 判定モジュール（spec §4 判定順序） ===')
    check('judge_omura 18/18', judge_tests())

    print('=== 2. 中立レースの土台 ===')
    check('中立な登番を6人確保できた', len(NEU) == 6, '見つかった数=%d' % len(NEU))
    check('検体の登番が揃った', all([R_ST_LATE, R_ST_GOOD, R_SUDOSHI, R_KUU, R_KABE, R_TOBU]),
          str([R_ST_LATE, R_ST_GOOD, R_SUDOSHI, R_KUU, R_KABE, R_TOBU]))
    base = sc(mkrace(4, '予選', NEU, wins=[5.0, 5.0, 5.0, 5.0, 5.0, 5.0]))
    check('中日4R・全員無印・勝率同率（1位扱い）B級 → 0点', base == 0, '実際=%g' % base)

    print('=== 3. 日程・番組シグナル ===')
    check('初日3R・無印 → +2', sc(mkrace(3, '予選', NEU), day_n=1) == 2.0)
    check('初日7R → 初日点なし', sc(mkrace(7, '予選', NEU), day_n=1) == 0.0)
    check('初日3R×勝率4位以下 → +3（穴の巣）', sc(mkrace(3, '予選', NEU, wins=LOW), day_n=1) == 3.0)
    check('初日3R×勝率1位A級 → +1', sc(mkrace(3, '予選', NEU, grades=A, wins=TOP), day_n=1) == 1.0)
    check('7R進入固定 → 0点・分類=進入固定', d.score_race(mkrace(7, '予選', NEU, fixed=True, wins=LOW), 1, False)[1] == '進入固定'
          and sc(mkrace(7, '予選', NEU, fixed=True, wins=LOW), day_n=1) == 0.0)
    check('最終日4R×A級 → −1（1位でなくても）', sc(mkrace(4, '一般', NEU, grades=A, wins=[5.5, 6.0, 5.0, 5.0, 5.0, 5.0]), day_n=6, is_final=True) == -1.0)
    check('最終日4R×A級×勝率1位 → −2', sc(mkrace(4, '一般', NEU, grades=A, wins=TOP), day_n=6, is_final=True) == -2.0)
    check('最終日9R×A級 → 最終日点なし', sc(mkrace(9, '一般', NEU, grades=A, wins=[5.5, 6.0, 5.0, 5.0, 5.0, 5.0]), day_n=6, is_final=True) == 0.0)
    check('最終日4R×B級 → 0', sc(mkrace(4, '一般', NEU, wins=[5.5, 6.0, 5.0, 5.0, 5.0, 5.0]), day_n=6, is_final=True) == 0.0)
    check('準優勝戦 → 0点・鉄板寄り', d.score_race(mkrace(10, '準優勝戦', NEU, wins=LOW), 5, False)[1] == '準優勝戦')
    check('予選特選 → 特選系', d.score_race(mkrace(11, '予選特選', NEU, wins=LOW), 3, False)[1] == '特選系')
    check('一般特選 → 通常戦（拾わない）', d.score_race(mkrace(9, '一般特選', NEU, wins=LOW), 3, False)[1] == '通常戦')
    check('優勝戦 → 優勝戦・0点', d.score_race(mkrace(12, '優勝戦', NEU, wins=LOW), 6, True)[1] == '優勝戦')
    check('2日目2R×B級 → +0.5', sc(mkrace(2, '予選', NEU, wins=[5.0] * 6), day_n=2) == 0.5)
    check('2日目2R×A級（勝率2位） → 0', sc(mkrace(2, '予選', NEU, grades=A, wins=[5.0, 6.0, 5.0, 5.0, 5.0, 5.0]), day_n=2) == 0.0)

    print('=== 4. 選手の型（表から） ===')
    same = [5.0] * 6
    check('1号艇スロー遅れ● → +1', sc(mkrace(4, '予選', [R_ST_LATE] + NEU[1:], wins=same)) == 1.0)
    check('1号艇スロー巧者● → −1', sc(mkrace(4, '予選', [R_ST_GOOD] + NEU[1:], wins=same)) == -1.0)
    check('2号艇壁弱●(素通し) → +1', sc(mkrace(4, '予選', [NEU[0], R_SUDOSHI] + NEU[2:], wins=same)) == 1.0)
    check('2号艇壁弱●(食う型) → +1', sc(mkrace(4, '予選', [NEU[0], R_KUU] + NEU[2:], wins=same)) == 1.0)
    check('2号艇壁強● → −1', sc(mkrace(4, '予選', [NEU[0], R_KABE] + NEU[2:], wins=same)) == -1.0)
    check('1号艇飛ぶ型 → 加点なし（フォーム分岐のみ）', sc(mkrace(4, '予選', [R_TOBU] + NEU[1:], wins=same)) == 0.0
          and d.score_race(mkrace(4, '予選', [R_TOBU] + NEU[1:], wins=same), 3, False)[5]['zan1'] == '飛ぶ型')
    if R_SHIBORI:
        check('3号艇絞りまくり● → +0.5', sc(mkrace(4, '予選', NEU[:2] + [R_SHIBORI] + NEU[3:], wins=same)) == 0.5)
        check('3・4号艇とも絞りまくり● → 1回だけ+0.5', sc(mkrace(4, '予選', NEU[:2] + [R_SHIBORI, R_SHIBORI] + NEU[4:], wins=same)) == 0.5)
    check('重ね掛け：初日3R×4位以下×1号艇遅れ×2号艇壁弱 → +5',
          sc(mkrace(3, '予選', [R_ST_LATE, R_SUDOSHI] + NEU[2:], wins=LOW), day_n=1) == 5.0)

    print('=== 5. ラベル・方針 ===')
    check('ラベル 3.0→穴の巣', d.label_for('通常戦', '', 3.0)[1] == '穴の巣')
    check('ラベル 2.0→崩れゾーン', d.label_for('通常戦', '', 2.0)[1] == '崩れゾーン')
    check('ラベル 1.0→要注意', d.label_for('通常戦', '', 1.0)[1] == '要注意')
    check('ラベル 0→中立', d.label_for('通常戦', '', 0.0)[1] == '中立')
    check('ラベル −1→鉄板寄り', d.label_for('通常戦', '', -1.0)[1] == '鉄板寄り')
    check('ラベル 進入固定→鉄板・見送り', d.label_for('進入固定', '', 0.0)[1] == '鉄板・見送り')
    p = d.policy_for('通常戦', '', 2.0, dict(zan1='', c2type='素通し型'), [])
    check('素通し型の方針は3-1/4-1で2号艇消し', '3-1-全' in p and '2号艇は消し' in p)
    p = d.policy_for('通常戦', '', 0.0, dict(zan1='', c2type=''), [])
    check('中立の方針は中穴フォーム（1-4/5/6）', '1-4-全' in p)
    p = d.policy_for('通常戦', '', 2.0, dict(zan1='飛ぶ型', c2type=''), [])
    check('飛ぶ型はX-1-Yを外す', 'X-1-Y を外し' in p)

    print('=== 6. パーサ（進入固定・最終日・勝率順位） ===')
    sample = (
        '\r\nボートレース大　村   　９月１９日  テスト杯  第　１日\r\n\r\n   ＊＊＊　番組表　＊＊＊\r\n\r\n'
        '          テスト杯　　\r\n\r\n   第　１日          ２０２５年　９月１９日   ボートレース大　村\r\n\r\n'
        '　７Ｒ  予選　　　　  進入固定       Ｈ１８００ｍ  電話投票締切予定１８：１３ \r\n'
        '-----\r\n'
        '1 4001選手一郎30福岡52A1 6.50 40.00 6.00 40.00 38 28.85 54 38.00              8\r\n'
        '2 4002選手二郎30福岡52B1 5.00 30.00 5.00 30.00 14 28.33 29 33.93             11\r\n'
        '3 4003選手三郎30福岡52B1 4.00 30.00 5.00 30.00 76 26.42 39 28.57             10\r\n'
        '4 4004選手四郎30福岡52B1 4.00 30.00 5.00 30.00 49 32.00 34 30.00              9\r\n'
        '5 4005選手五郎30福岡52B2 3.00 30.00 5.00 30.00 28 35.59 76 35.19              7\r\n'
        '6 4006選手六郎30福岡52B1 3.00 30.00 5.00 30.00 41 19.30 73 28.33              6\r\n'
        '　１２Ｒ  優勝戦　　　          Ｈ１８００ｍ  電話投票締切予定２０：４５ \r\n'
        '-----\r\n'
        '1 4011選手甲一30福岡52A1 5.00 40.00 6.00 40.00 38 28.85 54 38.00              8\r\n'
        '2 4012選手乙二30福岡52A1 7.00 30.00 5.00 30.00 14 28.33 29 33.93             11\r\n'
        '3 4013選手丙三30福岡52A1 7.50 30.00 5.00 30.00 76 26.42 39 28.57             10\r\n'
        '4 4014選手丁四30福岡52A1 6.00 30.00 5.00 30.00 49 32.00 34 30.00              9\r\n'
        '5 4015選手戊五30福岡52A2 4.00 30.00 5.00 30.00 28 35.59 76 35.19              7\r\n'
        '6 4016選手己六30福岡52B1 3.00 30.00 5.00 30.00 41 19.30 73 28.33              6\r\n')
    raw = '24BBGN' + sample + '24BEND'
    p = d.parse_omura(raw)
    check('パース成功・2レース', p is not None and len(p['races']) == 2)
    if p:
        r7, r12 = p['races']
        check('7Rの進入固定フラグ', r7['fixed'] is True and r7['rname'] == '予選')
        check('12Rは進入固定でない', r12['fixed'] is False)
        check('優勝戦があるので最終日', p['is_final'] is True)
        check('日目=1・タイトル=テスト杯', p['day_n'] == 1 and p['title'] == 'テスト杯', repr((p['day_n'], p['title'])))
        check('7R 1号艇は勝率1位', r7['rank1'] == 1)
        check('12R 1号艇は勝率4位', r12['rank1'] == 4)
        check('締切時刻', r7['deadline'] == '18:13' and r12['deadline'] == '20:45')
        check('モーター番号・2率', r7['boats'][0]['motor_no'] == '38' and abs(r7['boats'][0]['motor2'] - 28.85) < 1e-9)
    check('大村ブロックなし → None', d.parse_omura('04BBGN' + sample + '04BEND') is None)

    print()
    if FAILED:
        print('FAILED:', len(FAILED), FAILED)
        sys.exit(1)
    print('ALL OK')


if __name__ == '__main__':
    main()
