# -*- coding: utf-8 -*-
"""
EV検証スクリプト共通の小道具（人気順位まわり）

2026-09-19 の方針確定：3連単は50番人気までしか買わない（目安：オッズ約170倍まで）。
どのEV検証でも同じ付け方で人気順位を出すため、ここに集約する。
人気順位＝確定オッズの昇順（同オッズは組番の辞書順で先着）。1始まり。
"""

NINKI_MAX = 50      # これより後ろ（51番人気以降）は買わない


def ninki_rank(pairs):
    """[(combo, odds), ...] -> {combo: 人気順位}（オッズ昇順・同値はcombo順）"""
    lst = sorted(pairs, key=lambda x: (x[1], x[0]))
    return {c: i + 1 for i, (c, _o) in enumerate(lst)}


def ninki_rank_from_map(odds_map):
    """{combo: odds} -> {combo: 人気順位}"""
    return ninki_rank(list(odds_map.items()))


def race_ninki_rank(odds_by_key, race):
    """{(race, combo): odds} 形式から、その1レース分の {combo: 人気順位} を作る"""
    return ninki_rank([(c, o) for (r, c), o in odds_by_key.items() if r == race])


def within_ninki(rank, limit=NINKI_MAX):
    """人気順位が購入対象か（rank が None＝オッズ不明なら買わない扱い）"""
    return rank is not None and rank <= limit
