# -*- coding: utf-8 -*-
"""
丸亀 穴党ツール – データ更新スクリプト（4表まとめて出力）
"""
import os
import re
import csv
import socket
import datetime
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import lhafile

VENUE = "15"
WINDOW_DAYS = 365
LOCAL_FLOOR = 10
OUT_DIR = "data"
TMP_DIR = "_tmp"
UA = {"User-Agent": "Mozilla/5.0 (marugame-tool)"}
socket.setdefaulttimeout(30)

ST_NUM = re.compile(r"^\d\.\d+$")
KIM = ["まくり差し", "まくり", "逃げ", "差し", "抜き", "恵まれ"]
PTS = {"F": 20, "L1": 20, "S1": 10, "S2": 15, "K1": 10}
COUNT = set(["F", "L1", "S1", "S2", "K1"])


def period_start():
    t = datetime.date.today()
    if 5 <= t.month <= 10:
        d = datetime.date(t.year, 5, 1)
    elif t.month >= 11:
        d = datetime.date(t.year, 11, 1)
    else:
        d = datetime.date(t.year - 1, 11, 1)
    return d.strftime("%y%m%d")


def fetch(url):
    for _ in range(2):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA)).read()
        except Exception:
            continue
    return None


def lzh_to_text(raw):
    if not raw:
        return None
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        tmp = os.path.join(TMP_DIR, "x%d.lzh" % (abs(hash(raw)) % 10**9))
        with open(tmp, "wb") as f:
            f.write(raw)
        arc = lhafile.Lhafile(tmp)
        data = arc.read(arc.namelist()[0])
        os.remove(tmp)
        return data.decode("shift_jis", errors="replace")
    except Exception:
        return None


def download_one_k(ymd):
    url = "https://www1.mbrace.or.jp/od2/K/20%s/k%s.lzh" % (ymd[:4], ymd)
    return (ymd, lzh_to_text(fetch(url)))


