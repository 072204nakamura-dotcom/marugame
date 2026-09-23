# -*- coding: utf-8 -*-
"""大村 レース判定モジュール（spec_omura.md §4 の参照実装・回帰テスト付き）

判定順序が仕様の一部：
  ① 進入固定フラグ → ② レース名（準優・予選特選・特別選抜・優勝） → ③ 日程（初日／最終日）
  → ④ 1号艇の相対地力（出走表内 勝率順位・級）
選手の型（⑤）は daily_build_om.py 側で加点する。
変更時は必ず run_tests() を通すこと。
"""
import unicodedata


def judge_omura_race(rname, race_no, fixed, day_n, is_final, rank1, grade1):
    """戻り値: (分類, 加点, フラグ, フォーム)

    rname   : レース名（Bファイル表記のまま。中でNFKC正規化する）
    race_no : レース番号 1〜12
    fixed   : 進入固定なら True
    day_n   : 開催日目（不明なら None）
    is_final: 本日が最終日（＝本日のBファイルに「優勝戦」がある）なら True
    rank1   : 1号艇の出走表内 全国勝率順位（1〜6・不明なら None）
    grade1  : 1号艇の級 'A1'/'A2'/'B1'/'B2'（不明なら ''）
    """
    name = unicodedata.normalize('NFKC', rname or '')
    a1 = (grade1 or '').startswith('A')

    # ① 進入固定 ＝ 鉄板・穴買い禁止（レース番号は見ない）
    if fixed:
        return ('進入固定', 0.0, '鉄板・穴買い禁止', '見送り推奨')

    # ② レース名
    if '準優' in name:
        return ('準優勝戦', 0.0, '鉄板寄り', '1アタマ・中穴は1-4/5/6の2着流し')
    if '予選特選' in name or '特別選抜' in name:
        return ('特選系', 0.0, '鉄板寄り', '1アタマ・中穴は1-4/5/6の2着流し')
    if '優勝' in name:
        return ('優勝戦', 0.0, '', '中立（6人全員強豪＝相対地力が消える）')

    pts, flags = 0.0, []
    cls = '通常戦'

    # ③ 日程
    if day_n == 1 and race_no <= 6:
        pts += 2.0; flags.append('初日前半')            # 主戦場（−13.8pt z=−4.33）
    elif day_n == 2 and race_no <= 6 and not a1:
        pts += 0.5; flags.append('2日目前半(参考)')       # 暫定（監視）
    if is_final and race_no <= 8 and a1:
        pts -= 1.0; flags.append('最終日A級')             # 鉄板寄り（+15.8pt）

    # ④ 1号艇の相対地力
    if rank1 is not None and rank1 >= 4:
        pts += 1.0; flags.append('1号艇勝率4位以下')
    elif rank1 == 1 and a1:
        pts -= 1.0; flags.append('1号艇勝率1位A級')

    form = '均等型：2-1-全／3-1-全＋4-1-2/4-1-3' if pts >= 2.0 else '中穴：1-4/5/6の2着流し'
    flag = '・'.join(flags)
    return (cls, pts, flag, form)


TESTS = [
    # (rname, rno, fixed, day_n, final, rank1, grade1) -> (cls, pts)
    (('予選', 7, True, 3, False, 1, 'A1'), ('進入固定', 0.0)),
    (('予選', 1, True, 1, False, 6, 'B1'), ('進入固定', 0.0)),         # 全日固定の日は初日でも加点しない
    (('準優勝戦', 10, False, 5, False, 1, 'A1'), ('準優勝戦', 0.0)),
    (('予選特選', 11, False, 3, False, 1, 'A1'), ('特選系', 0.0)),
    (('特別選抜戦Ａ', 12, False, 6, True, 1, 'A1'), ('特選系', 0.0)),
    (('一般特選', 9, False, 4, False, 2, 'A2'), ('通常戦', 0.0)),      # 「特選」単独では拾わない
    (('優勝戦', 12, False, 6, True, 1, 'A1'), ('優勝戦', 0.0)),
    (('予選', 3, False, 1, False, 2, 'A2'), ('通常戦', 2.0)),          # 初日前半
    (('予選', 3, False, 1, False, 5, 'B1'), ('通常戦', 3.0)),          # 初日前半×勝率4位以下＝穴の巣
    (('予選', 3, False, 1, False, 1, 'A1'), ('通常戦', 1.0)),          # 初日前半でも1位A級なら−1
    (('予選', 7, False, 1, False, 5, 'B1'), ('通常戦', 1.0)),          # 初日でも7Rは初日点なし
    (('予選', 2, False, 2, False, 5, 'B1'), ('通常戦', 1.5)),          # 2日目前半B級 0.5 + 4位以下 1
    (('予選', 2, False, 2, False, 5, 'A2'), ('通常戦', 1.0)),          # 2日目前半はB級のみ
    (('一般', 4, False, 6, True, 1, 'A1'), ('通常戦', -2.0)),          # 最終日A級 −1 ＋ 1位A級 −1
    (('一般', 4, False, 6, True, 5, 'B1'), ('通常戦', 1.0)),           # 最終日でもB級は効かない
    (('一般', 9, False, 6, True, 1, 'A1'), ('通常戦', -1.0)),          # 最終日点は1〜8Rのみ
    (('予選', 5, False, 3, False, 3, 'B1'), ('通常戦', 0.0)),          # 中日・3位 → 0
    (('予選', 5, False, 3, False, None, ''), ('通常戦', 0.0)),         # 情報欠損でも落ちない
]


def run_tests():
    ok = 0
    for args, (ec, ep) in TESTS:
        c, p, fl, fm = judge_omura_race(*args)
        good = (c == ec and abs(p - ep) < 1e-9)
        ok += good
        print(('OK ' if good else 'NG!'), args, '->', c, p, fl)
    print(f'{ok}/{len(TESTS)} passed')
    return ok == len(TESTS)


if __name__ == '__main__':
    assert run_tests()
