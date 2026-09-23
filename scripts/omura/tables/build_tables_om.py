# -*- coding: utf-8 -*-
"""大村(24) 選手表5種＋モーター表（旧世代・現行世代）を構築
   入力: extract_omura.py の出力（nat_*.csv, omura_entries.csv, omura_races.csv）と omura_b_entries.csv
   出力: data/omura/ 配下（BOM付きUTF-8）
     om_st.csv / om_shibori.csv / om_zanshi.csv / om_wall.csv
     om_motor_oldgen.csv / om_motor_current.csv / om_race_resid.csv / nat_1c.csv ほか
   閾値は丸亀§3・津/福岡/平和島移植メモの校正判断を踏襲（当地採用n≥10、遅れ>0.18、巧者≤0.13、
   絞りまくり当地15走以上・率≥15%、残す/飛ぶ=上下20%デシル、壁=上下10%、6ヒモ外し=艇番6 n≥15 & 3連対<25%）"""
import csv, os, math, statistics
from collections import defaultdict

OUT = 'data/omura'; os.makedirs(OUT, exist_ok=True)
K = 20
names = {r['regno']: r['name'] for r in csv.DictReader(open('nat_names.csv', encoding='utf-8'))}
ent = list(csv.DictReader(open('omura_entries.csv', encoding='utf-8')))
races = list(csv.DictReader(open('omura_races.csv', encoding='utf-8')))
B = list(csv.DictReader(open('omura_b_entries.csv', encoding='utf-8')))
nat1c = {r['touban']: (int(r['n1c']), int(r['win1c'])) for r in csv.DictReader(open('nat_1c.csv'))}
P0 = sum(v[1] for v in nat1c.values()) / sum(v[0] for v in nat1c.values())
def shrink(reg):
    n, w = nat1c.get(reg, (0, 0)); return (w + K * P0) / (n + K)
def wcsv(name, fields, rows):
    with open(os.path.join(OUT, name), 'w', newline='', encoding='utf-8-sig') as fo:
        w = csv.DictWriter(fo, fieldnames=fields, extrasaction='ignore'); w.writeheader()
        for r in rows: w.writerow(r)
    print('  ->', name, len(rows), '行')

# ---------- ① ST表 ----------
natst = defaultdict(lambda: {'slow': [0.0, 0], 'dash': [0.0, 0]})
for r in csv.DictReader(open('nat_st.csv')):
    key = 'slow' if r['course'] in '123' else 'dash'
    natst[r['regno']][key][0] += float(r['st_avg']) * int(r['n']); natst[r['regno']][key][1] += int(r['n'])
locst = defaultdict(lambda: {'slow': [0.0, 0], 'dash': [0.0, 0]})
for e in ent:
    if not e['course']: continue
    try: st = float(e['st'])
    except: continue
    if not (-0.5 < st < 1.5): continue
    key = 'slow' if e['course'] in '123' else 'dash'
    locst[e['regno']][key][0] += st; locst[e['regno']][key][1] += 1
st_rows = []
for reg in set(natst) | set(locst):
    row = {'regno': reg, '選手名': names.get(reg, '')}
    for key, lab in (('slow', 'スロー'), ('dash', 'ダッシュ')):
        ns, nn = natst[reg][key]; ls, ln = locst[reg][key]
        nat_avg = round(ns / nn, 3) if nn else ''; loc_avg = round(ls / ln, 3) if ln else ''
        row[f'全国{lab}n'] = nn; row[f'全国{lab}ST'] = nat_avg; row[f'当地{lab}n'] = ln; row[f'当地{lab}ST'] = loc_avg
        if ln >= 10: adopt, src = loc_avg, '当地'
        elif nn > 0: adopt, src = nat_avg, '全国'
        else: adopt, src = '', ''
        row[f'採用{lab}ST'] = adopt; row[f'{lab}源'] = src
        row[f'{lab}遅れ'] = '●' if (adopt != '' and adopt > 0.18) else ''
        row[f'{lab}巧者'] = '●' if (adopt != '' and adopt <= 0.13) else ''
    st_rows.append(row)
stf = ['regno', '選手名', '全国スローn', '全国スローST', '当地スローn', '当地スローST', '採用スローST', 'スロー源', 'スロー遅れ', 'スロー巧者',
       '全国ダッシュn', '全国ダッシュST', '当地ダッシュn', '当地ダッシュST', '採用ダッシュST', 'ダッシュ源', 'ダッシュ遅れ', 'ダッシュ巧者']
st_rows.sort(key=lambda x: x['regno'])
print('① ST表: %d人 スロー遅れ●%d 巧者●%d 当地スロー採用%d' % (len(st_rows), sum(1 for r in st_rows if r['スロー遅れ'] == '●'),
      sum(1 for r in st_rows if r['スロー巧者'] == '●'), sum(1 for r in st_rows if r['スロー源'] == '当地')))
