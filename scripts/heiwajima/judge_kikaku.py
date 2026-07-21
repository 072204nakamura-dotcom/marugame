# -*- coding: utf-8 -*-
"""平和島 企画レース判定モジュール（spec_kikaku.md の参照実装・回帰テスト11/11通過済み）
判定順序が仕様の一部。変更時は必ず run_tests() を通すこと。"""
import unicodedata

def judge_heiwajima_race(rname, race_no):
    """戻り値: (分類, 加点, フラグ, フォーム)"""
    name = unicodedata.normalize('NFKC', rname or '')
    if 'ベイラン' in name:
        return ('東京ベイランチ', 0, '鉄板・穴買い禁止', '見送り推奨')
    if 'ベイブレ' in name:
        return ('ベイブレイク', 1.0, 'カド攻め', '4まくり(4-1/4-流し)')
    if '準優' in name:
        return ('準優勝戦', 0, '', '中立')
    if '優勝' in name:
        return ('優勝戦', 0, '鉄板寄り', '1アタマ・見送り寄り')
    if '記者選抜' in name:
        return ('記者選抜', 0, '', '中立')
    if '選抜' in name:
        return ('選抜系', 0.5, '暫定・隠れ穴', '差し水面フォーム')
    if race_no == 7:
        return ('通常戦', 2.0, '主戦場', '差し水面フォーム(2C/3Cアタマ-1残し)')
    if race_no == 3:
        return ('通常戦', 1.0, '準主戦場', '差し水面フォーム(2C/3Cアタマ-1残し)')
    if race_no in (1, 6):
        return ('通常戦', 0.5, '参考', '差し水面フォーム')
    return ('通常戦', 0, '', '中立')

TESTS = [
    ('東京ベイラン', 2, '東京ベイランチ', 0),
    ('東京ベイラン', 5, '東京ベイランチ', 0),
    ('ベイブレイク', 8, 'ベイブレイク', 1.0),
    ('準優勝戦', 12, '準優勝戦', 0),
    ('優勝戦', 12, '優勝戦', 0),
    ('東京ベイ選抜', 11, '選抜系', 0.5),
    ('東京ベイＤＲ', 12, '通常戦', 0),
    ('予選', 7, '通常戦', 2.0),
    ('予選', 3, '通常戦', 1.0),
    ('一般', 5, '通常戦', 0),
    ('予選特賞', 9, '通常戦', 0),
]

def run_tests():
    ok = 0
    for nm, rc, ec, ep in TESTS:
        c, p, fl, fm = judge_heiwajima_race(nm, rc)
        good = (c == ec and p == ep)
        ok += good
        print(('OK ' if good else 'NG!'), nm, rc, '->', c, p)
    print(f'{ok}/{len(TESTS)} passed')
    return ok == len(TESTS)

if __name__ == '__main__':
    assert run_tests()
