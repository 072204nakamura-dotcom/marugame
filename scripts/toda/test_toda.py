# -*- coding: utf-8 -*-
"""戸田(02) 穴党ツール の回帰テスト（ネットワーク不要）

実行: python scripts/toda/test_toda.py

指示書§3の受け入れ基準を、蓄積済みデータから毎回計算して確認する。
仕様書の数値は 2025-07-09〜2026-07-08 窓のもの。こちらは毎朝window が進むので
完全一致はしない。許容幅は指示書の指定（±0.5%等）か、方向と大きさで判定する。
"""
import os
import csv
import sys
import inspect
from collections import defaultdict

import toda_daily as t

FAILED = []


def check(name, cond, detail=''):
    print(('  OK  ' if cond else '  NG! ') + name + (('   << ' + detail) if not cond else
                                                     (('   ' + detail) if detail else '')))
    if not cond:
        FAILED.append(name)


def near(got, want, tol):
    return abs(got - want) <= tol


def load(path):
    with open(path, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def main():
    D = t.DATA
    races = load(os.path.join(D, 'toda_races.csv'))
    ents = load(os.path.join(D, 'toda_entries.csv'))
    mak = load(os.path.join(D, 'toda_makuriya.csv'))
    nok = load(os.path.join(D, 'toda_nokoshi6.csv'))
    counts = t.load_counts()

    print('=== 1. 戸田の集計規模（指示書§3: 185開催日・約2,220レース） ===')
    days = len({r['date'] for r in races})
    check('開催日数 185日前後', 175 <= days <= 195, '実測 %d日' % days)
    check('レース数 2,220前後', 2100 <= len(races) <= 2350, '実測 %dレース' % len(races))

    print('=== 2. 当地ベース値（指示書§3） ===')
    base = t.base_stats(races)
    check('イン1着率 42.9%（±0.5）', near(base['in1'], 42.9, 0.5), '実測 %.1f%%' % base['in1'])
    check('万舟率 17.6%（±1.0）', near(base['man'], 17.6, 1.0), '実測 %.1f%%' % base['man'])
    check('3連単中央値 3,320円前後', 2900 <= base['median'] <= 3700,
          '実測 %d円' % base['median'])

    print('=== 3. 決まり手の分布（指示書§3） ===')
    for label, key, want in (('逃げ', 'nige', 40.7), ('まくり', 'makuri', 26.5),
                             ('まくり差し', 'makurizashi', 11.8), ('差し', 'sashi', 13.3),
                             ('抜き', 'nuki', 6.9)):
        got = base[key]
        check('%s %.1f%%（±2.0）' % (label, want), near(got, want, 2.0), '実測 %.1f%%' % got)
    check('まくり系（まくり＋まくり差し）38.3%（±2.0）',
          near(base['makuri_kei'], 38.3, 2.0), '実測 %.1f%%' % base['makuri_kei'])

    print('=== 4. 全国1コース逃げ率（指示書§3: 55.2%±0.5） ===')
    i = {c: n for n, c in enumerate(t.CNT_COLS)}
    c1n = sum(v[i['c1n']] for v in counts.values())
    c1w = sum(v[i['c1w']] for v in counts.values())
    rate = c1w / c1n * 100
    check('全国1コース逃げ率 55.2%（±0.5）', near(rate, 55.2, 0.5),
          '実測 %.1f%%（n=%d）' % (rate, c1n))

    print('=== 5. 採用シグナル②まくり屋カド（仕様書2-②: まくり系38.3→61.2%） ===')
    power = {r['登番']: float(r['まくり力']) for r in mak}
    kim = {(r['date'], r['rno']): r['kimarite'] for r in races}
    c4 = {}
    for e in ents:
        if e['course'] == '4':
            c4[(e['date'], e['rno'])] = e['touban']
    # 仕様書には「まくり屋」の定義が2つある。
    #   A) §5-1 … まくり力 >= +8（表の印。参考として毎日出す）
    #   B) §2-② … 実まくり率 >= 20% かつ 全国4コース10走以上
    #             （効果61.2%・n=121の出典。★アプリはこちらを判定に使う）
    # 両方の数字を毎日出して、乖離が広がっていないか見えるようにしておく。
    rate4 = {r['登番']: (float(r['実4まくり率']), int(r['全国4走'])) for r in mak}

    def effect(sel):
        hit = [k for k, tb in c4.items() if sel(tb)]
        if not hit:
            return 0, 0, 0
        mkn = sum(1 for k in hit if kim.get(k) in t.MAKURI_KEI)
        w = sum(1 for k in hit if ent4[k]['chaku'] == '01')
        return len(hit), mkn / len(hit) * 100, w / len(hit) * 100

    ent4 = {}
    for e in ents:
        if e['course'] == '4':
            ent4[(e['date'], e['rno'])] = e

    nA, mA, wA = effect(lambda tb: power.get(tb, -99) >= t.MAKURIYA_POWER_TH)
    nB, mB, wB = effect(lambda tb: tb in rate4
                        and rate4[tb][0] >= t.MAKURIYA_RATE_TH
                        and rate4[tb][1] >= t.MAKURIYA_MIN_N)
    print('    A) まくり力>=+8（参考）          n=%3d まくり系%.1f%% 4コ勝率%.1f%%' % (nA, mA, wA))
    print('    B) 実まくり率>=20%%（★判定に使用） n=%3d まくり系%.1f%% 4コ勝率%.1f%%' % (nB, mB, wB))
    check('判定に使うn が仕様書の n=121 と近い', 90 <= nB <= 155, '実測 n=%d' % nB)
    lift = mB - base['makuri_kei']
    check('まくり屋カド時のまくり系がベースを大きく上回る（+15pt以上）', lift >= 15,
          '実測 %.1f%% vs ベース%.1f%% ＝ +%.1fpt（n=%d）'
          % (mB, base['makuri_kei'], lift, nB))
    check('まくり屋カド時の4コース勝率 約30%（仕様書 13.4→30.1%）', 22 <= wB <= 42,
          '実測 %.1f%%' % wB)

    print('=== 6. 採用シグナル②下側 カド消し（仕様書2-②: 4コース勝率6.7%） ===')
    low = [k for k, tb in c4.items() if power.get(tb, 99) <= t.KADOKESHI_TH]
    lw = sum(1 for e in ents if e['course'] == '4' and e['chaku'] == '01'
             and (e['date'], e['rno']) in set(low))
    check('カド消し時の4コース勝率 約6.7%（半分以下）', lw / len(low) * 100 <= 11,
          '実測 %.1f%%（n=%d）' % (lw / len(low) * 100, len(low))) if low else None

    print('=== 7. 採用シグナル③6コース残す型（仕様書2-③: 21.4→35.8%） ===')
    resid = {r['登番']: float(r['残し残差']) for r in nok}
    c6 = [(e, resid.get(e['touban'])) for e in ents if e['course'] == '6']
    allc6 = [e for e, _ in c6]
    base6 = sum(1 for e in allc6 if e['chaku'] in ('02', '03')) / len(allc6) * 100
    hit6 = [e for e, v in c6 if v is not None and v >= t.NOKOSHI_TH]
    r6 = sum(1 for e in hit6 if e['chaku'] in ('02', '03')) / len(hit6) * 100
    check('戸田6コースの2-3連対ベース 21.4%（±2）', near(base6, 21.4, 2.0),
          '実測 %.1f%%' % base6)
    check('残す型の2-3連対 約36%', 30 <= r6 <= 42,
          '実測 %.1f%%（n=%d・+%.1fpt）' % (r6, len(hit6), r6 - base6))
    low6 = [e for e, v in c6 if v is not None and v <= t.KIERU_TH]
    r6l = sum(1 for e in low6 if e['chaku'] in ('02', '03')) / len(low6) * 100
    check('消える型の2-3連対 約15.8%（ベース以下）', r6l < base6,
          '実測 %.1f%%（n=%d）' % (r6l, len(low6)))

    print('=== 8. 判定ロジック（指示書§6 のフロー） ===')
    T_MAK = {r['登番']: {'まくり力': float(r['まくり力']),
                        '実4まくり率': float(r['実4まくり率']),
                        '全国4走': int(r['全国4走'])} for r in mak}
    T_NOK = {r['登番']: {'残し残差': float(r['残し残差'])} for r in nok}
    # まくり屋の検体は判定に使う定義B（実まくり率>=20%・10走以上）を満たす選手から取る
    top_mak = next(r['登番'] for r in mak
                   if float(r['実4まくり率']) >= t.MAKURIYA_RATE_TH
                   and int(r['全国4走']) >= t.MAKURIYA_MIN_N)
    low_mak = mak[-1]['登番']
    top_nok = nok[0]['登番']
    low_nok = nok[-1]['登番']
    # 両方の表で「印なし」の選手でないと、無印レースの検体にならない
    nok_resid = {r['登番']: float(r['残し残差']) for r in nok}
    neutral = next(r['登番'] for r in mak
                   if abs(float(r['まくり力'])) < 1
                   and float(r['実4まくり率']) < t.MAKURIYA_RATE_TH
                   and t.KIERU_TH < nok_resid.get(r['登番'], 0) < t.NOKOSHI_TH)

    def mk(regnos):
        return dict(rno=1, rname='予選', deadline='11:00',
                    boats=[dict(teiban=n + 1, regno=r, name='x', grade='B1')
                           for n, r in enumerate(regnos)])

    base_regs = [neutral] * 6
    s, f, p = t.judge_race(mk(base_regs), T_MAK, T_NOK)
    check('無印レース → 0点・見送り', s == 0 and f == [] and '見送り' in p, 'score=%d %s' % (s, f))

    regs = list(base_regs); regs[3] = top_mak
    s, f, p = t.judge_race(mk(regs), T_MAK, T_NOK)
    check('4号艇がまくり屋 → +2点・まくり屋カド', s == 2 and 'まくり屋カド' in f, 'score=%d' % s)
    check('  方針が 4-5-x / 4-1-x / 4-3-x', '4-5-x' in p and '4-1-x' in p and '4-3-x' in p, p[:50])
    check('  1号艇は薄くの注記', '着外57%' in p, p[:80])

    regs = list(base_regs); regs[3] = low_mak
    s, f, p = t.judge_race(mk(regs), T_MAK, T_NOK)
    check('4号艇がまくらない型 → −1点・カド消し', s == -1 and 'カド消し' in f, 'score=%d' % s)
    check('  方針に4コース勝率6.7%', '6.7%' in p, p[:50])

    regs = list(base_regs); regs[5] = top_nok
    s, f, p = t.judge_race(mk(regs), T_MAK, T_NOK)
    check('6号艇が残す型 → +1点・6残す', s == 1 and '6残す' in f, 'score=%d' % s)
    check('  方針がヒモ強調', 'ヒモ強調' in p and '2着づけ' in p, p[:50])

    regs = list(base_regs); regs[5] = low_nok
    s, f, p = t.judge_race(mk(regs), T_MAK, T_NOK)
    check('6号艇が消える型 → 0点・6切り（スコアは動かさない）',
          s == 0 and '6切り' in f, 'score=%d %s' % (s, f))

    regs = list(base_regs); regs[3] = top_mak; regs[5] = top_nok
    s, f, p = t.judge_race(mk(regs), T_MAK, T_NOK)
    check('二枚重ね → +3点', s == 3 and 'まくり屋カド' in f and '6残す' in f, 'score=%d' % s)
    check('  本線 4-6-x', '4-6-x' in p, p[:40])
    check('  n=11のサンプル不足を明記', 'n=11' in p and 'サンプル不足' in p, p[:90])

    print('=== 9. 却下シグナルが実装に混入していないか（仕様書§3） ===')
    src = inspect.getsource(t.judge_race) + inspect.getsource(t.label_for)
    for w in ('風', 'wdir', 'wspd', '北西', '人気', 'ninki', '展示', 'tenji'):
        check('judge_race/label_for が「%s」を参照していない' % w, w not in src)

    print('=== 10. 非開催日の扱い ===')
    check('02ブロックが無ければ None', t.parse_b('01BBGN\nx\n01BEND') is None)

    print()
    if FAILED:
        print('NG %d件: %s' % (len(FAILED), ' / '.join(FAILED)))
        return 1
    print('全テスト通過')
    return 0


if __name__ == '__main__':
    sys.exit(main())
