# -*- coding: utf-8 -*-
"""表示した買い目の実戦成績 — EV監視セルの通算ROI

各会場ページが「実際にその日表示した買い目」を git 履歴から復元し、
Kファイル（data/lzh_k）の3連単結果・払戻と突き合わせて通算する。
バックテストではなく「ページに出た買い目をそのまま買っていたら」の成績。

追跡セル（買い目表示を入れた 2026-08-26 以降）:
  平和島 壁強×頭1      … 1-2-3/4/5/6 を 1,000円 100円単位でオッズ反比例配分（合成単勝）
  平和島 差し巧者×頭2  … 2-1-3/4/5/6 ＋ 2-3-1・2-4-1 の6点均等
  福岡   うねり窓S8    … 2-3-x／2-5-x の8点均等
  戸田   カド消し×攻め手5 … 頭5帯 5-X-Y 20点均等（EV検証と同じ帯）

出力: data/ev_track_log.csv（1行=1レース）／data/ev_track_summary.json／track/index.html
実行: python scripts/ev_track.py   （git履歴が要るので Actions では fetch-depth: 0）
"""
import os, re, csv, json, subprocess, unicodedata, datetime
import lhafile

TRACK_SINCE = '2026-08-26'
LOG = 'data/ev_track_log.csv'
SUMMARY = 'data/ev_track_summary.json'
PAGE = 'track/index.html'
LZH_K = 'data/lzh_k'
ODDS_DIR = 'data/odds'

RACE_HDR = re.compile(r'^\s{2,}(\d{1,2})R\s+(.*?)\s+H(\d{3,4})m')
SANTAN = re.compile(r'3連単\s+([1-6]-[1-6]-[1-6])\s+(\d+)')
S8 = ['2-3-1', '2-3-4', '2-3-5', '2-3-6', '2-5-1', '2-5-3', '2-5-4', '2-5-6']
HEAD5 = ['5-%d-%d' % (a, b) for a in range(1, 7) for b in range(1, 7) if a != 5 and b != 5 and a != b]
LOG_COLS = ['date', 'venue', 'race', 'cell', 'points', 'stake', 'result', 'payout', 'return', 'note']


# ---------------- git 履歴から「表示した買い目」を復元 ----------------
def git(*args):
    return subprocess.run(['git', *args], capture_output=True, check=True).stdout


def commits_for(path):
    return git('log', '--format=%H', '--since=' + TRACK_SINCE, '--', path).decode().split()


def show(commit, path):
    return git('show', '%s:%s' % (commit, path)).decode('utf-8', 'replace')


def recs_heiwajima():
    seen, recs = set(), []
    for c in commits_for('heiwajima/index.html'):        # 新しい順＝同日複数ビルドは最後のものを採用
        html = show(c, 'heiwajima/index.html')
        m = re.search(r'class="datebox">(\d{4}-\d{2}-\d{2})', html)
        if not m or m.group(1) in seen:
            continue
        date = m.group(1); seen.add(date)
        parts = re.split(r'<div class="card" id="race(\d+)">', html)
        for i in range(1, len(parts), 2):
            rno, body = int(parts[i]), parts[i + 1]
            if '買い目: 1-2-3' in body:
                recs.append(dict(date=date, jcd='04', venue='平和島', race=rno, mode='prop',
                                 cell='平和島 壁強×頭1（1-2-x 比例配分）',
                                 combos=['1-2-3', '1-2-4', '1-2-5', '1-2-6']))
            elif '買い目: 2-1-3' in body:
                recs.append(dict(date=date, jcd='04', venue='平和島', race=rno, mode='equal',
                                 cell='平和島 差し巧者×頭2（2-1-x＋2-3-1・2-4-1）',
                                 combos=['2-1-3', '2-1-4', '2-1-5', '2-1-6', '2-3-1', '2-4-1']))
    return recs


def recs_fukuoka():
    seen, recs = set(), []
    for c in commits_for('fukuoka/data/racecard.json'):
        try:
            d = json.loads(show(c, 'fukuoka/data/racecard.json'))
        except ValueError:
            continue
        date = d.get('date', '')
        if not date or date in seen:
            continue
        seen.add(date)
        for r in d.get('races', []):
            if any('買い目S8' in p for p in r.get('policy', [])):
                recs.append(dict(date=date, jcd='22', venue='福岡', race=int(r['race']), mode='equal',
                                 cell='福岡 うねり窓S8（2-3-x／2-5-x）', combos=S8))
    return recs


