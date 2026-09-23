# -*- coding: utf-8 -*-
"""大村(24) 穴党ツール — Kファイル365日から1パスで抽出

出力（カレントディレクトリ）:
  omura_races.csv    大村レース単位（結果・配当・3連単人気・風・決まり手）
  omura_entries.csv  大村エントリー単位（着・艇・登番・進入・ST・展示・モーター）
  nat_races.csv      全場レース単位（jcd付き。全国ベースライン用）
  nat_1c.csv         全国1コース地力（touban,n1c,win1c）
  nat_st.csv         全国 進入コース別 平均ST
  nat_zan1c.csv      ⑥1号艇 残す/飛ぶ
  nat_zan6.csv       ⑦6コース残し
  nat_boat56.csv     11-5 艇番5/6 3連対
  nat_wall.csv       ⑫壁力 レース行
  nat_crank.csv      進入コース別 着別カウント（⑤外3着用）
  nat_names.csv      登番→氏名
  nat_c2sashi.csv    2コース差し（n2c,win2c,sashi_win）
平和島の parse_hw.py / nat_extract_hw.py と同じ解釈規則（固定幅の選手行・NFKC）。
"""
import lhafile, glob, re, csv, unicodedata, sys
from collections import defaultdict

TARGET = '24'   # 大村

RE_HEADER = re.compile(r'^\s{0,6}(\d{1,2})R\s+(\S+)[\s\u3000]*(進入固定|[^\sH]{2,8})?\s*H(\d+)m(.*)$')
RE_WIND = re.compile(r'風[\s　]*([東西南北]{1,3})?[\s　]*(\d+)m')
RE_WAVE = re.compile(r'波[\s　]*(\d+)cm')
RE_DAY = re.compile(r'第\s*(\d+)\s*日')
RE_PAYTOP = re.compile(r'^\s+(\d{1,2})R\s+([1-6]-[1-6]-[1-6])\s+(\d+)')
RE_SANTAN = re.compile(r'３連単\s+([1-6]-[1-6]-[1-6])\s+(\d+)\s+人気\s+(\d+)')
RE_NITAN = re.compile(r'２連単\s+([1-6]-[1-6])\s+(\d+)\s+人気\s+(\d+)')
RE_TANSHO = re.compile(r'単勝\s+([1-6])\s+(\d+)')


def is_finisher(line):
    if len(line) < 30: return False
    if line[0:2] != '  ': return False
    if not line[6:7].isdigit(): return False
    if not line[8:12].isdigit(): return False
    return True


def parse_finisher(line):
    rank = line[2:4].strip()
    boat = line[6]
    regno = line[8:12]
    name = line[13:21].replace('　', '').strip()
    tail = line[21:].split()
    motor = boatno = exhib = course = st = None
    if len(tail) >= 5:
        motor = tail[0]; boatno = tail[1]
        try: exhib = float(tail[2])
        except: exhib = None
        c = tail[3]
        if len(c) == 1 and c in '123456': course = c
        st = tail[4]
    return dict(rank=rank, boat=boat, regno=regno, name=name, motor=motor,
                boatno=boatno, exhib=exhib, course=course, st=st)


