# -*- coding: utf-8 -*-
"""戸田カド消し（4号艇まくり力≤−4）×他シグナルの重ね掛け探索（探索的・多重比較に注意）"""
import sys, os, csv, math
sys.path.insert(0,'scripts/toda')
import ev_makuriya as E
from collections import defaultdict

odds=E.load_odds()
races={(r['date'],r['rno']):r for r in E.load(os.path.join(E.D,'toda_races.csv')) if r['santan'] and r['payout']}
ents=defaultdict(dict)
for e in E.load(os.path.join(E.D,'toda_entries.csv')): ents[(e['date'],e['rno'])][e['teiban']]=e['touban']
mak={r['登番']:r for r in E.load(os.path.join(E.D,'toda_makuriya.csv'),bom=True)}
nok={r['登番']:float(r['残し残差']) for r in E.load(os.path.join(E.D,'toda_nokoshi6.csv'),bom=True)}
keshi={tb for tb,m in mak.items() if float(m['まくり力'])<=-4}

# 全国のコース別まくり率（江戸川用に蓄積した月次カウンタから regno×course へ集約）
crs=defaultdict(lambda:[0.0,0.0])   # (regno,course) -> [n, mk1]
for r in csv.DictReader(open('data/edogawa/nat_course.csv',encoding='utf-8')):
    a=crs[(r['regno'],r['course'])]; a[0]+=float(r['n']); a[1]+=float(r['mk1'])
def atk(reg,course,min_n=15,th=0.10):
    n,mk=crs.get((reg,str(course)),(0,0))
    return n>=min_n and mk/n>=th

# カド消しレースの抽出
KS=[]
for k,r in races.items():
    if k not in odds or k not in ents: continue
    b=ents[k]
    if b.get('4') in keshi: KS.append((k,r,b))
print('カド消しレース n=%d'%len(KS))

def head_stats(rows,label):
    print('  --- %s (n=%d) ---'%(label,len(rows)))
    print('   頭  実測    含意    差      頭帯ROI')
    for h in '123456':
        n=hit=0; imp=ret=cost=0.0
        for k,r,b in rows:
            im=E.implied(odds[k]); p=sum(v for c,v in im.items() if c.startswith(h+'-'))
            if not p: continue
            band=[c for c in odds[k] if c[0].startswith(h) and c[1]=='-']
            band=[c for c in im if c.startswith(h+'-')]
            n+=1; imp+=p
            cost+=len(band)*100
            if r['santan'].startswith(h+'-'): hit+=1; ret+=int(r['payout'])
        if not n: continue
        a,i=hit/n,imp/n; se=math.sqrt(a*(1-a)/n) if 0<a<1 else 0
        print('   %s  %5.1f%%  %5.1f%%  %+5.1fpt(z=%+.1f)  %6.1f%%'%(h,a*100,i*100,(i-a)*100,(i-a)/se if se else 0,ret/cost*100 if cost else 0))

head_stats(KS,'カド消し全体')
# 重ね掛け
L6=[(k,r,b) for k,r,b in KS if b.get('6') and nok.get(b['6'],0)>=6]
head_stats(L6,'カド消し × 6残す')
A3=[(k,r,b) for k,r,b in KS if b.get('3') and atk(b['3'],3)]
head_stats(A3,'カド消し × 3号艇が3コース攻め手(まくり率>=10%)')
A5=[(k,r,b) for k,r,b in KS if b.get('5') and atk(b['5'],5,th=0.05)]
head_stats(A5,'カド消し × 5号艇が5コース攻め手(まくり率>=5%)')
# 6残す時の6のヒモ値付け
def pos_stats(rows,pos,boat,label):
    n=hit=0; imp=ret=cost=0.0
    for k,r,b in rows:
        im=E.implied(odds[k]); p=sum(v for c,v in im.items() if c.split('-')[pos-1]==boat)
        if not p: continue
        n+=1; imp+=p; cost+=2000
        if r['santan'].split('-')[pos-1]==boat: hit+=1; ret+=int(r['payout'])
    if not n: print('  %s 該当なし'%label); return
    a,i=hit/n,imp/n
    print('  %-32s n=%3d 実測%5.1f%% 含意%5.1f%% 差%+5.1fpt ROI%6.1f%%'%(label,n,a*100,i*100,(i-a)*100,ret/cost*100))
print()
print('=== ヒモ側 ===')
pos_stats(KS,2,'6','カド消し×6号艇2着')
pos_stats(L6,2,'6','カド消し×6残す×6号艇2着')
pos_stats(KS,2,'1','カド消し×1号艇2着')
