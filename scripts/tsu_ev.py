# -*- coding: utf-8 -*-
"""津(09) EV検証 — 企画・カド消し再現・モーターの値付け

津にはレースアーカイブが無いため、Kファイルキャッシュ(data/lzh_k)から直接
レース結果（組番・払戻・レース名・艇番→登番・1号艇モーター）を復元して照合する。

検証セル（事前定義）:
 A. 企画別の1号艇: ツッキー(鉄板)／ゴールド系／非企画 … 鳴門方式
 B. カド消し再現: 4号艇がまくらない型(全国まくり力<=-4)の4頭 … 戸田の盲点(z=+4.4)の再現実験
 C. モーター: 1号艇が高●/低▲/無印の頭1 … 津固有の採用シグナル「機械の型」
 D. 2号艇壁弱●の頭2 … 平和島「型」系の対照

実行: python scripts/tsu_ev.py
"""
import os, re, csv, math, unicodedata
from collections import defaultdict
import lhafile

ODDS_DIR = 'data/odds/09'
LZH_K = 'data/lzh_k'
RACE_HDR = re.compile(r'^\s{2,}(\d{1,2})R\s+(.*?)\s+H(\d{3,4})m')
SANTAN = re.compile(r'3連単\s+([1-6]-[1-6]-[1-6])\s+(\d+)')


def is_fin(l):
    return len(l) > 21 and l[:2] == '  ' and l[6].isdigit() and l[8:12].isdigit()


def parse_tsu_day(date):
    p = f"{LZH_K}/k{date[2:4]}{date[5:7]}{date[8:10]}.lzh"
    if not os.path.exists(p):
        return []
    try:
        lf = lhafile.Lhafile(p)
        raw = lf.read(lf.infolist()[0].filename).decode('shift_jis', 'replace')
    except Exception:
        return []
    if '09KBGN' not in raw:
        return []
    blk = raw.split('09KBGN')[1].split('09KEND')[0]
    races, cur = [], None
    for ln in blk.split('\n'):
        h = RACE_HDR.match(ln)
        if h and ('風' in ln or '波' in ln):
            if cur: races.append(cur)
            cur = dict(rno=int(h.group(1)),
                       rname=unicodedata.normalize('NFKC', h.group(2)).replace(' ', '').strip(),
                       combo='', payout=0, boats={}, motor={})
            continue
        if cur is None: continue
        if is_fin(ln):
            t = ln[21:].split()
            cur['boats'][ln[6]] = ln[8:12]
            if t: cur['motor'][ln[6]] = t[0]
            continue
        sm = SANTAN.search(unicodedata.normalize('NFKC', ln))
        if sm and not cur['combo']:
            cur['combo'], cur['payout'] = sm.group(1), int(sm.group(2))
    if cur: races.append(cur)
    return [r for r in races if r['combo'] and len(r['boats']) >= 5]


def implied(om):
    inv = {c: 1.0/o for c, o in om.items() if o > 0}
    t = sum(inv.values())
    return {c: v/t for c, v in inv.items()} if t else {}


