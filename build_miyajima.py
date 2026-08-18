# -*- coding: utf-8 -*-
"""
宮島 穴党ツール：毎朝の data.json 生成スクリプト
- 当日のBファイル(番組表)をダウンロードして宮島(17)を切り出し
- 仕様書の採用シグナルでレースごとの「崩れ筋スコア」を計算
- miyajima/data.json を出力（index.htmlが読み込む）
使い方: python3 build_miyajima.py            ← 今日の日付で実行
        python3 build_miyajima.py 260620    ← 日付指定(テスト用)
"""
import sys, os, io, re, csv, json, datetime, unicodedata, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "miyajima")

# ---------- 固定テーブル（2025-07〜2026-06実測・仕様書§6/§13） ----------
RNO_TABLE = [
 {"rno":1,"in1":72.7,"man":14.1},{"rno":2,"in1":49.5,"man":20.8},
 {"rno":3,"in1":47.1,"man":19.6},{"rno":4,"in1":51.2,"man":17.2},
 {"rno":5,"in1":55.4,"man":15.7},{"rno":6,"in1":60.8,"man":17.2},
 {"rno":7,"in1":46.8,"man":20.7},{"rno":8,"in1":51.5,"man":17.0},
 {"rno":9,"in1":53.2,"man":20.4},{"rno":10,"in1":55.0,"man":20.3},
 {"rno":11,"in1":68.8,"man":14.1},{"rno":12,"in1":70.9,"man":15.1}]
# レース番号スコア（イン残差の実測から：1R+10.1pt要塞 / 7R−6.4pt最荒）
RNO_SCORE = {1:-4.0, 2:1.0, 3:1.5, 4:0.0, 5:1.5, 6:-1.5, 7:2.5,
             8:0.0, 9:0.5, 10:0.0, 11:-1.0, 12:-1.0}

def load_csv(name, key=0):
    d={}
    p=os.path.join(OUTDIR, name)
    if not os.path.exists(p): return d
    with open(p, encoding="utf-8-sig") as f:
        rd=csv.reader(f); header=next(rd)
        for row in rd:
            if row: d[row[key]]=row
    return d

ST   = load_csv("st_table.csv")        # 登番 -> [登番,ST,走数,出所]
JIR  = load_csv("jiriki_table.csv")      # 登番 -> [登番,走数,全国逃げ率]
FMO  = load_csv("f_holders.csv")  # 登番 -> ...（有無だけ使う）

# ---------- Bファイル取得・解凍 ----------
def fetch_b(yymmdd):
    yyyymm = "20"+yymmdd[:4]
    url=f"https://www1.mbrace.or.jp/od2/B/{yyyymm}/b{yymmdd}.lzh"
    req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    data=urllib.request.urlopen(req, timeout=60).read()
    if len(data)<1000: raise RuntimeError("Bファイルが小さすぎます(未公開?)")
    import lhafile
    lf=lhafile.Lhafile(io.BytesIO(data))
    return lf.read(lf.namelist()[0]).decode("shift_jis", errors="replace")

# ---------- 宮島ブロックのパース ----------
def parse_racer(line):
    # '1 3918深井利寿51滋賀52A2 6.59 46.72 6.38 48.28 70 35.10 69 28.10 ...'
    if len(line)<40: return None
    if line[0] not in "123456" or line[1]!=" ": return None
    reg=line[2:6]
    if not reg.isdigit(): return None
    name=line[6:10].replace("　","").strip()
    grade=line[16:18].strip()
    tail=line[18:].split()
    def num(i):
        try: return float(tail[i])
        except: return None
    return dict(teiban=int(line[0]), reg=reg, name=name, grade=grade,
                zenkoku_win=num(0), zenkoku_2=num(1),
                touchi_win=num(2), touchi_2=num(3),
                motor_no=tail[4] if len(tail)>4 else None,
                motor_2=num(5))

def parse_block(blk):
    norm=unicodedata.normalize("NFKC", blk)
    m=re.search(r"第\s*(\d+)\s*日", norm)
    nichime=int(m.group(1)) if m else None
    m=re.search(r"^ボートレース宮\s*島\s+\S+\s+(.+?)\s+第", norm, re.M)
    title=None
    for ln in norm.split("\n")[:8]:
        mm=re.match(r"ボートレース宮\s*島\s+\S+\s+(.+?)\s+第", ln)
        if mm: title=mm.group(1).strip(); break
    races=[]; cur=None
    for raw_ln in blk.split("\n"):
        ln=unicodedata.normalize("NFKC", raw_ln.rstrip())
        h=re.match(r"\s*(\d+)R\s+(\S.*?)\s+H\d+m\s+電話投票締切予定(\d{1,2}):(\d{2})", ln)
        if h:
            cur=dict(rno=int(h.group(1)), rname=h.group(2).strip(),
                     deadline=f"{int(h.group(3)):02d}:{h.group(4)}", boats=[])
            races.append(cur); continue
        if cur is not None:
            b=parse_racer(ln)
            if b: cur["boats"].append(b)
    races=[r for r in races if len(r["boats"])==6]
    yusho = any("優勝" in r["rname"] for r in races)
    return races, nichime, title, yusho

