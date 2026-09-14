# -*- coding: utf-8 -*-
"""店主の印象タグの「目盛り合わせ」— 評価は結果データと合っているか

1. 攻め評価（1〜5）ごとに、評価された選手の実績を並べる
     全国3・4コースのまくり系1着率、1着率、平均ST、F本数、級別の内訳
   → 評価が高いほどまくり系率が高ければ「店主の目は結果と整合」。
     整合しないなら「結果に残らない攻め（失敗した仕掛け）を見ている」＝機械に無い情報の可能性

2. 1艇ずつの検証（3・4の両方を要求しないので n が多い）
     3号艇 or 4号艇が「評価済み・攻め4以上」のレース vs 「評価済み・攻め3以下」のレース
     → 5・6頭率、1頭率、その艇の1着率とまくり系決着率
   評価済みどうしで比べるので「評価された選手＝有名な強い選手」の偏りが小さい

実行: python scripts/tags/tag_calib.py
"""
import os, re, csv, json, glob, math, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tag_ev import parse_k, load_odds, implied_head, z  # noqa: E402

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
os.chdir(REPO)


def load_tags():
    d = json.load(open('data/tags/racer_tags.json', encoding='utf-8'))
    return {r: v for r, v in d['racers'].items()}


def load_ledger():
    with open('data/tags/racers_ledger.csv', encoding='utf-8-sig') as f:
        return {r['登番']: r for r in csv.DictReader(f)}


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def calib(tags, led):
    print('=== 1. 攻め評価ごとの実績（全国13か月） ===')
    print('  評価  人数  A級  3・4コース走数  まくり系1着率  1着率   平均ST   F本数/人')
    for s in (5, 4, 3, 2, 1):
        rs = [r for r, v in tags.items() if v.get('atk') == s and r in led]
        if not rs:
            print('  %4d  %4d  （該当なし）' % (s, 0)); continue
        n34 = mk34 = w34 = 0.0
        sts, fs, a = [], 0, 0
        for r in rs:
            L = led[r]
            n4, n3 = f(L['4走']) or 0, 0
            # 4コースの走数・まくり系率は台帳にある。3コースは nat_course から
            n34 += n4; mk34 += (f(L['4まくり系1着率']) or 0) / 100 * n4
            if f(L['平均ST']) is not None: sts.append(f(L['平均ST']))
            fs += int(L['F本数'] or 0)
            a += 1 if L['級別'].startswith('A') else 0
        # 3コースぶんを nat_course から足す
        with open('data/edogawa/nat_course.csv', encoding='utf-8') as fh:
            for row in csv.DictReader(fh):
                if row['regno'] in rs and row['course'] in ('3', '4'):
                    if row['course'] == '3':
                        n34 += float(row['n']); mk34 += float(row['mk1'])
                    w34 += float(row['r1'])
        print('  %4d  %4d  %3d  %12.0f  %11.1f%%  %5.1f%%  %6.3f  %6.2f' % (
            s, len(rs), a, n34, mk34 / n34 * 100 if n34 else 0, w34 / n34 * 100 if n34 else 0,
            sum(sts) / len(sts) if sts else 0, fs / len(rs)))
    print('  ※まくり系1着率＝3・4コースで「まくり／まくり差し」で1着になった割合。評価が高いほど高ければ目盛りが合っている')


def boatwise(tags, races, odds):
    print()
    print('=== 2. 1艇ずつ: その艇が「評価済み」のレースだけで比べる ===')
    rated = {r: v.get('atk') for r, v in tags.items() if v.get('atk')}
    for lane in ('3', '4'):
        hi = [r for r in races if rated.get(r['boats'].get(lane), 0) >= 4]
        lo = [r for r in races if 0 < rated.get(r['boats'].get(lane), 0) <= 3]
        print('  --- %s号艇 ---' % lane)
        for lab, rs in (('攻め3以下（対照）', lo), ('★ 攻め4以上', hi)):
            n = len(rs)
            if not n:
                print('    %-16s データなし' % lab); continue
            w56 = sum(1 for r in rs if r['combo'][0] in '56')
            in2_56 = sum(1 for r in rs if r['combo'][0] in '56' or r['combo'][2] in '56')
            in3_56 = sum(1 for r in rs if any(c in '56' for c in (r['combo'][0], r['combo'][2], r['combo'][4])))
            w1 = sum(1 for r in rs if r['combo'][0] == '1')
            wl = sum(1 for r in rs if r['combo'][0] == lane)
            # その艇が2着以内
            top2 = sum(1 for r in rs if lane in (r['combo'][0], r['combo'][2]))
            ev = [(r, odds[(r['jcd'], r['date'], r['rno'])]) for r in rs if (r['jcd'], r['date'], r['rno']) in odds]
            line = '    %-16s n=%5d  5・6頭 %5.1f%%  5か6が2着内 %5.1f%%  5か6が3連単内 %5.1f%%  1頭 %5.1f%%  %s頭 %5.1f%%  %s2着内 %5.1f%%' % (
                lab, n, w56 / n * 100, in2_56 / n * 100, in3_56 / n * 100, w1 / n * 100, lane, wl / n * 100, lane, top2 / n * 100)
            if ev:
                m = len(ev)
                hitl = sum(1 for r, om in ev if r['combo'][0] == lane)
                retl = sum(r['payout'] for r, om in ev if r['combo'][0] == lane)
                impl = sum(implied_head(om, lane) for r, om in ev) / m
                hit56 = sum(1 for r, om in ev if r['combo'][0] in '56')
                ret56 = sum(r['payout'] for r, om in ev if r['combo'][0] in '56')
                imp56 = sum(implied_head(om, '5') + implied_head(om, '6') for r, om in ev) / m
                line += ('\n        └ オッズあり n=%4d  %s頭帯: 的中 %4.1f%% / 含意 %4.1f%% (%+.1fpt z=%+.1f) ROI %5.1f%%'
                         '  ｜ 5・6頭帯40点: 的中 %4.1f%% / 含意 %4.1f%% (%+.1fpt) ROI %5.1f%%' % (
                             m, lane, hitl / m * 100, impl * 100, (hitl / m - impl) * 100, z(hitl / m, m, impl),
                             retl / (m * 2000) * 100, hit56 / m * 100, imp56 * 100, (hit56 / m - imp56) * 100,
                             ret56 / (m * 4000) * 100))
            print(line)
    print('  ※「★」の行で 5・6頭（または 5か6が2着内・3連単内）が対照より高く、1頭が低ければ仮説の方向。'
          'その艇の頭帯の「差」がプラスなら、市場はその選手の攻めを安く見ている')


def main():
    tags = load_tags()
    led = load_ledger()
    print('評価あり %d 人（攻め評価 %d 人）' % (len(tags), sum(1 for v in tags.values() if v.get('atk'))))
    calib(tags, led)
    races = []
    for p in sorted(glob.glob('data/lzh_k/k*.lzh')):
        races.extend(parse_k(p))
    odds = load_odds()
    boatwise(tags, races, odds)


if __name__ == '__main__':
    main()
