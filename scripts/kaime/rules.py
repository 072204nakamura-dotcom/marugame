# -*- coding: utf-8 -*-
"""買い目シグナル — ルール表（正本：実装指示書 §3）

★ 条件・数値は変えないこと。変えると過去3年（2023/10〜2026/9）の検証が無意味になる。
  ルールを増やすときは、この表に1行足し、検証の数字と出典（仕様書の節）を必ず書く。
  gas/kaime/Code.gs の RULES も同じ内容に揃えること。

各キー
  venues  … 対象の場コード
  winter  … True なら 10〜3月だけ
  nonfinal… True なら最終日（優勝戦がある日）を除く
  r_max   … 1〜r_max R だけ（None＝R不問）
  rank1_min … 1号艇の出走表内勝率順位がこの値以上（None＝不問）
  weakest_gap … 1号艇が全国勝率で最下位かつ5番目との差がこの値以上（None＝不問）
  wind    … True なら直前情報の風速5m以上（GASで判定）
  bet     … 券種・買い目の作り方（GASで組み立て）
  rank    … ◎本命 / △参考 / ×監視
"""

RULES = [
    dict(id='KIR-A', rank='◎', venues=['01'], winter=True, nonfinal=True, r_max=5,
         rank1_min=None, weakest_gap=None, wind=True,
         bet='3t_X1Y_40_80_pop50', label='3連単 X-1-Y（40〜80倍・50番人気まで）',
         verify='142.8%（126/138/162）。公平見積り107%'),
    dict(id='KIR-B', rank='◎', venues=['01'], winter=True, nonfinal=True, r_max=5,
         rank1_min=None, weakest_gap=None, wind=True,
         bet='2t_X1', label='2連単 X-1（5点）',
         verify='115.4%（161/88/110）。公平見積り104%'),
    dict(id='KIR-C', rank='△', venues=['01'], winter=True, nonfinal=True, r_max=5,
         rank1_min=None, weakest_gap=None, wind=True,
         bet='3t_X1Y_2to5_pop50', label='3連単 X-1-Y（X,Y∈2〜5・50番人気まで）',
         verify='122.4%（66/116/172）'),
    dict(id='MIY-B', rank='△', venues=['17'], winter=True, nonfinal=True, r_max=5,
         rank1_min=None, weakest_gap=None, wind=True,
         bet='2t_X1', label='2連単 X-1（5点）',
         verify='133.8%（116/89/191）'),
    dict(id='FUK-B', rank='△', venues=['22'], winter=True, nonfinal=True, r_max=None,
         rank1_min=4, weakest_gap=None, wind=True,
         bet='2t_X1', label='2連単 X-1（5点）',
         verify='151.3%（65/98/240）'),
    dict(id='WAK-C', rank='△', venues=['20'], winter=True, nonfinal=True, r_max=5,
         rank1_min=None, weakest_gap=None, wind=True,
         bet='3t_X1Y_all', label='3連単 X-1-Y（20点・オッズで絞らない）',
         verify='118.9%（32/209/88）'),
    dict(id='TOD-A', rank='△', venues=['02'], winter=True, nonfinal=True, r_max=5,
         rank1_min=None, weakest_gap=None, wind=True,
         bet='3t_X1Y_40_80_pop50', label='3連単 X-1-Y（40〜80倍・50番人気まで）',
         verify='106.5%（85/141/87）'),
    dict(id='ASH-Q', rank='×', venues=['21'], winter=False, nonfinal=True, r_max=5,
         rank1_min=4, weakest_gap=None, wind=False,
         bet='3f_outer_top3', label='3連複 外上位3艇の1点',
         verify='114.6%（124/115/104）'),
    dict(id='MAR-E', rank='×', venues=['15'], winter=False, nonfinal=False, r_max=None,
         rank1_min=4, weakest_gap=None, wind=True,
         bet='2t_outer_top3_box', label='2連単 外上位3艇BOX（6点）',
         verify='101.0%（83/116/103）'),
    dict(id='W1-Q', rank='×', venues=['20', '09', '22'], winter=False, nonfinal=False, r_max=None,
         rank1_min=None, weakest_gap=1.0, wind=False,
         bet='3f_1XY_all', label='3連複 1号艇を含む10通り',
         verify='106/103/101%（各70〜90R）'),
]

RULE_BY_ID = {r['id']: r for r in RULES}

VENUE_NAMES = {'01': '桐生', '02': '戸田', '09': '津', '15': '丸亀', '17': '宮島',
               '20': '若松', '21': '芦屋', '22': '福岡'}

TARGET_VENUES = sorted({v for r in RULES for v in r['venues']})

# どのオッズが要るか（指示書 §4-3）
NEED_3T = {'KIR-A', 'KIR-C', 'TOD-A', 'WAK-C'}
NEED_2T = {'KIR-B', 'MIY-B', 'FUK-B', 'MAR-E'}
NEED_3F = {'ASH-Q', 'W1-Q'}


def is_winter(month):
    """10〜3月が冬。"""
    return month >= 10 or month <= 3


def match_rules(jcd, month, is_final_day, race_no, rank1, weakest_gap):
    """番組・季節・日程の条件だけで当てはまるルールIDを返す（風とオッズはGASが判定）。"""
    out = []
    for r in RULES:
        if jcd not in r['venues']:
            continue
        if r['winter'] and not is_winter(month):
            continue
        if r['nonfinal'] and is_final_day:
            continue
        if r['r_max'] is not None and race_no > r['r_max']:
            continue
        if r['rank1_min'] is not None and (rank1 is None or rank1 < r['rank1_min']):
            continue
        if r['weakest_gap'] is not None and (weakest_gap is None or weakest_gap < r['weakest_gap']):
            continue
        out.append(r['id'])
    return out