# ---------- スコアリング（仕様書§4-7,13の採用シグナル） ----------
def score_race(r, yusho_day):
    s = RNO_SCORE.get(r["rno"], 0.0)
    why=[]
    if s>=1.5: why.append(f"{r['rno']}Rは実測でイン沈む構造spot")
    if r["rno"]==1: why.append("1Rはイン要塞(+10pt)")
    if yusho_day:
        s -= 2.0; why.append("優勝戦日=インが締まる日(+5.5pt)")
    b1 = r["boats"][0]
    for b in r["boats"]:
        b["badges"]=[]; b["jiriki"]=None; b["st_avg"]=None
        j=JIR.get(b["reg"])
        if j: b["jiriki"]=float(j[2])
        st=ST.get(b["reg"])
        if st: b["st_avg"]=float(st[1])
        if b["reg"] in FMO:
            b["badges"].append("F持ち")
            if b["teiban"]==1: s+=1.5
        if b["st_avg"] is not None:
            if b["st_avg"]>=0.19:
                b["badges"].append("ST遅め")
                if b["teiban"]==1: s+=1.5
            elif b["st_avg"]<=0.14 and b["teiban"] in (3,4):
                b["badges"].append("ST一撃"); s+=0.8
        if b["teiban"]==1 and b["jiriki"] is not None:
            if b["jiriki"]<45: b["badges"].append("イン不安"); s+=2.0
            elif b["jiriki"]<50: s+=1.0
            elif b["jiriki"]>65: b["badges"].append("逃げ厚"); s-=2.0
            elif b["jiriki"]>60: s-=1.0
        if b["teiban"] in (5,6) and b["grade"]=="A1":
            b["badges"].append("外に地力"); s+=0.7
    s=round(s,1)
    # ラベル
    if r["rno"]==1 and s<=0: label="鉄板1R"
    elif s>=4: label="穴の巣"
    elif s>=2: label="堅いか万舟"
    elif s<=-3: label="イン堅め"
    else: label="中間"
    # 方針文
    pol=[]
    if label=="穴の巣":
        pol.append("イン頭を外す3連単を検討。受け皿は2-3-4（宮島は6が残らない）。")
    elif label=="堅いか万舟":
        pol.append("イン信頼と崩れの二択。オッズ次第で崩れ側へ。ヒモも内寄り優先。")
    elif label in ("イン堅め","鉄板1R"):
        pol.append("イン頭固定が本線。穴狙いは見送り推奨。")
    else:
        pol.append("特筆材料薄。無理せず他レースへ。")
    pol.append("直前確認：北東/東の風2m以上なら穴側へ加点（−5.8pt効果・暫定採用）。")
    return s, label, " ".join(pol)

# ---------- メイン ----------
def main():
    if len(sys.argv)>1:
        yymmdd=sys.argv[1]
    else:
        today=datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=9)  # JST
        yymmdd=today.strftime("%y%m%d")
    date_str=f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"
    out=dict(date=date_str, kaisai=False, rno_table=RNO_TABLE,
             updated=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M JST"))
    try:
        raw=fetch_b(yymmdd)
    except Exception as e:
        print("Bファイル取得失敗:", e); raw=None
    if raw and "17BBGN" in raw:
        blk=raw.split("17BBGN")[1].split("17BEND")[0]
        races, nichime, title, yusho = parse_block(blk)
        if races:
            out["kaisai"]=True; out["nichime"]=nichime; out["title"]=title or ""
            out["races"]=[]
            for r in races:
                s,label,pol=score_race(r, yusho)
                base=next((x["in1"] for x in RNO_TABLE if x["rno"]==r["rno"]), None)
                out["races"].append(dict(rno=r["rno"], rname=r["rname"],
                    deadline=r["deadline"], score=s, label=label, policy=pol,
                    base_in1=base,
                    boats=[dict(teiban=b["teiban"], name=b["name"], grade=b["grade"],
                                jiriki=b["jiriki"], st_avg=b["st_avg"],
                                motor2=b["motor_2"], badges=b["badges"]) for b in r["boats"]]))
    os.makedirs(OUTDIR, exist_ok=True)
    with open(os.path.join(OUTDIR,"data.json"),"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=1)
    print("出力:", os.path.join(OUTDIR,"data.json"),
          "/ 開催:", out["kaisai"], "/ レース数:", len(out.get("races",[])))

if __name__=="__main__":
    main()