wcsv('om_st.csv', stf, st_rows)

# ---------- ④ 絞りまくり表（当地3・4コース） ----------
by_race = defaultdict(list)
for e in ent: by_race[(e['date'], e['race'])].append(e)
shibori = defaultdict(lambda: [0, 0])
for r in races:
    for e in by_race[(r['date'], r['race'])]:
        if e['course'] in ('3', '4'):
            shibori[e['regno']][0] += 1
            if e['boat'] == r['win_boat'] and r['kimarite'] in ('まくり', 'まくり差し'): shibori[e['regno']][1] += 1
sh_rows = []
for reg, (n34, mw) in shibori.items():
    if n34 < 15: continue
    rate = mw / n34
    sh_rows.append(dict(regno=reg, 選手名=names.get(reg, ''), n34=n34, まくり系1着=mw, 率=round(rate, 3),
                        絞りまくり='●' if rate >= 0.15 else '', 暫定='暫定' if 15 <= n34 <= 19 else ''))
sh_rows.sort(key=lambda x: -x['率'])
print('④ 絞りまくり表: 15走以上%d人 ●%d人' % (len(sh_rows), sum(1 for r in sh_rows if r['絞りまくり'] == '●')))
print('  上位:', ', '.join('%s%.1f%%(n%d)' % (r['選手名'], r['率'] * 100, r['n34']) for r in sh_rows[:6]))
wcsv('om_shibori.csv', ['regno', '選手名', 'n34', 'まくり系1着', '率', '絞りまくり', '暫定'], sh_rows)

# ---------- ⑤⑥⑦・11-5 残し表 ----------
nat_out = defaultdict(lambda: [0, 0])
for r in csv.DictReader(open('nat_crank.csv')):
    if r['course'] in ('4', '5', '6'): nat_out[r['regno']][0] += int(r['n']); nat_out[r['regno']][1] += int(r['r3'])
loc_out = defaultdict(lambda: [0, 0])
for e in ent:
    if e['course'] in ('4', '5', '6'):
        loc_out[e['regno']][0] += 1
        if e['rank'] == '03': loc_out[e['regno']][1] += 1