def main():
    odds = {}
    for fn in sorted(os.listdir(ODDS_DIR)):
        if not fn.endswith('.csv'): continue
        with open(os.path.join(ODDS_DIR, fn), encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row['odds']:
                    odds.setdefault((row['date'], int(row['race'])), {})[row['combo']] = float(row['odds'])
    odds = {k: v for k, v in odds.items() if len(v) >= 100}
    dates = sorted({d for d, _ in odds})

    mak = {r['登番']: r for r in csv.DictReader(open('data/toda/toda_makuriya.csv', encoding='utf-8-sig'))}
    kabe = {r[0]: r for r in list(csv.reader(open('tsu/tables/tsu_kabe.csv', encoding='utf-8-sig')))[1:]}
    kabe_hdr = next(csv.reader(open('tsu/tables/tsu_kabe.csv', encoding='utf-8-sig')))
    i_kabe = kabe_hdr.index('壁')
    motor = {r['motor']: r for r in csv.DictReader(open('tsu/tables/tsu_motor.csv', encoding='utf-8-sig'))}

    JOIN = []
    for d in dates:
        for r in parse_tsu_day(d):
            k = (d, r['rno'])
            if k in odds:
                JOIN.append((r, odds[k]))
    print('オッズ%d日 × K結果 → JOIN %dレース' % (len(dates), len(JOIN)))

    def bucket(rows, band_head, label):
        n = hit = 0; imp = ret = 0.0
        for r, om in rows:
            im = implied(om)
            p = sum(v for c, v in im.items() if c.startswith(band_head + '-'))
            if not p: continue
            n += 1; imp += p
            if r['combo'].startswith(band_head + '-'):
                hit += 1; ret += r['payout']
        if not n:
            print('  %-30s データなし' % label); return
        a, i = hit/n, imp/n
        se = math.sqrt(a*(1-a)/n) if 0 < a < 1 else 0
        print('  %-30s n=%4d 実測%5.1f%% 含意%5.1f%% 差%+5.1fpt(z=%+.1f) 頭帯ROI%6.1f%%'
              % (label, n, a*100, i*100, (i-a)*100, (i-a)/se if se else 0, ret/(n*20*100)*100))

    def sel(f):
        return [(r, om) for r, om in JOIN if f(r)]

    print()
    print('=== A. 企画別（1号艇の値付け） ===')
    bucket(sel(lambda r: 'ッキー' in r['rname']), '1', 'ツッキー(鉄板企画)')
    bucket(sel(lambda r: 'ールド' in r['rname']), '1', 'ゴールド系(5R企画)')
    bucket(sel(lambda r: 'ッキー' not in r['rname'] and 'ールド' not in r['rname']), '1', '非企画')
    print()
    print('=== B. カド消し再現（戸田の盲点 z=+4.4 は津でも起きるか） ===')
    def kado(r, lo, hi):
        m = mak.get(r['boats'].get('4', ''), None)
        if not m: return False
        p = float(m['まくり力'])
        return lo <= p <= hi
    bucket(sel(lambda r: kado(r, -99, -4)), '4', 'カド消し(まくり力<=-4)の4頭')
    bucket(sel(lambda r: (m := mak.get(r['boats'].get('4', ''))) is not None
               and float(m['実4まくり率']) >= 20 and int(m['全国4走']) >= 10), '4', 'まくり屋カドの4頭')
    bucket(sel(lambda r: (m := mak.get(r['boats'].get('4', ''))) is not None
               and float(m['まくり力']) > -4
               and not (float(m['実4まくり率']) >= 20 and int(m['全国4走']) >= 10)), '4', '対照(無印)の4頭')
    print()
    print('=== C. 1号艇モーターの型（津固有シグナル） ===')
    def mot(r, mark):
        mo = motor.get(r['motor'].get('1', ''), None)
        return bool(mo) and mo.get('判定', '') == mark
    bucket(sel(lambda r: mot(r, '高●')), '1', '1号艇=高●機の頭1')
    bucket(sel(lambda r: mot(r, '低▲')), '1', '1号艇=低▲機の頭1')
    bucket(sel(lambda r: (motor.get(r['motor'].get('1', '')) or {}).get('判定', '') == ''), '1', '1号艇=無印機の頭1')
    print()
    print('=== D. 2号艇壁弱●の頭2（型シグナルの対照） ===')
    def kb(r):
        row = kabe.get(r['boats'].get('2', ''))
        return bool(row) and row[i_kabe] == '壁弱●'
    bucket(sel(kb), '2', '2号艇=壁弱●の頭2')
    bucket(sel(lambda r: not kb(r)), '2', '対照の頭2')
    print()
    print('読み方: 差プラス=市場がその頭を過大評価/マイナス=過小評価。ROI100%超が実利の目安。')


if __name__ == '__main__':
    main()
