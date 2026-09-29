# -*- coding: utf-8 -*-
"""買い目シグナル — 締切前判定・結果判定の関数（Python版）

GAS（gas/kaime/Code.gs）が本番で使うのと**同じ仕様**の関数をPythonで持ち、
test_kaime.py で公式ページの保存HTML（tests/fixtures/）に通して並びを確かめる。
どちらかを直したら、もう片方も必ず同じように直すこと。
"""
import re

ODDS_RE = re.compile(r'class="oddsPoint[^"]*">([^<]*)<')
WIND_RE = re.compile(r'風速</span>\s*<span class="weather1_bodyUnitLabelData">(\d+)m')
WIND_TIME_RE = re.compile(r'水面気象情報[\s　]*([^<]*?)\s*</p>')
NUM_RE = re.compile(r'numberSet1_number[^>]*>(\d)<')
PAY_RE = re.compile(r'is-payout1">&yen;([\d,]+)')

OUTER = [2, 3, 4, 5, 6]


def _num(v):
    try:
        return float(v.strip())
    except ValueError:
        return None          # 欠場など


# ------------------------------------------------------------------
# オッズ
# ------------------------------------------------------------------
def parse_odds3t(html):
    """3連単120通り → {'a-b-c': オッズ or None}。120個に満たなければ None（保留）。
    並びは scripts/odds.py の parse_odds3t と同じ。"""
    vals = ODDS_RE.findall(html or '')
    if len(vals) < 120:
        return None
    out = {}
    for i, v in enumerate(vals[:120]):
        r, h = divmod(i, 6)
        head = h + 1
        others = [b for b in range(1, 7) if b != head]
        second = others[r // 4]
        thirds = [b for b in others if b != second]
        out['%d-%d-%d' % (head, second, thirds[r % 4])] = _num(v)
    return out


def parse_odds2tf(html):
    """2連単・2連複ページ → ({'a-b': 2連単}, {'a-b': 2連複}) 。45個に満たなければ None。"""
    vals = ODDS_RE.findall(html or '')
    if len(vals) < 45:
        return None
    t2 = {}
    for i, v in enumerate(vals[:30]):
        r, h = divmod(i, 6)
        head = h + 1
        others = [b for b in range(1, 7) if b != head]
        t2['%d-%d' % (head, others[r])] = _num(v)
    f2 = {}
    pairs = [(a, b) for b in range(2, 7) for a in range(1, b)]   # 2連複：列=2着側b、行=a
    for (a, b), v in zip(pairs, vals[30:45]):
        f2['%d-%d' % (a, b)] = _num(v)
    return t2, f2


def f3_order():
    """3連複20個の並び：(a,b,c) を b=2..5, c=b+1..6, a=1..b-1 の順。"""
    return [(a, b, c) for b in range(2, 6) for c in range(b + 1, 7) for a in range(1, b)]


def parse_odds3f(html):
    vals = ODDS_RE.findall(html or '')
    if len(vals) < 20:
        return None
    return {'%d-%d-%d' % k: _num(v) for k, v in zip(f3_order(), vals[:20])}


def popularity(odds3t):
    """3連単の人気順位（オッズの低い順。同オッズは同順位）。数値でない目は None。"""
    nums = [v for v in odds3t.values() if v is not None]
    return {k: (None if v is None else 1 + sum(1 for x in nums if x < v)) for k, v in odds3t.items()}


# ------------------------------------------------------------------
# 直前情報（風速）
# ------------------------------------------------------------------
def parse_wind(html):
    """(風速m or None, 表示時刻の文字列)。"""
    m = WIND_RE.search(html or '')
    t = WIND_TIME_RE.search(html or '')
    return (int(m.group(1)) if m else None), (t.group(1).strip() if t else '')


# ------------------------------------------------------------------
# 買い目
# ------------------------------------------------------------------
def build_bets(bet, race, odds3t=None, odds2t=None, odds3f=None):
    """ルールの bet 種別から [{combo, odds, pop}] を作る。
    オッズが要るのに無いときは None（保留）。該当ゼロなら []（見送り）。"""
    pop = popularity(odds3t) if odds3t else {}

    def row(combo, table, with_pop=False):
        return dict(combo=combo, odds=table.get(combo) if table else None,
                    pop=pop.get(combo) if with_pop else None)

    if bet.startswith('3t_'):
        if not odds3t:
            return None
        xs = [2, 3, 4, 5] if bet == '3t_X1Y_2to5_pop50' else OUTER
        out = []
        for x in xs:
            for y in xs:
                if x == y:
                    continue
                c = '%d-1-%d' % (x, y)
                o, p = odds3t.get(c), pop.get(c)
                if bet == '3t_X1Y_all':
                    out.append(row(c, odds3t, True))
                elif o is None or p is None:
                    continue
                elif bet == '3t_X1Y_40_80_pop50' and 40.0 <= o < 80.0 and p <= 50:
                    out.append(row(c, odds3t, True))
                elif bet == '3t_X1Y_2to5_pop50' and p <= 50:
                    out.append(row(c, odds3t, True))
        return out
    if bet == '2t_X1':
        return [row('%d-1' % x, odds2t) for x in OUTER]
    if bet == '2t_outer_top3_box':
        t = race['outer_top3']
        return [row('%d-%d' % (a, b), odds2t) for a in t for b in t if a != b]
    if bet == '3f_outer_top3':
        return [row('-'.join(str(b) for b in sorted(race['outer_top3'])), odds3f)]
    if bet == '3f_1XY_all':
        return [row('1-%d-%d' % (x, y), odds3f) for x in OUTER for y in OUTER if x < y]
    raise ValueError('unknown bet: ' + bet)


# ------------------------------------------------------------------
# 結果ページ
# ------------------------------------------------------------------
def parse_result(html):
    """raceresult → {'3連単': [(組番, 払戻)], '3連複': [...], '2連単': [...], 'henkan': [艇番], 'cancelled': bool}
    結果がまだ無ければ None。同着で2行あれば両方入る。"""
    html = html or ''
    out = {'henkan': [], 'cancelled': False}
    for kind in ('3連単', '3連複', '2連単'):
        m = re.search(r'<td rowspan="2">%s</td>(.*?)</tbody>' % kind, html, re.S)
        rows = []
        if m:
            for tr in re.split(r'<tr', m.group(1)):
                nums = NUM_RE.findall(tr)
                pay = PAY_RE.search(tr)
                if nums and pay:
                    combo = '-'.join(sorted(nums) if kind == '3連複' else nums)   # 3連複は小さい順
                    rows.append((combo, int(pay.group(1).replace(',', ''))))
        out[kind] = rows
    m = re.search(r'<th>返還</th>(.*?)</table>', html, re.S)
    if m:
        out['henkan'] = [int(x) for x in NUM_RE.findall(m.group(1))]
    if not out['3連単']:
        if 'レース中止' in html:
            out['cancelled'] = True
        else:
            return None
    return out


KIND_OF_BET = {'3t': '3連単', '2t': '2連単', '3f': '3連複'}


def settle_bets(bet, bets, result, unit=100):
    """1点unit円で買ったときの (払戻合計, 的中した組番のリスト)。
    中止は全額返還、返還艇を含む目はその点だけ返還。"""
    if result['cancelled']:
        return unit * len(bets), []
    kind = KIND_OF_BET[bet[:2]]
    wins = dict(result[kind])
    pay, hits = 0, []
    for b in bets:
        boats = [int(x) for x in b['combo'].split('-')]
        if any(x in result['henkan'] for x in boats):
            pay += unit
        elif b['combo'] in wins:
            pay += wins[b['combo']] * unit // 100
            hits.append(b['combo'])
    return pay, hits
