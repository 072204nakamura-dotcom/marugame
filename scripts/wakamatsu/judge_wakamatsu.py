# -*- coding: utf-8 -*-
"""若松 レース判定モジュール（spec_wakamatsu.md §4 の参照実装・回帰テスト付き）

判定順序が仕様の一部：
  ① 進入固定フラグ（5R「進入固定戦隊」） → ② レース名（準優・予選特選・特別選抜・ドリーム・優勝）
  → ③ 3R格差戦（3R×1号艇B級×外に全国勝率1.5以上上の艇） → ④ 1号艇が出走表で勝率最上位
選手の型（スロー遅れ・壁弱）は daily_build_wm.py 側で加点する。
風・波は朝の時点で分からないので採点に入れない（直前ルールとして画面に出すだけ）。
変更時は必ず run_tests() を通すこと。
"""
import unicodedata

GAP_3R = -1.5      # 1号艇勝率 −（2〜6号艇の最高勝率）がこれ以下なら「格差」


def is_katame_name(name):
    """鉄板寄りのレース名か（NFKC後の部分一致）。
    Bファイルのレース名は8文字で切れるので「ドリー」で拾う（1stドリー・2ndドリー・ドリーム戦・ドリームEX）。"""
    if '準優' in name and '進出' not in name:
        return True
    for k in ('予選特選', '特別選抜', 'ドリー'):
        if k in name:
            return True
    if '優勝' in name:
        return True
    return False


def judge_wakamatsu_race(rname, race_no, fixed, grade1, gap1):
    """戻り値: (分類, 加点, フラグ)

    rname   : レース名（Bファイル表記のまま。中でNFKC正規化する）
    race_no : レース番号 1〜12
    fixed   : 進入固定なら True（見出し行に「進入固定」。若松は5R「進入固定戦隊」）
    grade1  : 1号艇の級 'A1'/'A2'/'B1'/'B2'（不明なら ''）
    gap1    : 1号艇の全国勝率 −（2〜6号艇の全国勝率の最大）。不明なら None
    """
    name = unicodedata.normalize('NFKC', rname or '')
    b1 = (grade1 or '').startswith('B')

    # ① 進入固定 ＝ 鉄板・穴買い禁止（レース名でなく見出しの「進入固定」で判定）
    if fixed or '進入固定' in name:
        return ('進入固定', 0.0, '鉄板・穴買い禁止')

    # ② レース名
    if is_katame_name(name):
        return ('特選系', 0.0, '鉄板寄り')

    pts, flags = 0.0, []

    # ③ 3R格差戦（主戦場）
    if race_no == 3 and b1 and gap1 is not None and gap1 <= GAP_3R:
        pts += 2.0
        flags.append('3R格差戦')

    # ④ 1号艇が出走表で勝率最上位（同率含む）
    if gap1 is not None and gap1 >= 0:
        pts -= 1.0
        flags.append('1号艇勝率最上位')

    return ('通常戦', pts, '・'.join(flags))


TESTS = [
    # (rname, rno, fixed, grade1, gap1) -> (cls, pts)
    (('進入固定戦隊', 5, True, 'A1', 0.5), ('進入固定', 0.0)),
    (('進入固定戦隊', 5, False, 'A1', 0.5), ('進入固定', 0.0)),     # 見出しフラグが取れなくても名前で拾う
    (('準優勝戦', 10, False, 'A1', 0.3), ('特選系', 0.0)),
    (('準優進出戦', 10, False, 'B1', -2.0), ('通常戦', 0.0)),       # 準優進出戦は通常戦（3Rでない）
    (('予選特選', 11, False, 'A1', 0.2), ('特選系', 0.0)),
    (('1stドリー', 12, False, 'A1', -0.2), ('特選系', 0.0)),
    (('ドリーム戦', 12, False, 'A1', 0.0), ('特選系', 0.0)),
    (('優勝戦', 12, False, 'A1', 0.1), ('特選系', 0.0)),
    (('MD優勝戦', 12, False, 'A1', 0.1), ('特選系', 0.0)),
    (('一般特選', 9, False, 'A2', -0.4), ('通常戦', 0.0)),          # 「特選」単独では拾わない
    (('エイトビート', 8, False, 'A1', 0.2), ('通常戦', -1.0)),      # 8Rは企画だが名前では鉄板にしない
    (('一般戦', 3, False, 'B1', -2.8), ('通常戦', 2.0)),            # 3R格差戦
    (('予選', 3, False, 'B1', -1.5), ('通常戦', 2.0)),              # 境界ちょうど
    (('予選', 3, False, 'B1', -1.4), ('通常戦', 0.0)),              # 格差不足
    (('予選', 3, False, 'A2', -2.0), ('通常戦', 0.0)),              # 1号艇A級は対象外
    (('予選', 4, False, 'B1', -2.5), ('通常戦', 0.0)),              # 3R以外は格差でも加点しない
    (('予選', 3, False, 'B1', None), ('通常戦', 0.0)),              # 情報欠損でも落ちない
    (('予選', 6, False, 'A1', 0.0), ('通常戦', -1.0)),              # 勝率最上位（同率）
    (('予選☆', 3, False, 'B1', -2.0), ('通常戦', 2.0)),            # ☆付きも同じ扱い
]


def run_tests():
    ok = 0
    for args, (ec, ep) in TESTS:
        c, p, fl = judge_wakamatsu_race(*args)
        good = (c == ec and abs(p - ep) < 1e-9)
        ok += good
        print(('OK ' if good else 'NG!'), args, '->', c, p, fl)
    print(f'{ok}/{len(TESTS)} passed')
    return ok == len(TESTS)


if __name__ == '__main__':
    assert run_tests()
