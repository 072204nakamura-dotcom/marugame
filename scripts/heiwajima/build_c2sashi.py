import csv
from collections import defaultdict
names={r['regno']:r['name'] for r in csv.DictReader(open('nat_names.csv'))}
# 全国2コース着（差し勝ちの母数調整用に2コース勝率のメンバー補正）
c2=list(csv.DictReader(open('nat_c2sashi.csv')))
data=[]
for r in c2:
    n=int(r['n2c']); w=int(r['win2c']); s=int(r['sashi_win'])
    if n>=40:
        data.append((r['regno'],n,w,s))
# 全国2コース勝率ベースライン
tot_n=sum(d[1] for d in data); tot_w=sum(d[2] for d in data); tot_s=sum(d[3] for d in data)
base_win=tot_w/tot_n; base_sashi=tot_s/tot_n
print('全国2コ(40走+) 平均勝率%.1f%% 差し勝率%.1f%% (差し比率%.0f%%)'%(base_win*100,base_sashi*100,tot_s/tot_w*100))
# 縮小（k=20, base_win へ）で2コ勝率、差し勝率
K=20
rows=[]
for reg,n,w,s in data:
    win_sh=(w+K*base_win)/(n+K)
    sashi_sh=(s+K*base_sashi)/(n+K)
    rows.append(dict(regno=reg,選手名=names.get(reg,''),n2c=n,
        勝率=round(w/n,3),差し勝率=round(s/n,3),
        補正勝率=round(win_sh,3),補正差し勝率=round(sashi_sh,3),
        差し比率=round(s/w,3) if w else 0))
# 差し巧者●：補正差し勝率が上位10%
sv=sorted(r['補正差し勝率'] for r in rows)
p90=sv[len(sv)*9//10]; p10=sv[len(sv)//10]
for r in rows:
    r['差し巧者']='●' if r['補正差し勝率']>=p90 else ''
    r['差し不発']='●' if r['補正差し勝率']<=p10 else ''
rows.sort(key=lambda x:-x['補正差し勝率'])
with open('平和島_2コース差し表.csv','w',newline='') as fo:
    w=csv.DictWriter(fo,fieldnames=['regno','選手名','n2c','勝率','差し勝率','補正勝率','補正差し勝率','差し比率','差し巧者','差し不発']); w.writeheader()
    for r in rows: w.writerow(r)
ng=sum(1 for r in rows if r['差し巧者']=='●')
print('2コース差し表: %d人(2コ40走+) 差し巧者●%d 差し不発●%d'%(len(rows),ng,sum(1 for r in rows if r['差し不発']=='●')))
print('閾値: 差し巧者 補正差し勝率≥%.1f%% / 差し不発≤%.1f%%'%(p90*100,p10*100))
print()
print('=== 差し巧者トップ10（崩れ時の2Cアタマ候補）===')
for r in rows[:10]:
    print('  %s: 補正差し勝率%.1f%% (生%.1f%%/勝率%.1f%%/差し比率%.0f%% n=%d)'%(
        r['選手名'],r['補正差し勝率']*100,r['差し勝率']*100,r['勝率']*100,r['差し比率']*100,r['n2c']))
