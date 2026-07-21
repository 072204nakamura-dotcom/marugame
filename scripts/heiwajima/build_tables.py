import csv
from collections import defaultdict
names={r['regno']:r['name'] for r in csv.DictReader(open('nat_names.csv'))}
ent=list(csv.DictReader(open('heiwajima_entries.csv')))
races=list(csv.DictReader(open('heiwajima_races.csv')))

# ---------- ① ST表 ----------
natst=defaultdict(lambda:{'slow':[0.0,0],'dash':[0.0,0]})
for r in csv.DictReader(open('nat_st.csv')):
    reg=r['regno']; c=r['course']; av=float(r['st_avg']); n=int(r['n'])
    key='slow' if c in '123' else 'dash'
    natst[reg][key][0]+=av*n; natst[reg][key][1]+=n
locst=defaultdict(lambda:{'slow':[0.0,0],'dash':[0.0,0]})
for e in ent:
    if not e['course'] or e['st'] in ('','L','F'): continue
    try: st=float(e['st'])
    except: continue
    if not(-0.5<st<1.5): continue
    key='slow' if e['course'] in '123' else 'dash'
    locst[e['regno']][key][0]+=st; locst[e['regno']][key][1]+=1
regs=set(natst)|set(locst)
st_rows=[]
for reg in regs:
    row={'regno':reg,'選手名':names.get(reg,'')}
    for key,lab in [('slow','スロー'),('dash','ダッシュ')]:
        ns,nn=natst[reg][key]; ls,ln=locst[reg][key]
        nat_avg=round(ns/nn,3) if nn else ''
        loc_avg=round(ls/ln,3) if ln else ''
        row['全国%sn'%lab]=nn; row['全国%sST'%lab]=nat_avg
        row['当地%sn'%lab]=ln; row['当地%sST'%lab]=loc_avg
        if ln>=10: adopt=loc_avg; src='当地'
        elif nn>0: adopt=nat_avg; src='全国'
        else: adopt=''; src=''
        row['採用%sST'%lab]=adopt; row['%s源'%lab]=src
        row['%s遅れ'%lab]='●' if (adopt!='' and adopt>0.18) else ''
        row['%s巧者'%lab]='●' if (adopt!='' and adopt<=0.13) else ''
    st_rows.append(row)
stf=['regno','選手名','全国スローn','全国スローST','当地スローn','当地スローST','採用スローST','スロー源','スロー遅れ','スロー巧者','全国ダッシュn','全国ダッシュST','当地ダッシュn','当地ダッシュST','採用ダッシュST','ダッシュ源','ダッシュ遅れ','ダッシュ巧者']
with open('平和島_ST表.csv','w',newline='') as fo:
    w=csv.DictWriter(fo,fieldnames=stf,extrasaction='ignore'); w.writeheader()
    for r in sorted(st_rows,key=lambda x:x['regno']): w.writerow(r)
sl_late=sum(1 for r in st_rows if r['スロー遅れ']=='●'); sl_good=sum(1 for r in st_rows if r['スロー巧者']=='●')
loc_adopt=sum(1 for r in st_rows if r['スロー源']=='当地')
print('① ST表: %d人 スロー遅れ●%d 巧者●%d 当地スロー採用%d'%(len(st_rows),sl_late,sl_good,loc_adopt))

# ---------- ④ 絞りまくり表（当地）----------
by_race=defaultdict(list)
for e in ent: by_race[(e['date'],e['race'])].append(e)
shibori=defaultdict(lambda:[0,0])
for r in races:
    es=by_race[(r['date'],r['race'])]; km=r['kimarite']; wb=r['win_boat']
    for e in es:
        if e['course'] in ('3','4'):
            shibori[e['regno']][0]+=1
            if e['boat']==wb and km in ('まくり','まくり差し'):
                shibori[e['regno']][1]+=1
sh_rows=[]
for reg,(n34,mw) in shibori.items():
    if n34<15: continue
    rate=mw/n34
    sh_rows.append(dict(regno=reg,選手名=names.get(reg,''),n34=n34,まくり系1着=mw,率=round(rate,3),
        絞りまくり='●' if rate>=0.15 else '',暫定='暫定' if 15<=n34<=19 else ''))
sh_rows.sort(key=lambda x:-x['率'])
with open('平和島_絞りまくり表.csv','w',newline='') as fo:
    w=csv.DictWriter(fo,fieldnames=['regno','選手名','n34','まくり系1着','率','絞りまくり','暫定']); w.writeheader()
    for r in sh_rows: w.writerow(r)
nsh=sum(1 for r in sh_rows if r['絞りまくり']=='●')
print('④ 絞りまくり表: 15走以上%d人 ●%d人'%(len(sh_rows),nsh))
if sh_rows[:5]:
    print('  上位:', ', '.join('%s%.1f%%(n%d)'%(r['選手名'],r['率']*100,r['n34']) for r in sh_rows[:5]))