zan1c = {r['regno']: (int(r['n1c']), int(r['lose']), int(r['p2_when_lose'])) for r in csv.DictReader(open('nat_zan1c.csv'))}
zan6 = {r['regno']: (int(r['n6']), int(r['r2']), int(r['r3'])) for r in csv.DictReader(open('nat_zan6.csv'))}
b56 = defaultdict(dict)
for r in csv.DictReader(open('nat_boat56.csv')): b56[r['regno']][r['boat']] = (int(r['san']), int(r['n']))
eff = [p2 / l for reg, (n, l, p2) in zan1c.items() if n >= 40 and l >= 20]
rv = sorted(eff); d_nokosu = rv[len(rv) * 8 // 10]; d_tobu = rv[len(rv) * 2 // 10]
print('⑥残す飛ぶ 有効%d人 残す型≥%.0f%% 飛ぶ型≤%.0f%%' % (len(eff), d_nokosu * 100, d_tobu * 100))
zrows = []
for reg in set(nat_out) | set(loc_out) | set(zan1c) | set(zan6) | set(b56):
    row = {'regno': reg, '選手名': names.get(reg, '')}
    non, nr3 = nat_out.get(reg, [0, 0]); lon, lr3 = loc_out.get(reg, [0, 0])
    row['全国外n'] = non; row['全国外3着率'] = round(nr3 / non, 3) if non else ''
    row['当地外n'] = lon; row['当地外3着率'] = round(lr3 / lon, 3) if lon else ''
    if lon >= 25: row['採用外3着率'], row['外3着源'] = row['当地外3着率'], '当地'
    elif non > 0: row['採用外3着率'], row['外3着源'] = row['全国外3着率'], '全国'
    else: row['採用外3着率'], row['外3着源'] = '', ''
    if reg in zan1c:
        n, l, p2 = zan1c[reg]; row['n1c'] = n; row['負け'] = l
        if n >= 40 and l >= 20:
            nk = p2 / l; row['残し率'] = round(nk, 3); row['残し有効'] = '●'
            row['型'] = '残す型' if nk >= d_nokosu else ('飛ぶ型' if nk <= d_tobu else '')
        else: row['残し率'] = round(p2 / l, 3) if l else ''; row['残し有効'] = ''; row['型'] = ''
    if reg in zan6:
        n6, r2, r3 = zan6[reg]; row['n6'] = n6
        row['6コ2着率'] = round(r2 / n6, 3) if n6 else ''; row['6コ3着率'] = round(r3 / n6, 3) if n6 else ''
        row['6残し有効'] = '●' if n6 >= 40 else ''
    b5 = b56[reg].get('5', (0, 0)); b6 = b56[reg].get('6', (0, 0))
    row['艇番5乗艇'] = b5[1]; row['艇番5_3連対率'] = round(b5[0] / b5[1], 3) if b5[1] else ''
    row['艇番6乗艇'] = b6[1]; row['艇番6_3連対率'] = round(b6[0] / b6[1], 3) if b6[1] else ''
    row['6ヒモ外し候補'] = '●' if (b6[1] >= 15 and b6[0] / b6[1] < 0.25) else ''
    row['艇番5低率'] = '●' if (b5[1] >= 15 and b5[0] / b5[1] < 0.25) else ''
    zrows.append(row)
zf = ['regno', '選手名', '全国外n', '全国外3着率', '当地外n', '当地外3着率', '採用外3着率', '外3着源', 'n1c', '負け', '残し率', '残し有効', '型',
      'n6', '6コ2着率', '6コ3着率', '6残し有効', '艇番5乗艇', '艇番5_3連対率', '艇番6乗艇', '艇番6_3連対率', '6ヒモ外し候補', '艇番5低率']
zrows.sort(key=lambda x: x['regno'])
print('残し表: %d人 残す型%d 飛ぶ型%d 当地外3着採用%d 6外し候補%d' % (len(zrows), sum(1 for r in zrows if r.get('型') == '残す型'),
      sum(1 for r in zrows if r.get('型') == '飛ぶ型'), sum(1 for r in zrows if r['外3着源'] == '当地'), sum(1 for r in zrows if r['6ヒモ外し候補'] == '●')))
eff2 = sorted(((r['選手名'], r['残し率']) for r in zrows if r.get('残し有効') == '●'), key=lambda x: -x[1])
print('  残す型トップ:', ', '.join('%s%.0f%%' % (n, v * 100) for n, v in eff2[:4]), '／ 飛ぶ型ワースト:', ', '.join('%s%.0f%%' % (n, v * 100) for n, v in eff2[-4:]))
wcsv('om_zanshi.csv', zf, zrows)

# ---------- ⑫ 壁表（全国12か月・2コース40走以上） ----------
wall = defaultdict(lambda: dict(n2=0, nige=0, exp=0.0, lose=0, selfwin=0, makuri=0))
for r in csv.DictReader(open('nat_wall.csv')):
    w = wall[r['c2_regno']]; w['n2'] += 1; w['exp'] += shrink(r['c1_regno'])
    if r['c1_won'] == '1': w['nige'] += 1
    else:
        w['lose'] += 1
        if r['win_course'] == '2': w['selfwin'] += 1
        if r['kimarite'] in ('まくり', 'まくり差し'): w['makuri'] += 1
wrows = []
for reg, w in wall.items():
    if w['n2'] < 40: continue
    nige = w['nige'] / w['n2']; ex = w['exp'] / w['n2']
    wrows.append(dict(regno=reg, 選手名=names.get(reg, ''), n2=w['n2'], nige=round(nige, 4), exp=round(ex, 4),
                      壁力=round((nige - ex) * 100, 1), 負けn=w['lose'],
                      自分勝ち率=round(w['selfwin'] / w['lose'], 3) if w['lose'] else '',
                      まくり決着率=round(w['makuri'] / w['lose'], 3) if w['lose'] else ''))
vals = sorted(r['壁力'] for r in wrows); hi_t = vals[len(vals) * 9 // 10]; lo_t = vals[len(vals) // 10]
for r in wrows:
    if r['壁力'] >= hi_t: r['壁'] = '壁強●'; r['弱タイプ'] = ''
    elif r['壁力'] <= lo_t:
        r['壁'] = '壁弱●'; r['弱タイプ'] = '食う型' if (r['自分勝ち率'] != '' and r['自分勝ち率'] >= 0.5) else '素通し型'
    else: r['壁'] = ''; r['弱タイプ'] = ''
wrows.sort(key=lambda x: x['壁力'])
print('⑫ 壁表: %d人 平均壁力%.2fpt 閾値 壁強≥%+.1f／壁弱≤%+.1f 壁強●%d 壁弱●%d（素通し%d・食う%d）' % (
    len(wrows), sum(r['壁力'] for r in wrows) / len(wrows), hi_t, lo_t, sum(1 for r in wrows if r['壁'] == '壁強●'),
    sum(1 for r in wrows if r['壁'] == '壁弱●'), sum(1 for r in wrows if r['弱タイプ'] == '素通し型'), sum(1 for r in wrows if r['弱タイプ'] == '食う型')))
print('  壁弱:', ', '.join('%s%+.1f(%s)' % (r['選手名'], r['壁力'], r['弱タイプ']) for r in wrows[:5]))
print('  壁強:', ', '.join('%s%+.1f' % (r['選手名'], r['壁力']) for r in wrows[-5:]))
wcsv('om_wall.csv', ['regno', '選手名', 'n2', 'nige', 'exp', '壁力', '負けn', '自分勝ち率', 'まくり決着率', '壁', '弱タイプ'], wrows)

# ---------- ⑪ モーター表（世代別） ----------
GEN_CUT = '2026-05-24'   # 現行世代の起点（5/11〜5/23の開催空白中に交換。5/24に全72機0.0%）
ent_idx = defaultdict(dict)
for e in ent: ent_idx[(e['date'], e['race'])][e['boat']] = e
def motor_table(bs, label):
    m = defaultdict(lambda: dict(n=0, r2=0, r3=0, dev=[]))
    for b in bs:
        e = ent_idx.get((b['date'], b['race']), {}).get(str(b['teiban']))
        if not e or not b['motor']: continue
        mm = m[b['motor']]; mm['n'] += 1
        if e['rank'] in ('01', '02'): mm['r2'] += 1
        if e['rank'] in ('01', '02', '03'): mm['r3'] += 1
        # 展示偏差（レース内平均との差）
        fins = ent_idx[(b['date'], b['race'])].values()
        ex = [float(x['exhib']) for x in fins if x['exhib'] not in ('', 'None', None)]
        if ex and e['exhib'] not in ('', 'None', None): mm['dev'].append(float(e['exhib']) - sum(ex) / len(ex))
    rows = []
    for mo, mm in m.items():
        rows.append(dict(motor=mo, n=mm['n'], 二連率=round(mm['r2'] / mm['n'] * 100, 1), 三連率=round(mm['r3'] / mm['n'] * 100, 1),
                         展示偏差=round(sum(mm['dev']) / len(mm['dev']), 3) if mm['dev'] else '', 判定='', 暫定=''))
    valid = sorted(r['二連率'] for r in rows if r['n'] >= 30)
    if valid:
        hi = valid[len(valid) * 8 // 10]; lo = valid[len(valid) * 2 // 10]
        for r in rows:
            if r['n'] < 30: r['暫定'] = 'n不足'
            elif r['二連率'] >= hi: r['判定'] = '高●'
            elif r['二連率'] <= lo: r['判定'] = '低▲'
        print('%s: %d機 走数中央値%d 閾値 高●≥%.1f／低▲≤%.1f 高●%d 低▲%d' % (label, len(rows), statistics.median(r['n'] for r in rows), hi, lo,
              sum(1 for r in rows if r['判定'] == '高●'), sum(1 for r in rows if r['判定'] == '低▲')))
    rows.sort(key=lambda x: -x['二連率'])
    return rows
old = motor_table([b for b in B if b['date'] < '2026-05-12'], '⑪ 旧世代（2025-09-19〜2026-05-11）')
cur = motor_table([b for b in B if b['date'] >= GEN_CUT], '⑪ 現行世代（%s〜）' % GEN_CUT)
wcsv('om_motor_oldgen.csv', ['motor', 'n', '二連率', '三連率', '展示偏差', '判定', '暫定'], old)
wcsv('om_motor_current.csv', ['motor', 'n', '二連率', '三連率', '展示偏差', '判定', '暫定'], cur)

# ---------- 残差付きレースアーカイブ（基礎率表示用） ----------
bidx = {(b['date'], b['race'], b['teiban']): b for b in B}
rrows = []
for r in races:
    if not r['c1_regno']: continue
    n, w = nat1c.get(r['c1_regno'], (0, 0)); inwin = 1 if r['c1_rank'] == '01' else 0
    ex = (w - inwin + K * P0) / (n - 1 + K)
    b1 = bidx.get((r['date'], r['race'], '1'), {})
    rrows.append(dict(date=r['date'], race=r['race'], rname=r['rname'], fixed=r['fixed'], day_n=r['day_n'], title=r['title'],
                      wdir=r['wdir'], wspd=r['wspd'], wave=r['wave'], kimarite=r['kimarite'], combo=r['combo'], payout=r['payout'],
                      ninki=r['ninki'], win_boat=r['win_boat'], win_course=r['win_course'], g1=b1.get('grade', ''),
                      exp=round(ex, 4), inwin=inwin, resid=round(inwin - ex, 4)))
wcsv('om_race_resid.csv', list(rrows[0].keys()), rrows)
# 全国地力・名前・アーカイブもコピー
for src, dst in (('nat_1c.csv', 'nat_1c.csv'), ('nat_names.csv', 'nat_names.csv'), ('omura_races.csv', 'om_races_archive.csv'),
                 ('omura_entries.csv', 'om_entries_archive.csv'), ('omura_b_entries.csv', 'om_b_archive.csv')):
    rows = list(csv.DictReader(open(src, encoding='utf-8')))
    wcsv(dst, list(rows[0].keys()), rows)
print('p0 =', round(P0, 4))
