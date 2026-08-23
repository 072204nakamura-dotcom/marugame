# -*- coding: utf-8 -*-
"""全国・選手別の決まり手プロフィール（Kファイル370日・全24場から直接集計）
「まくりの決まり手が無い選手」の洗い出し。"""
import os, re, csv, unicodedata, lhafile
from collections import defaultdict

REPO=r'C:/Users/gk-ki/GitHub/marugame'
RACE_HDR=re.compile(r'^\s{2,}(\d{1,2})R\s+(.*?)\s+H(\d{3,4})m')
KIM=('逃げ','差し','まくり','まくり差し','抜き','恵まれ')

def is_fin(l): return len(l)>21 and l[:2]=='  ' and l[6].isdigit() and l[8:12].isdigit()

P=defaultdict(lambda: defaultdict(int))   # regno -> counters
names={}
files=sorted(f for f in os.listdir(REPO+'/data/lzh_k') if f.endswith('.lzh'))
print('Kファイル',len(files),'日分を集計中...',flush=True)
for i,fn in enumerate(files):
    try:
        lf=lhafile.Lhafile(REPO+'/data/lzh_k/'+fn)
        raw=lf.read(lf.infolist()[0].filename).decode('shift_jis','replace')
    except Exception: continue
    for vm in re.finditer(r'(\d{2})KBGN(.*?)\1KEND', raw, re.S):
        cur_kim=None; boats=[]
        def flush():
            for chaku,reg,co in boats:
                p=P[reg]
                p['総出走']+=1
                if co>=2: p['攻め走(2-6C)']+=1
                if chaku=='01':
                    p['1着']+=1
                    if cur_kim in KIM: p['勝ち_'+cur_kim]+=1
                    if co>=2 and cur_kim in ('まくり','まくり差し'): p['攻めまくり系1着']+=1
        for line in vm.group(2).split('\n'):
            if RACE_HDR.match(line) and ('風' in line or '波' in line):
                flush(); cur_kim=None; boats=[]; continue
            if 'ﾚｰｽﾀｲﾑ' in line:
                cur_kim=line.split('ﾚｰｽﾀｲﾑ')[-1].replace('　','').strip(); continue
            if is_fin(line):
                t=line[21:].split()
                co=t[3] if len(t)>=4 and len(t[3])==1 and t[3] in '123456' else ''
                if not co: continue
                nm=line[13:21].replace('　','').strip()
                if nm: names[line[8:12]]=nm
                boats.append((line[2:4].strip(), line[8:12], int(co)))
        flush()
    if (i+1)%90==0: print(' ',i+1,'/',len(files),flush=True)

rows=[]
for reg,p in P.items():
    mk=p['勝ち_まくり']; mkz=p['勝ち_まくり差し']
    rows.append(dict(regno=reg, 選手名=names.get(reg,''), 総出走=p['総出走'],
        攻め走=p['攻め走(2-6C)'], 一着=p['1着'],
        逃げ=p['勝ち_逃げ'], 差し=p['勝ち_差し'], まくり=mk, まくり差し=mkz,
        抜き=p['勝ち_抜き'], 恵まれ=p['勝ち_恵まれ'],
        まくりゼロ='●' if (p['攻め走(2-6C)']>=100 and mk==0) else '',
        まくり系ゼロ='●' if (p['攻め走(2-6C)']>=100 and mk+mkz==0) else ''))
rows.sort(key=lambda r:-r['攻め走'])
out=REPO+'/data/全国_決まり手プロフィール.csv'
with open(out,'w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
n100=[r for r in rows if r['攻め走']>=100]
print('選手数:',len(rows),'／ 攻め走100以上:',len(n100))
print('まくりゼロ●(攻め100走以上でまくり1着0):',sum(1 for r in n100 if r['まくりゼロ']))
print('まくり系ゼロ●(まくり差しも0):',sum(1 for r in n100 if r['まくり系ゼロ']))
print('->',out)
