# -*- coding: utf-8 -*-
"""
全場共通 EVバックテスト v1（シグナルレース × 確定オッズ照合・毎回フル再計算）

検証すること：
 1) シグナルレースで各「頭帯」（h-X-Y 20点）と「非イン帯」（2〜6頭 100点）の
    実測的中率が、市場含意の公正確率（控除補正後）を上回るか（エッジ残存）
 2) 確定オッズ等額買いのROI（すべり想定ヘアカット付き）
 3) 合成オッズ閾値（EVフィルタ）を上げると回収率が上がるか（過剰人気の裏の構造確認）
 4) 最大連敗・最大ドローダウン（資金設計用）

実行: python scripts/ev_backtest.py
出力:
  data/ev_backtest_log.csv      … シグナルレース×帯の明細
  data/ev_backtest_summary.json … 場×帯サマリー
前提: data/odds/{JCD}/YYYY-MM-DD.csv（既存バッチ蓄積・読むだけ）
      data/lzh_k/kYYMMDD.lzh（既存キャッシュ・読むだけ）
"""
import os, re, csv, json, glob

import lhafile

ODDS_ROOT = 'data/odds'
LZH_K = 'data/lzh_k'
LOG_CSV = 'data/ev_backtest_log.csv'
SUM_JSON = 'data/ev_backtest_summary.json'
TAKEOUT = 0.75            # 3連単の払戻率
HAIRCUT = 5.0             # 確定→直前オッズのすべり想定（ROI判定時に引くpt）
SYNTH_CUTS = (0, 8, 12, 16, 20)   # 合成オッズ閾値スイープ（0=フィルタなし）

# レース番号ベースの採用シグナル（z>=2.0・WF通過済みのみ。気象条件系はv2）
SIGNALS = {
    '09': dict(name='津',     races=(4,), label='4R企画穴ゾーン(z=-2.3/-4.5)'),
    '04': dict(name='平和島', races=(7,), label='7R穴ゾーン(z=-3.23)'),
    '03': dict(name='江戸川', races=(6,), label='6R最深穴ゾーン(z=-2.62)'),
}

RE_PAY = re.compile(r'^\s+(\d{1,2})R\s+([1-6]-[1-6]-[1-6])\s+(\d+)')


def k_block(date, jcd):
    path = f"{LZH_K}/k{date[2:4]}{date[5:7]}{date[8:10]}.lzh"
    if not os.path.exists(path):
        return None
    try:
        lf = lhafile.Lhafile(path)
        raw = lf.read(lf.infolist()[0].filename).decode('shift_jis', errors='replace')
    except Exception:
        return None
    key = f'{jcd}KBGN'
    if key not in raw:
        return None
    return raw.split(key)[1].split(f'{jcd}KEND')[0]


def results(date, jcd):
    """{race:(combo, payout)} 3連単（ブロック冒頭の払戻一覧・各レース最初の組）"""
    blk = k_block(date, jcd)
    if not blk:
        return {}
    out = {}
    for ln in blk.split('\n'):
        m = RE_PAY.match(ln)
        if m and 'H' not in ln:
            r = int(m.group(1))
            if r not in out:
                out[r] = (m.group(2), int(m.group(3)))
    return out