def recs_toda():
    seen, recs = set(), []
    for c in commits_for('toda/data.json'):
        try:
            d = json.loads(show(c, 'toda/data.json'))
        except ValueError:
            continue
        date = d.get('date', '')
        if not date or date in seen:
            continue
        seen.add(date)
        if not d.get('kaisai'):
            continue
        for r in d.get('races', []):
            if '攻撃権は5号艇へ' in r.get('policy', ''):
                recs.append(dict(date=date, jcd='02', venue='戸田', race=int(r['rno']), mode='equal',
                                 cell='戸田 カド消し×攻め手5→頭5帯（5-X-Y 20点）', combos=HEAD5))
    return recs


# ---------------- 結果（Kファイル）とオッズ ----------------
_kcache = {}


def results(date, jcd):
    key = (date, jcd)
    if key in _kcache:
        return _kcache[key]
    out = {}
    p = os.path.join(LZH_K, 'k%s%s%s.lzh' % (date[2:4], date[5:7], date[8:10]))
    if os.path.exists(p):
        try:
            lf = lhafile.Lhafile(p)
            raw = lf.read(lf.infolist()[0].filename).decode('shift_jis', 'replace')
        except Exception:
            raw = ''
        if jcd + 'KBGN' in raw:
            blk = raw.split(jcd + 'KBGN')[1].split(jcd + 'KEND')[0]
            cur = None
            for ln in blk.split('\n'):
                h = RACE_HDR.match(ln)
                if h and ('風' in ln or '波' in ln):
                    cur = int(h.group(1)); continue
                if cur is None:
                    continue
                sm = SANTAN.search(unicodedata.normalize('NFKC', ln))
                if sm and cur not in out:
                    out[cur] = (sm.group(1), int(sm.group(2)))
    _kcache[key] = out
    return out