def download_all_k():
    days = [(datetime.date.today() - datetime.timedelta(d)).strftime("%y%m%d")
            for d in range(WINDOW_DAYS)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        return [it for it in ex.map(download_one_k, days) if it[1]]


def latest_fan_text():
    t = datetime.date.today(); y = t.year % 100
    cands = ["%02d10" % y, "%02d04" % y, "%02d10" % (y - 1), "%02d04" % (y - 1)]
    if t.month < 11:
        cands = [c for c in cands if c != "%02d10" % y]
    if t.month < 5:
        cands = [c for c in cands if c != "%02d04" % y]
    for code in cands:
        url = "https://www.boatrace.jp/static_extra/pc_static/download/data/kibetsu/fan%s.lzh" % code
        text = lzh_to_text(fetch(url))
        if text:
            print("  fan:", code)
            return text
    return None


def parse_fan(text):
    nat = {}
    if not text:
        return nat
    raw = text.encode("shift_jis", errors="replace")
    for r in raw.split(b"\r\n"):
        if len(r) < 400:
            continue
        tb = r[0:4].decode("ascii", "replace")
        nm = r[4:20].decode("shift_jis", "replace").replace("\u3000", "").strip()
        kyu = r[39:41].decode("shift_jis", "replace").strip()
        cs = {}
        for c in range(6):
            base = 82 + c * 13
            cs[c + 1] = (int(r[base:base + 3]), int(r[base + 7:base + 10]) / 100)

        def grp(cos):
            num = sum(cs[c][0] * cs[c][1] for c in cos if cs[c][0] > 0)
            den = sum(cs[c][0] for c in cos if cs[c][0] > 0)
            return round(num / den, 3) if den > 0 else None

        nat[tb] = {"name": nm, "kyu": kyu, "S": grp([1, 2, 3]), "D": grp([4, 5, 6])}
    return nat


def parse_all(k_items):
    PS = period_start()
    A = {
        "st_sum": defaultdict(float), "st_n": defaultdict(int),
        "mg_total": defaultdict(int), "mg_F": defaultdict(int),
        "f_run": defaultdict(int), "f_pts": defaultdict(int), "f_cnt": defaultdict(int),
        "e34": defaultdict(int), "mk": defaultdict(int),
        "me34": defaultdict(int), "mmk": defaultdict(int),
        "c1e": defaultdict(int), "c1lose": defaultdict(int), "c1_2": defaultdict(int),
        "oe": defaultdict(int), "ot3": defaultdict(int),
        "moe": defaultdict(int), "mot3": defaultdict(int),
        "c6e": defaultdict(int), "c6_2": defaultdict(int), "c6_3": defaultdict(int),
    }
    for ymd, text in k_items:
        in_period = ymd >= PS
        for mm in re.finditer(r"(\d\d)KBGN(.*?)\1KEND", text, re.S):
            jcd = mm.group(1); kim = None
            for ln in mm.group(2).split("\n"):
                s = ln.rstrip("\r")
                if "ﾚｰｽﾀｲﾑ" in s:
                    part = s.split("ﾚｰｽﾀｲﾑ")[-1].replace("\u3000", "").replace(" ", "")
                    kim = next((k for k in KIM if part.startswith(k)), None)
                    continue
                if len(s) > 21 and s[0:2] == "  " and s[8:12].isdigit() and s[6:7].isdigit():
                    tail = s[21:].split()
                    if len(tail) < 4 or len(tail[3]) != 1 or tail[3] not in "123456":
                        continue
                    co = int(tail[3]); ch = s[2:4].strip(); tb = s[8:12]
                    fin = ch.isdigit() and 1 <= int(ch) <= 6
                    k = int(ch) if fin else 0
                    win_makuri = (ch == "01" and kim in ("まくり", "まくり差し"))
                    if jcd == VENUE:
                        A["mg_total"][tb] += 1
                        if len(tail) >= 5:
                            stv = tail[4]
                            if stv.startswith("F"):
                                A["mg_F"][tb] += 1
                            elif ST_NUM.match(stv):
                                g = "S" if co <= 3 else "D"
                                A["st_sum"][(tb, g)] += float(stv); A["st_n"][(tb, g)] += 1
                    if in_period:
                        if fin:
                            A["f_run"][tb] += 1
                        elif ch in COUNT:
                            A["f_run"][tb] += 1; A["f_pts"][tb] += PTS[ch]
                            if ch == "F":
                                A["f_cnt"][tb] += 1
                    if co in (3, 4):
                        A["e34"][tb] += 1
                        if win_makuri:
                            A["mk"][tb] += 1
                        if jcd == VENUE:
                            A["me34"][tb] += 1
                            if win_makuri:
                                A["mmk"][tb] += 1
                    if co == 1:
                        A["c1e"][tb] += 1
                        if not (fin and k == 1):
                            A["c1lose"][tb] += 1
                        if fin and k == 2:
                            A["c1_2"][tb] += 1
                    if co >= 4:
                        A["oe"][tb] += 1
                        if fin and k <= 3:
                            A["ot3"][tb] += 1
                        if jcd == VENUE:
                            A["moe"][tb] += 1
                            if fin and k <= 3:
                                A["mot3"][tb] += 1
                    if co == 6:
                        A["c6e"][tb] += 1
                        if fin and k == 2:
                            A["c6_2"][tb] += 1
                        if fin and k == 3:
                            A["c6_3"][tb] += 1
    return A


def pct(sorted_list, p):
    return sorted_list[int(len(sorted_list) * p)] if sorted_list else 0


def write_all(A, fan):
    os.makedirs(OUT_DIR, exist_ok=True)

    def name(tb): return fan.get(tb, {}).get("name", "")
    def kyu(tb):  return fan.get(tb, {}).get("kyu", "")

    def loc(tb, g):
        key = (tb, g)
        return round(A["st_sum"][key] / A["st_n"][key], 3) if A["st_n"][key] > 0 else None

    p = os.path.join(OUT_DIR, "丸亀_最終ST表.csv")
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["登番", "名前", "級", "採用元", "丸亀走数", "スロー平均ST", "ダッシュ平均ST",
                    "スロー巧者(<=.13)", "スロー遅れ警戒(>.18)", "ダッシュ遅れ警戒(>.18)"])
        for tb, d in fan.items():
            use = A["mg_total"].get(tb, 0) >= LOCAL_FLOOR and loc(tb, "S") is not None
            src, S, D = ("当地", loc(tb, "S"), loc(tb, "D")) if use else ("全国", d["S"], d["D"])
            fl = lambda v, op, th: ("" if v is None else ("●" if (v <= th if op == "le" else v > th) else ""))
            w.writerow([tb, d["name"], d["kyu"], src, A["mg_total"].get(tb, 0),
                        S if S is not None else "", D if D is not None else "",
                        fl(S, "le", .13), fl(S, "gt", .18), fl(D, "gt", .18)])

    p = os.path.join(OUT_DIR, "丸亀_当期F持ち表.csv")
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["登番", "名前", "級", "当期出走", "F本数", "当期事故率", "自重区分", "A級F持ち警戒"])
        rows = []
        for tb in A["f_run"]:
            run = A["f_run"][tb]; fcnt = A["f_cnt"][tb]
            jr = round(A["f_pts"][tb] / run, 3) if run > 0 else 0
            sect = "F2持ち以上" if fcnt >= 2 else ("F1持ち" if fcnt == 1 else "")
            danger = "●" if (kyu(tb) in ("A1", "A2") and fcnt >= 1) else ""
            rows.append([tb, name(tb), kyu(tb), run, fcnt, jr, sect, danger])
        rows.sort(key=lambda x: (-x[4], -x[5]))
        w.writerows(rows)

    rates = sorted(A["mk"][t] / A["e34"][t] for t in A["e34"] if A["e34"][t] >= 30)
    TH = pct(rates, 0.75)
    p = os.path.join(OUT_DIR, "丸亀_まくり表.csv")
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["登番", "名前", "級", "全国3/4進入", "全国まくり率",
                    "丸亀3/4進入", "丸亀まくり率", "採用値", "絞りまくり型"])
        for tb in A["e34"]:
            nat_r = round(A["mk"][tb] / A["e34"][tb], 3) if A["e34"][tb] >= 15 else ""
            loc_r = round(A["mmk"][tb] / A["me34"][tb], 3) if A["me34"][tb] >= 15 else ""
            adopt = loc_r if loc_r != "" else nat_r
            flag = "●" if (adopt != "" and adopt >= TH) else ""
            if nat_r == "" and loc_r == "":
                continue
            w.writerow([tb, name(tb), kyu(tb), A["e34"][tb], nat_r,
                        A["me34"][tb], loc_r, adopt, flag])

    nok = sorted(A["c1_2"][t] / A["c1lose"][t]
                 for t in A["c1e"] if A["c1e"][t] >= 40 and A["c1lose"][t] >= 20)
    HI, LO = pct(nok, 0.75), pct(nok, 0.25)
    p = os.path.join(OUT_DIR, "丸亀_残し表.csv")
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["登番", "名前", "級", "1コ進入", "1コ負け", "1コ負け時2着率", "型",
                    "外進入(全国)", "外3着残し率(全国)", "丸亀外進入", "丸亀外3着残し率", "外採用値",
                    "6コ進入", "6コ2着率", "6コ3着率"])
        allt = set(A["c1e"]) | set(A["oe"]) | set(A["c6e"])
        for tb in allt:
            if A["c1e"][tb] >= 40 and A["c1lose"][tb] >= 20:
                r2 = A["c1_2"][tb] / A["c1lose"][tb]
                typ = "残す" if r2 >= HI else ("飛ぶ" if r2 <= LO else "中間")
                r2s = round(r2, 3)
            else:
                r2s, typ = "", ""
            o_nat = round(A["ot3"][tb] / A["oe"][tb], 3) if A["oe"][tb] >= 25 else ""
            m_loc = round(A["mot3"][tb] / A["moe"][tb], 3) if A["moe"][tb] >= 25 else ""
            adopt = m_loc if m_loc != "" else o_nat
            s62 = round(A["c6_2"][tb] / A["c6e"][tb], 3) if A["c6e"][tb] >= 40 else ""
            s63 = round(A["c6_3"][tb] / A["c6e"][tb], 3) if A["c6e"][tb] >= 40 else ""
            if r2s == "" and o_nat == "" and m_loc == "" and s62 == "":
                continue
            w.writerow([tb, name(tb), kyu(tb), A["c1e"][tb], A["c1lose"][tb], r2s, typ,
                        A["oe"][tb], o_nat, A["moe"][tb], m_loc, adopt,
                        A["c6e"][tb], s62, s63])


def main():
    print("K download...")
    k_items = download_all_k()
    print("  days:", len(k_items))
    A = parse_all(k_items)
    fan = parse_fan(latest_fan_text())
    print("  racers:", len(fan))
    write_all(A, fan)
    print("done: 4 CSVs in data/")


if __name__ == "__main__":
    main()