def parse_venue_block(blk):
    lines = blk.split('\n')
    day_n = None; title = ''
    payouts = {}; races = []; cur = None
    for i, ln in enumerate(lines):
        ln = ln.rstrip('\r')
        if day_n is None:
            m = RE_DAY.search(unicodedata.normalize('NFKC', ln))
            if m and ('日' in ln): day_n = int(m.group(1))
        if i == 5 and ln.strip(): title = ln.strip()
        mp = RE_PAYTOP.match(ln)
        if mp and 'H' not in ln:
            r = int(mp.group(1))
            if r not in payouts: payouts[r] = (mp.group(2), int(mp.group(3)))
            continue
        mh = RE_HEADER.match(ln)
        if mh and ('m' in ln):
            if cur: races.append(cur)
            rest = mh.group(5)
            fixed = 1 if (mh.group(3) and '進入固定' in mh.group(3)) else 0
            mw = RE_WIND.search(rest)
            wdir = mw.group(1) if (mw and mw.group(1)) else None
            wspd = int(mw.group(2)) if mw else None
            mv = RE_WAVE.search(rest)
            wave = int(mv.group(1)) if mv else None
            weather = rest.split()[0].replace('　', '') if rest.split() else ''
            cur = dict(race=int(mh.group(1)), name=mh.group(2), dist=int(mh.group(4)), fixed=fixed,
                       weather=weather, wdir=wdir, wspd=wspd, wave=wave, kimarite=None,
                       fins=[], santan=None, nitan=None, tansho=None)
            continue
        if cur is not None and cur['kimarite'] is None and 'ﾚｰｽﾀｲﾑ' in ln:
            k = ln.split('ﾚｰｽﾀｸﾞ')[-1] if False else ln.split('ﾚｰｽﾀｲﾑ')[-1]
            k = k.replace('　', '').strip()
            cur['kimarite'] = k if k else None
            continue
        if cur is not None and is_finisher(ln):
            cur['fins'].append(parse_finisher(ln)); continue
        if cur is not None:
            ms = RE_SANTAN.search(ln)
            if ms: cur['santan'] = (ms.group(1), int(ms.group(2)), int(ms.group(3))); continue
            mn = RE_NITAN.search(ln)
            if mn: cur['nitan'] = (mn.group(1), int(mn.group(2)), int(mn.group(3))); continue
            mt = RE_TANSHO.search(ln)
            if mt and cur['tansho'] is None: cur['tansho'] = (mt.group(1), int(mt.group(2)))
    if cur: races.append(cur)
    races = [r for r in races if len(r['fins']) >= 4]
    return day_n, title, payouts, races