def load_odds(path):
    out = {}
    with open(path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            try:
                o = float(row['odds'])
            except (ValueError, TypeError, KeyError):
                continue
            if o > 0:
                out[(int(row['race']), row['combo'].strip())] = o
    return out


def make_bands():
    bs = {}
    for h in range(1, 7):
        bs[f'head{h}'] = [f'{h}-{s}-{t}' for s in range(1, 7) for t in range(1, 7)
                          if len({h, s, t}) == 3]
    bs['anti_in'] = [c for h in range(2, 7) for c in bs[f'head{h}']]
    return bs

BANDS = make_bands()


def band_row(date, race, odds, res, name, combos):
    priced = [(c, odds[(race, c)]) for c in combos if (race, c) in odds]
    if len(priced) < len(combos) - 8:     # 欠場等で帯が大きく壊れた日は除外
        return None
    synth_p = sum(1 / o for _, o in priced)          # 市場含意確率（控除込み）
    combo, payout = res
    hit = any(c == combo for c, _ in priced)
    ret = int(odds.get((race, combo), 0) * 100) if hit else 0
    return dict(date=date, race=race, band=name,
                points=len(priced), cost=len(priced) * 100,
                hit=int(hit), ret=ret,
                synth=round(1 / synth_p, 2),            # 帯の合成オッズ
                fair_p=round(synth_p * TAKEOUT, 4),     # 控除補正後の公正確率
                combo=combo, payout=payout)


def summarize(rows):
    """等額100円買いの通算成績（時系列で連敗・DDも計算）"""
    rows = sorted(rows, key=lambda r: (r['date'], r['race'], r['band']))
    n = len(rows)
    cost = sum(r['cost'] for r in rows)
    ret = sum(r['ret'] for r in rows)
    hits = sum(r['hit'] for r in rows)
    ep = sum(r['fair_p'] for r in rows)                 # 期待的中数（市場基準）
    var = sum(r['fair_p'] * (1 - r['fair_p']) for r in rows)
    z = (hits - ep) / var ** 0.5 if var > 0 else 0.0
    streak = worst = cum = peak = dd = 0
    for r in rows:
        streak = 0 if r['hit'] else streak + 1
        worst = max(worst, streak)
        cum += r['ret'] - r['cost']
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    roi = ret / cost * 100 if cost else 0.0
    return dict(n=n, hits=hits,
                roi=round(roi, 1), roi_haircut=round(roi - HAIRCUT, 1),
                hit_rate=round(hits / n * 100, 1) if n else 0,
                mkt_fair=round(ep / n * 100, 1) if n else 0,
                edge_z=round(z, 2),
                max_miss_streak=worst, max_dd_yen=int(dd))


def main():
    all_rows, report = [], {}
    for jcd, sig in SIGNALS.items():
        odds_files = sorted(glob.glob(f'{ODDS_ROOT}/{jcd}/*.csv'))
        if not odds_files:
            report[jcd] = dict(name=sig['name'], note='オッズ未蓄積のためスキップ')
            continue
        rows, days = [], 0
        for path in odds_files:
            date = os.path.basename(path)[:10]
            res = results(date, jcd)
            if not res:
                continue
            odds, hit_day = None, False
            for race in sig['races']:
                if race not in res:
                    continue
                if odds is None:
                    odds = load_odds(path)
                for name, combos in BANDS.items():
                    r = band_row(date, race, odds, res[race], name, combos)
                    if r:
                        r['jcd'] = jcd
                        rows.append(r)
                        hit_day = True
            if hit_day:
                days += 1
        all_rows += rows
        venue = dict(name=sig['name'], label=sig['label'], days=days)
        for name in BANDS:
            sub = [r for r in rows if r['band'] == name]
            if sub:
                venue[name] = summarize(sub)
        # EVフィルタの効き確認：外枠頭帯(head2〜6)をプールし、合成オッズ閾値でふるう
        sweep = {}
        outs = [r for r in rows
                if r['band'].startswith('head') and r['band'] != 'head1']
        for cut in SYNTH_CUTS:
            sub = [r for r in outs if r['synth'] >= cut]
            if sub:
                sweep[str(cut)] = summarize(sub)
        venue['sweep_outsider_heads'] = sweep
        report[jcd] = venue

    os.makedirs('data', exist_ok=True)
    with open(LOG_CSV, 'w', newline='', encoding='utf-8-sig') as f:
        cols = ['jcd', 'date', 'race', 'band', 'points', 'cost', 'hit', 'ret',
                'synth', 'fair_p', 'combo', 'payout']
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader(); w.writerows(all_rows)
    with open(SUM_JSON, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print('読み方: hit_rate > mkt_fair かつ edge_z>=2.0 でエッジ残存。'
          'roi_haircut>=110 かつ n>=100 で本採用検討。'
          'sweepは合成オッズ閾値を上げてroiが上がるか（EVフィルタの効き）を見る。'
          'n<30は表示のみ・判定しない。')


if __name__ == '__main__':
    main()
