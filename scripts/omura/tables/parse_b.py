# -*- coding: utf-8 -*-
"""Bファイル（番組表）365日から大村(24)ブロックを抽出 → omura_b_entries.csv
   列: date,race,rname,fixed,deadline,teiban,regno,name,age,branch,weight,grade,
       nat_win,nat_2,loc_win,loc_2,motor,motor2,boat,boat2
   選手行の固定幅は平和島 daily_build_hw.py と同じ（ln[0]=艇番 / ln[2:6]=登番 / ln[6:10]=氏名 / ln[16:18]=級）"""
import lhafile, glob, re, csv, unicodedata

JCD = '24'
BOAT_RE = re.compile(r'^([1-6]) (\d{4})(.{4})(\d{2})(..)(\d{2})([AB][12])(.*)$')
RATE_RE = re.compile(r'(\d+\.\d\d)\s+(\d+\.\d\d)\s+(\d+\.\d\d)\s+(\d+\.\d\d)\s+(\d+)\s+(\d+\.\d\d)\s+(\d+)\s+(\d+\.\d\d)')
HEAD_RE = re.compile(r'^\s*(\d{1,2})R\s+(\S+)(.*)$')
DEADLINE_RE = re.compile(r'締切予定\s*(\d{1,2}:\d{2})')

rows = []
for f in sorted(glob.glob('lzh_b/b??????.lzh')):
    ymd = f.split('b')[-1].split('.')[0]
    date = f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}"
    try:
        lf = lhafile.Lhafile(f)
        raw = lf.read(lf.infolist()[0].filename).decode('shift_jis', errors='replace')
    except Exception as e:
        print('ERR', f, e); continue
    m = re.search(r'%sBBGN(.*?)%sBEND' % (JCD, JCD), raw, re.S)
    if not m: continue
    cur = None
    for ln in m.group(1).split('\n'):
        ln = ln.rstrip('\r')
        n = unicodedata.normalize('NFKC', ln)
        mh = HEAD_RE.match(n)
        if mh and ('締切' in n or 'H' in n):
            md = DEADLINE_RE.search(n)
            cur = dict(race=int(mh.group(1)), rname=mh.group(2),
                       fixed=1 if '進入固定' in n else 0,
                       deadline=md.group(1) if md else '')
            continue
        mb = BOAT_RE.match(ln)
        if mb and cur is not None:
            mr = RATE_RE.search(unicodedata.normalize('NFKC', mb.group(8)))
            rows.append(dict(date=date, race=cur['race'], rname=cur['rname'], fixed=cur['fixed'],
                             deadline=cur['deadline'], teiban=int(ln[0]), regno=ln[2:6],
                             name=ln[6:10].replace('　', '').strip(), age=mb.group(4),
                             branch=mb.group(5), weight=mb.group(6), grade=mb.group(7),
                             nat_win=mr.group(1) if mr else '', nat_2=mr.group(2) if mr else '',
                             loc_win=mr.group(3) if mr else '', loc_2=mr.group(4) if mr else '',
                             motor=mr.group(5) if mr else '', motor2=mr.group(6) if mr else '',
                             boat=mr.group(7) if mr else '', boat2=mr.group(8) if mr else ''))
with open('omura_b_entries.csv', 'w', newline='', encoding='utf-8') as fo:
    w = csv.DictWriter(fo, fieldnames=list(rows[0].keys())); w.writeheader()
    for r in rows: w.writerow(r)
print('B行数', len(rows), '日数', len(set(r['date'] for r in rows)), 'レース', len(set((r['date'], r['race']) for r in rows)))
