import csv
from collections import defaultdict
names={r['regno']:r['name'] for r in csv.DictReader(open('nat_names.csv'))}
ent=list(csv.DictReader(open('heiwajima_entries.csv')))

# ⑤外3着：全国（courses4-6）
nat_out=defaultdict(lambda:[0,0])  # regno->[n_out, r3]
for r in csv.DictReader(open('nat_crank.csv')):
    if r['course'] in ('4','5','6'):
        nat_out[r['regno']][0]+=int(r['n']); nat_out[r['regno']][1]+=int(r['r3'])
# ⑤外3着：当地
loc_out=defaultdict(lambda:[0,0])
for e in ent:
    if e['course'] in ('4','5','6'):
        loc_out[e['regno']][0]+=1
        if e['rank']=='03': loc_out[e['regno']][1]+=1
# ⑥残す飛ぶ
zan1c={r['regno']:(int(r['n1c']),int(r['lose']),int(r['p2_when_lose'])) for r in csv.DictReader(open('nat_zan1c.csv'))}
# ⑦6残し
zan6={r['regno']:(int(r['n6']),int(r['r2']),int(r['r3'])) for r in csv.DictReader(open('nat_zan6.csv'))}
# 11-5 艇番5/6
b56=defaultdict(dict)
for r in csv.DictReader(open('nat_boat56.csv')):
    b56[r['regno']][r['boat']]=(int(r['san']),int(r['n']))

# デシル閾値（⑥残す飛ぶ・有効n1c40+ lose20+）
eff=[(reg,p2/l) for reg,(n,l,p2) in zan1c.items() if n>=40 and l>=20]
rv=sorted(x[1] for x in eff)
d_nokosu=rv[len(rv)*8//10] if rv else 0.63  # 上位20%
d_tobu=rv[len(rv)*2//10] if rv else 0.32
print('⑥残す飛ぶ 有効%d人 残す型≥%.0f%% 飛ぶ型≤%.0f%%'%(len(eff),d_nokosu*100,d_tobu*100))

regs=set(nat_out)|set(loc_out)|set(zan1c)|set(zan6)|set(b56)
rows=[]
for reg in regs:
    row={'regno':reg,'選手名':names.get(reg,'')}
    # ⑤
    non,nr3=nat_out.get(reg,[0,0]); lon,lr3=loc_out.get(reg,[0,0])
    row['全国外n']=non; row['全国外3着率']=round(nr3/non,3) if non else ''
    row['当地外n']=lon; row['当地外3着率']=round(lr3/lon,3) if lon else ''
    if lon>=25: row['採用外3着率']=row['当地外3着率']; row['外3着源']='当地'
    elif non>0: row['採用外3着率']=row['全国外3着率']; row['外3着源']='全国'
    else: row['採用外3着率']=''; row['外3着源']=''
    # ⑥
    if reg in zan1c:
        n,l,p2=zan1c[reg]; row['n1c']=n; row['負け']=l
        if n>=40 and l>=20:
            nk=p2/l; row['残し率']=round(nk,3); row['残し有効']='●'
            row['型']='残す型' if nk>=d_nokosu else ('飛ぶ型' if nk<=d_tobu else '')
        else: row['残し率']=round(p2/l,3) if l else ''; row['残し有効']=''; row['型']=''
    # ⑦
    if reg in zan6:
        n6,r2,r3=zan6[reg]; row['n6']=n6
        row['6コ2着率']=round(r2/n6,3) if n6 else ''; row['6コ3着率']=round(r3/n6,3) if n6 else ''
        row['6残し有効']='●' if n6>=40 else ''
    # 11-5
    b5=b56[reg].get('5',(0,0)); b6=b56[reg].get('6',(0,0))
    row['艇番5乗艇']=b5[1]; row['艇番5_3連対率']=round(b5[0]/b5[1],3) if b5[1] else ''
    row['艇番6乗艇']=b6[1]; row['艇番6_3連対率']=round(b6[0]/b6[1],3) if b6[1] else ''
    row['6ヒモ外し候補']='●' if (b6[1]>=15 and b6[0]/b6[1]<0.25) else ''
    row['艇番5低率']='●' if (b5[1]>=15 and b5[0]/b5[1]<0.25) else ''
    rows.append(row)
zf=['regno','選手名','全国外n','全国外3着率','当地外n','当地外3着率','採用外3着率','外3着源','n1c','負け','残し率','残し有効','型','n6','6コ2着率','6コ3着率','6残し有効','艇番5乗艇','艇番5_3連対率','艇番6乗艇','艇番6_3連対率','6ヒモ外し候補','艇番5低率']
with open('平和島_残し表.csv','w',newline='') as fo:
    w=csv.DictWriter(fo,fieldnames=zf,extrasaction='ignore'); w.writeheader()
    for r in sorted(rows,key=lambda x:x['regno']): w.writerow(r)
nk=sum(1 for r in rows if r.get('型')=='残す型'); tb=sum(1 for r in rows if r.get('型')=='飛ぶ型')
o25=sum(1 for r in rows if r['外3着源']=='当地')
print('残し表: %d人 残す型%d 飛ぶ型%d 当地外3着採用%d'%(len(rows),nk,tb,o25))
# トップ残す/飛ぶ
eff2=[(r['選手名'],r['残し率']) for r in rows if r.get('残し有効')=='●']
eff2.sort(key=lambda x:-x[1])
print('  残す型トップ:', ', '.join('%s%.0f%%'%(n,v*100) for n,v in eff2[:3]))
print('  飛ぶ型ワースト:', ', '.join('%s%.0f%%'%(n,v*100) for n,v in eff2[-3:]))