def main():
    nat = defaultdict(lambda: [0, 0])
    st_nat = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    zan1c = defaultdict(lambda: [0, 0, 0])
    zan6 = defaultdict(lambda: [0, 0, 0])
    boat56 = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    crank = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))  # regno->course->[n,r1,r2,r3]
    c2s = defaultdict(lambda: [0, 0, 0])
    names = {}
    wall_rows = []; nat_races = []
    om_races = []; om_entries = []; om_days = set()

    kfiles = sorted(glob.glob('lzh_k/k??????.lzh'))
    for f in kfiles:
        ymd = f.split('k')[-1].split('.')[0]
        date = f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}"
        try:
            lf = lhafile.Lhafile(f)
            raw = lf.read(lf.infolist()[0].filename).decode('shift_jis', errors='replace')
        except Exception as e:
            print('ERR', f, e); continue
        for m in re.finditer(r'(\d{2})KBGN(.*?)\1KEND', raw, re.S):
            jcd, blk = m.group(1), m.group(2)
            day_n, title, payouts, races = parse_venue_block(blk)
            for r in races:
                fins = r['fins']; km = r['kimarite']
                byc = {x['course']: x for x in fins if x['course']}
                win = [x for x in fins if x['rank'] == '01']
                win_course = win[0]['course'] if win else None
                for x in fins:
                    names.setdefault(x['regno'], x['name'])
                    if x['course']:
                        cr = crank[x['regno']][x['course']]; cr[0] += 1
                        if x['rank'] in ('01', '02', '03'): cr[int(x['rank'])] += 1
                        try:
                            stv = float(x['st'])
                            if -0.5 < stv < 1.5:
                                st_nat[x['regno']][x['course']][0] += stv
                                st_nat[x['regno']][x['course']][1] += 1
                        except (TypeError, ValueError):
                            pass
                    if x['boat'] in ('5', '6'):
                        boat56[x['regno']][x['boat']][1] += 1
                        if x['rank'] in ('01', '02', '03'): boat56[x['regno']][x['boat']][0] += 1
                if '1' in byc:
                    c1 = byc['1']
                    nat[c1['regno']][0] += 1
                    if c1['rank'] == '01': nat[c1['regno']][1] += 1
                    zan1c[c1['regno']][0] += 1
                    if c1['rank'] != '01':
                        zan1c[c1['regno']][1] += 1
                        if c1['rank'] == '02': zan1c[c1['regno']][2] += 1
                if '6' in byc:
                    c6 = byc['6']; zan6[c6['regno']][0] += 1
                    if c6['rank'] == '02': zan6[c6['regno']][1] += 1
                    elif c6['rank'] == '03': zan6[c6['regno']][2] += 1
                if '2' in byc:
                    c2 = byc['2']; c2s[c2['regno']][0] += 1
                    if c2['rank'] == '01':
                        c2s[c2['regno']][1] += 1
                        if km == '差し': c2s[c2['regno']][2] += 1
                if '1' in byc and '2' in byc and win_course:
                    wall_rows.append((byc['2']['regno'], byc['1']['regno'],
                                      1 if byc['1']['rank'] == '01' else 0, win_course, km or ''))
                combo, amt = payouts.get(r['race'], (None, None))
                st3 = r['santan'] or (None, None, None)
                nat_races.append(dict(jcd=jcd, date=date, race=r['race'], rname=r['name'], fixed=r['fixed'], day_n=day_n or '',
                                      wdir=r['wdir'] or '', wspd=r['wspd'] if r['wspd'] is not None else '',
                                      kimarite=km or '', win_course=win_course or '',
                                      combo=combo or (st3[0] or ''), payout=amt or (st3[1] or ''),
                                      ninki=st3[2] or '',
                                      c1_regno=byc['1']['regno'] if '1' in byc else '',
                                      c1_rank=byc['1']['rank'] if '1' in byc else ''))
                if jcd == TARGET:
                    om_days.add(date)
                    nt = r['nitan'] or (None, None, None); ts = r['tansho'] or (None, None)
                    om_races.append(dict(
                        date=date, race=r['race'], rname=r['name'], fixed=r['fixed'], day_n=day_n or '', title=title,
                        weather=r['weather'], wdir=r['wdir'] or '',
                        wspd=r['wspd'] if r['wspd'] is not None else '',
                        wave=r['wave'] if r['wave'] is not None else '', kimarite=km or '',
                        combo=combo or (st3[0] or ''), payout=amt or (st3[1] or ''), ninki=st3[2] or '',
                        nitan=nt[0] or '', nitan_pay=nt[1] or '', nitan_ninki=nt[2] or '',
                        tansho_pay=ts[1] or '',
                        c1_regno=byc['1']['regno'] if '1' in byc else '',
                        c1_rank=byc['1']['rank'] if '1' in byc else '',
                        win_boat=win[0]['boat'] if win else '', win_course=win_course or '',
                        n_fins=len(fins)))
                    for x in fins:
                        om_entries.append(dict(date=date, race=r['race'], **x))

    def wcsv(name, header, rows):
        with open(name, 'w', newline='', encoding='utf-8') as fo:
            w = csv.writer(fo); w.writerow(header)
            for row in rows: w.writerow(row)

    wcsv('nat_1c.csv', ['touban', 'n1c', 'win1c'], [[k, *v] for k, v in sorted(nat.items())])
    wcsv('nat_st.csv', ['regno', 'course', 'st_avg', 'n'],
         [[reg, c, round(s / n, 4), n] for reg, cd in st_nat.items() for c, (s, n) in cd.items() if n > 0])
    wcsv('nat_zan1c.csv', ['regno', 'n1c', 'lose', 'p2_when_lose'], [[k, *v] for k, v in zan1c.items()])
    wcsv('nat_zan6.csv', ['regno', 'n6', 'r2', 'r3'], [[k, *v] for k, v in zan6.items()])
    wcsv('nat_boat56.csv', ['regno', 'boat', 'san', 'n'],
         [[reg, b, s, n] for reg, bd in boat56.items() for b, (s, n) in bd.items()])
    wcsv('nat_wall.csv', ['c2_regno', 'c1_regno', 'c1_won', 'win_course', 'kimarite'], wall_rows)
    wcsv('nat_crank.csv', ['regno', 'course', 'n', 'r1', 'r2', 'r3'],
         [[reg, c, *v] for reg, cd in crank.items() for c, v in cd.items()])
    wcsv('nat_names.csv', ['regno', 'name'], sorted(names.items()))
    wcsv('nat_c2sashi.csv', ['regno', 'n2c', 'win2c', 'sashi_win'], [[k, *v] for k, v in c2s.items()])
    for name, rows in (('nat_races.csv', nat_races), ('omura_races.csv', om_races), ('omura_entries.csv', om_entries)):
        with open(name, 'w', newline='', encoding='utf-8') as fo:
            w = csv.DictWriter(fo, fieldnames=list(rows[0].keys())); w.writeheader()
            for r in rows: w.writerow(r)
    print('Kファイル:', len(kfiles), '全国レース:', len(nat_races), '全国選手:', len(nat))
    print('大村 開催日:', len(om_days), 'レース:', len(om_races), 'エントリー:', len(om_entries))


if __name__ == '__main__':
    main()
