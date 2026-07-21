# -*- coding: utf-8 -*-
"""全国K 365日から艇別テーブル用の集計を1パスで抽出（丸亀§3 ⑥⑦⑫・ST全国・11-5）"""
import lhafile, glob, re, csv, unicodedata
from collections import defaultdict

RE_HEADER = re.compile(r'^\s{0,6}(\d{1,2})R\s+(\S+)\s+H(\d+)m(.*)$')
RE_PAYTOP = re.compile(r'^\s+(\d{1,2})R\s+([1-6]-[1-6]-[1-6])\s+(\d+)')

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
    tail = line[21:].split()
    course = st = None
    if len(tail) >= 5:
        c = tail[3]
        if len(c) == 1 and c in '123456': course = c
        try: st = float(tail[4])
        except: st = None
    return dict(rank=rank, boat=boat, regno=regno, course=course, st=st)

def parse_block(blk):
    lines = blk.split('\n'); races=[]; cur=None
    for ln in lines:
        ln = ln.rstrip('\r')
        mh = RE_HEADER.match(ln)
        if mh and ('m' in ln):
            if cur: races.append(cur)
            cur = dict(kimarite=None, fins=[]); continue
        if cur is not None and cur['kimarite'] is None and 'ﾚｰｽﾀｲﾑ' in ln:
            k = ln.split('ﾚｰｽﾀｲﾑ')[-1].replace('\u3000','').strip()
            cur['kimarite']=k if k else None; continue
        if cur is not None and is_finisher(ln):
            cur['fins'].append(parse_finisher(ln))
    if cur: races.append(cur)
    return [r for r in races if len(r['fins'])>=4]

# 集計器
st_nat = defaultdict(lambda: defaultdict(lambda:[0.0,0]))   # regno->course->[st_sum,n]
zan1c  = defaultdict(lambda:[0,0,0])   # regno-> [n1c, lose(1着以外), 2着when_lose]
zan6   = defaultdict(lambda:[0,0,0])   # regno-> [n6, 2着, 3着]
boat56 = defaultdict(lambda: defaultdict(lambda:[0,0]))  # regno->boat->[sanrentai, n]
# 壁力：各レースの (2c_regno, 1c_regno, 1c_won, win_course, kimarite)
wall_rows = []

kfiles = sorted(glob.glob('lzh_k/k??????.lzh'))
for f in kfiles:
    try:
        lf=lhafile.Lhafile(f)
        raw=lf.read(lf.infolist()[0].filename).decode('shift_jis',errors='replace')
    except Exception as e:
        print('ERR',f,e); continue
    for m in re.finditer(r'(\d{2})KBGN(.*?)\1KEND', raw, re.S):
        for r in parse_block(m.group(2)):
            fins=r['fins']; km=r['kimarite']
            byc={x['course']:x for x in fins if x['course']}
            win=[x for x in fins if x['rank']=='01']
            win_course = win[0]['course'] if win else None
            # ST全国
            for x in fins:
                if x['course'] and x['st'] is not None and -0.5<x['st']<1.5:
                    st_nat[x['regno']][x['course']][0]+=x['st']
                    st_nat[x['regno']][x['course']][1]+=1
            # 艇番5/6 3連対
            for x in fins:
                if x['boat'] in ('5','6'):
                    boat56[x['regno']][x['boat']][1]+=1
                    if x['rank'] in ('01','02','03'): boat56[x['regno']][x['boat']][0]+=1
            # ⑥1号艇残す/飛ぶ
            if '1' in byc:
                c1=byc['1']; zan1c[c1['regno']][0]+=1
                if c1['rank']!='01':
                    zan1c[c1['regno']][1]+=1
                    if c1['rank']=='02': zan1c[c1['regno']][2]+=1
            # ⑦6コース残し
            if '6' in byc:
                c6=byc['6']; zan6[c6['regno']][0]+=1
                if c6['rank']=='02': zan6[c6['regno']][1]+=1
                elif c6['rank']=='03': zan6[c6['regno']][2]+=1
            # ⑫壁力（1cと2c両方確定・勝者確定のレース）
            if '1' in byc and '2' in byc and win_course:
                c1=byc['1']; c2=byc['2']
                wall_rows.append((c2['regno'], c1['regno'],
                                  1 if c1['rank']=='01' else 0,
                                  win_course, km or ''))

# 出力
with open('nat_st.csv','w',newline='') as fo:
    w=csv.writer(fo); w.writerow(['regno','course','st_avg','n'])
    for reg,cd in st_nat.items():
        for c,(s,n) in cd.items():
            if n>0: w.writerow([reg,c,round(s/n,4),n])
with open('nat_zan1c.csv','w',newline='') as fo:
    w=csv.writer(fo); w.writerow(['regno','n1c','lose','p2_when_lose'])
    for reg,(n,l,p2) in zan1c.items(): w.writerow([reg,n,l,p2])
with open('nat_zan6.csv','w',newline='') as fo:
    w=csv.writer(fo); w.writerow(['regno','n6','r2','r3'])
    for reg,(n,r2,r3) in zan6.items(): w.writerow([reg,n,r2,r3])
with open('nat_boat56.csv','w',newline='') as fo:
    w=csv.writer(fo); w.writerow(['regno','boat','san','n'])
    for reg,bd in boat56.items():
        for b,(s,n) in bd.items(): w.writerow([reg,b,s,n])
with open('nat_wall.csv','w',newline='') as fo:
    w=csv.writer(fo); w.writerow(['c2_regno','c1_regno','c1_won','win_course','kimarite'])
    for row in wall_rows: w.writerow(row)
print('ST全国選手:', len(st_nat), '/ 残す飛ぶ:', len(zan1c), '/ 6残し:', len(zan6),
      '/ 艇番56:', len(boat56), '/ 壁レース:', len(wall_rows))

if __name__=='__main__': pass
