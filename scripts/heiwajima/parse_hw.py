# -*- coding: utf-8 -*-
"""Kファイルのパース：全国1コース地力表（同一窓）＋平和島(04)詳細"""
import lhafile, glob, re, csv, unicodedata
from collections import defaultdict

RE_HEADER = re.compile(r'^\s{0,6}(\d{1,2})R\s+(\S+)\s+H(\d+)m(.*)$')
RE_WIND = re.compile(r'風[\s\u3000]*([東西南北]{1,3})?[\s\u3000]*(\d+)m')
RE_WAVE = re.compile(r'波[\s\u3000]*(\d+)cm')
RE_DAY = re.compile(r'第\s*(\d+)\s*日')
RE_PAYTOP = re.compile(r'^\s+(\d{1,2})R\s+([1-6]-[1-6]-[1-6])\s+(\d+)')

TARGET = '04'  # 平和島

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
    name = line[13:21].replace('\u3000', '').strip()
    tail = line[21:].split()
    motor = exhib = course = st = None
    if len(tail) >= 5:
        motor = tail[0]
        try: exhib = float(tail[2])
        except: exhib = None
        c = tail[3]
        if len(c) == 1 and c in '123456': course = c
        st = tail[4]
    return dict(rank=rank, boat=boat, regno=regno, name=name,
                motor=motor, exhib=exhib, course=course, st=st)

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
            if r not in payouts:
                payouts[r] = (mp.group(2), int(mp.group(3)))
            continue
        mh = RE_HEADER.match(ln)
        if mh and ('m' in ln):
            if cur: races.append(cur)
            rest = mh.group(4)
            mw = RE_WIND.search(rest)
            wdir = mw.group(1) if (mw and mw.group(1)) else None
            wspd = int(mw.group(2)) if mw else None
            mv = RE_WAVE.search(rest)
            wave = int(mv.group(1)) if mv else None
            weather = rest.split()[0].replace('\u3000','') if rest.split() else ''
            cur = dict(race=int(mh.group(1)), name=mh.group(2),
                       dist=int(mh.group(3)), weather=weather,
                       wdir=wdir, wspd=wspd, wave=wave, kimarite=None, fins=[])
            continue
        if cur is not None and cur['kimarite'] is None and 'ﾚｰｽﾀｲﾑ' in ln:
            k = ln.split('ﾚｰｽﾀｲﾑ')[-1].replace('\u3000','').strip()
            cur['kimarite'] = k if k else None
            continue
        if cur is not None and is_finisher(ln):
            cur['fins'].append(parse_finisher(ln))
    if cur: races.append(cur)
    races = [r for r in races if len(r['fins']) >= 4]
    return day_n, title, payouts, races

def main():
    nat = defaultdict(lambda: [0, 0])  # regno -> [n1c, win1c]  全国
    hw_races = []; hw_entries = []
    hw_days = set()
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
            # 全国1コース地力（全会場）
            for r in races:
                c1 = [x for x in r['fins'] if x['course'] == '1']
                if len(c1) == 1:
                    reg = c1[0]['regno']
                    nat[reg][0] += 1
                    if c1[0]['rank'] == '01': nat[reg][1] += 1
            if jcd == TARGET:
                hw_days.add(date)
                for r in races:
                    combo, amt = payouts.get(r['race'], (None, None))
                    c1 = [x for x in r['fins'] if x['course'] == '1']
                    win = [x for x in r['fins'] if x['rank'] == '01']
                    hw_races.append(dict(
                        date=date, race=r['race'], rname=r['name'], day_n=day_n,
                        title=title, weather=r['weather'], wdir=r['wdir'] or '',
                        wspd=r['wspd'] if r['wspd'] is not None else '',
                        wave=r['wave'] if r['wave'] is not None else '',
                        kimarite=r['kimarite'] or '',
                        combo=combo or '', payout=amt if amt else '',
                        c1_regno=c1[0]['regno'] if len(c1)==1 else '',
                        c1_rank=c1[0]['rank'] if len(c1)==1 else '',
                        win_boat=win[0]['boat'] if win else '',
                        win_course=win[0]['course'] if win else '',
                        n_fins=len(r['fins'])))
                    for x in r['fins']:
                        hw_entries.append(dict(date=date, race=r['race'], **x))
    # 出力
    with open('national_1c_hw.csv', 'w', newline='') as fo:
        w = csv.writer(fo); w.writerow(['touban','n1c','win1c'])
        for reg,(n,win) in sorted(nat.items()): w.writerow([reg,n,win])
    with open('heiwajima_races.csv', 'w', newline='') as fo:
        w = csv.DictWriter(fo, fieldnames=list(hw_races[0].keys())); w.writeheader()
        for r in hw_races: w.writerow(r)
    with open('heiwajima_entries.csv', 'w', newline='') as fo:
        w = csv.DictWriter(fo, fieldnames=list(hw_entries[0].keys())); w.writeheader()
        for r in hw_entries: w.writerow(r)
    print('全国選手数:', len(nat))
    print('平和島 開催日:', len(hw_days), 'レース:', len(hw_races), 'エントリー:', len(hw_entries))

if __name__ == '__main__':
    main()