def odds(jcd, date, rno):
    p = os.path.join(ODDS_DIR, jcd, date + '.csv')
    if not os.path.exists(p):
        return {}
    o = {}
    with open(p, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if int(r['race']) == rno and r['odds']:
                o[r['combo']] = float(r['odds'])
    return o


def allocate(combos, o, budget=1000, unit=100):
    """オッズ反比例で100円単位に配分（最大剰余法）。返り値 {combo: 円}"""
    w = {c: 1.0 / o[c] for c in combos}
    tot = sum(w.values())
    n_units = budget // unit
    raw = {c: w[c] / tot * n_units for c in combos}
    units = {c: int(raw[c]) for c in combos}
    for c in sorted(combos, key=lambda c: raw[c] - units[c], reverse=True)[: n_units - sum(units.values())]:
        units[c] += 1
    return {c: units[c] * unit for c in combos}


def settle(rec):
    res = results(rec['date'], rec['jcd']).get(rec['race'])
    row = dict(date=rec['date'], venue=rec['venue'], race=rec['race'], cell=rec['cell'],
               points=len(rec['combos']), result='', payout='', **{'return': ''}, note='')
    if rec['mode'] == 'prop':
        o = odds(rec['jcd'], rec['date'], rec['race'])
        if all(c in o for c in rec['combos']):
            alloc = allocate(rec['combos'], o)
            row['stake'] = sum(alloc.values())
            row['note'] = ' '.join('%s=%d' % (c, alloc[c]) for c in rec['combos'])
            hit_ret = lambda combo, pay: alloc[combo] / 100 * pay
        else:
            row['stake'] = 100 * len(rec['combos'])
            row['note'] = 'オッズ未取得のため均等'
            hit_ret = lambda combo, pay: pay
    else:
        row['stake'] = 100 * len(rec['combos'])
        hit_ret = lambda combo, pay: pay
    if res is None:
        return row                                     # 結果未着（Kファイル未取得）＝未確定
    combo, pay = res
    row['result'], row['payout'] = combo, pay
    row['return'] = int(round(hit_ret(combo, pay))) if combo in rec['combos'] else 0
    return row


# ---------------- ログのマージ・集計・ページ ----------------
def load_log():
    if not os.path.exists(LOG):
        return {}
    with open(LOG, encoding='utf-8') as f:
        return {(r['date'], r['venue'], int(r['race']), r['cell']): r for r in csv.DictReader(f)}


def summarize(rows):
    cells = {}
    for r in rows:
        s = cells.setdefault(r['cell'], dict(n=0, hits=0, stake=0, ret=0, pending=0))
        if r['result'] == '':
            s['pending'] += 1; continue
        s['n'] += 1; s['stake'] += int(r['stake']); s['ret'] += int(r['return'])
        s['hits'] += 1 if int(r['return']) > 0 else 0
    for s in cells.values():
        s['roi'] = round(s['ret'] / s['stake'] * 100, 1) if s['stake'] else None
    tot = dict(n=sum(s['n'] for s in cells.values()), hits=sum(s['hits'] for s in cells.values()),
               stake=sum(s['stake'] for s in cells.values()), ret=sum(s['ret'] for s in cells.values()),
               pending=sum(s['pending'] for s in cells.values()))
    tot['roi'] = round(tot['ret'] / tot['stake'] * 100, 1) if tot['stake'] else None
    return cells, tot


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def render(rows, cells, tot, now):
    def pct(v):
        return '—' if v is None else '%.0f%%' % v
    cell_rows = ''.join(
        '<tr><td>%s</td><td class="num">%d</td><td class="num">%d</td><td class="num">%s</td>'
        '<td class="num">%s</td><td class="num roi %s">%s</td><td class="num">%s</td></tr>'
        % (esc(k), s['n'], s['hits'], '{:,}'.format(s['stake']), '{:,}'.format(s['ret']),
           'good' if (s['roi'] or 0) >= 100 else 'bad', pct(s['roi']), s['pending'] or '')
        for k, s in cells.items())
    log_rows = ''.join(
        '<tr><td>%s</td><td>%s %dR</td><td>%s</td><td class="num">%s</td>'
        '<td class="num">%s</td><td>%s</td><td class="num">%s</td><td class="num %s">%s</td></tr>'
        % (r['date'], esc(r['venue']), int(r['race']), esc(r['cell']).split('（')[0], r['points'],
           '{:,}'.format(int(r['stake'])), r['result'] or '<span class="pend">未確定</span>',
           '{:,}'.format(int(r['payout'])) if r['payout'] != '' else '',
           'hit' if r['return'] not in ('', '0', 0) else '',
           ('{:,}'.format(int(r['return'])) if r['return'] != '' else ''))
        for r in sorted(rows, key=lambda r: (r['date'], r['venue'], int(r['race'])), reverse=True))
    return '''<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>実戦成績 — 表示した買い目の通算ROI</title>
<style>
*{box-sizing:border-box}
body{margin:0;padding:16px;font-family:-apple-system,"Hiragino Sans","Yu Gothic UI",Meiryo,sans-serif;font-size:15px;line-height:1.8;color:#2B2B28;background:#F7F5EF}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:18px;margin:28px 0 8px}
.lead{font-size:14px;color:#5A574E;margin:0 0 16px}
.venues{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 16px}
.venues a,.venues .on{display:inline-block;padding:6px 12px;border-radius:6px;font-size:14px;font-weight:700;text-decoration:none}
.venues a{background:#fff;color:#2B2B28;border:1px solid #D8D4C8}
.venues .on{background:#2B2B28;color:#fff}
.total{background:#fff;border:2px solid #2B2B28;border-radius:10px;padding:14px 16px;margin:0 0 8px}
.total b{font-size:26px}
.total .roi{font-size:32px;font-weight:700}
.wrap{overflow-x:auto}
table{border-collapse:collapse;background:#fff;width:100%%;min-width:560px}
th,td{border:1px solid #D8D4C8;padding:7px 9px;font-size:14px;text-align:left;vertical-align:top}
th{background:#EFECE3;font-weight:700}
td.num{text-align:right;font-family:"Zen Kaku Gothic New",-apple-system,sans-serif;font-weight:700}
td.roi.good{color:#1B6E3A}
td.roi.bad{color:#B8322A}
td.hit{color:#1B6E3A}
.pend{color:#B8322A;font-weight:700}
.note{background:#fff;border:1px solid #D8D4C8;border-radius:8px;padding:12px 14px;font-size:14px;margin:12px 0}
.note li{margin:2px 0}
footer{margin-top:24px;font-size:12px;color:#5A574E}
</style></head><body>
<nav class="venues" data-venue="track"></nav>
<h1>実戦成績 — 表示した買い目の通算ROI</h1>
<p class="lead">各会場ページに<b>その日実際に表示した買い目</b>を、そのまま買っていたらどうなったか。
バックテストではなく実戦の記録です（2026-08-27〜、毎週月曜に自動更新）。</p>

<div class="total">通算 <b>%d</b>レース ／ 的中 <b>%d</b>本 ／ 賭け %s円 → 払戻 %s円 ／ ROI <span class="roi">%s</span>%s</div>

<h2>セル別</h2>
<div class="wrap"><table>
<tr><th>監視セル</th><th>レース</th><th>的中</th><th>賭け(円)</th><th>払戻(円)</th><th>ROI</th><th>未確定</th></tr>
%s
</table></div>

<div class="note"><b>読み方</b>
<ul>
<li>ROI100%%が損益分岐。<b>100レース貯まるまでは判定しない</b>（EV検証と同じ三条件ルール）。</li>
<li>福岡S8は的中率6.5%%（15レースに1本）の「万舟を拾う」買い方。外れが続くのが前提。</li>
<li>平和島 壁強は1,000円を100円単位でオッズ反比例に配分（安い組ほど厚く）。ほかは1点100円の均等買い。</li>
<li>戸田 カド消し×攻め手5は頭5帯（5-X-Y）20点均等＝EV検証で ROI194%%（n=83）が出た帯と同じ買い方。</li>
<li>「未確定」は結果ファイル未着（翌朝のビルドで確定）。</li>
</ul></div>

<h2>全レース</h2>
<div class="wrap"><table>
<tr><th>日付</th><th>レース</th><th>セル</th><th>点数</th><th>賭け</th><th>結果</th><th>払戻</th><th>回収</th></tr>
%s
</table></div>

<footer>更新: %s JST ／ scripts/ev_track.py（git履歴の各日ページ × Kファイル結果）</footer>
<script src="../venues.js"></script>
</body></html>
''' % (tot['n'], tot['hits'], '{:,}'.format(tot['stake']), '{:,}'.format(tot['ret']), pct(tot['roi']),
       '（ほか未確定 %d）' % tot['pending'] if tot['pending'] else '', cell_rows, log_rows, now)


def main():
    recs = recs_heiwajima() + recs_fukuoka() + recs_toda()
    old = load_log()
    merged = dict(old)
    for rec in recs:
        row = settle(rec)
        key = (row['date'], row['venue'], row['race'], row['cell'])
        if row['result'] == '' and key in old and old[key]['result'] != '':
            continue                                   # 結果は一度確定したら保持（Kファイルが古くて消えても残す）
        row = {k: ('' if row.get(k) is None else row.get(k)) for k in LOG_COLS}
        merged[key] = row
    rows = sorted(merged.values(), key=lambda r: (r['date'], r['venue'], int(r['race'])))
    cells, tot = summarize(rows)
    now = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).strftime('%Y-%m-%d %H:%M')

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLS)
        w.writeheader(); w.writerows(rows)
    with open(SUMMARY, 'w', encoding='utf-8') as f:
        json.dump(dict(generated=now, since=TRACK_SINCE, cells=cells, total=tot), f, ensure_ascii=False, indent=1)
    os.makedirs(os.path.dirname(PAGE), exist_ok=True)
    with open(PAGE, 'w', encoding='utf-8') as f:
        f.write(render(rows, cells, tot, now))

    print('表示した買い目 %d レース（未確定 %d）' % (len(rows), tot['pending']))
    for k, s in cells.items():
        print('  %-40s n=%3d 的中%2d 賭け%6d 払戻%6d ROI %s' % (k, s['n'], s['hits'], s['stake'], s['ret'],
              '—' if s['roi'] is None else '%.0f%%' % s['roi']))
    print('  合計 n=%d 的中%d 賭け%d 払戻%d ROI %s' % (tot['n'], tot['hits'], tot['stake'], tot['ret'],
          '—' if tot['roi'] is None else '%.0f%%' % tot['roi']))


if __name__ == '__main__':
    main()
