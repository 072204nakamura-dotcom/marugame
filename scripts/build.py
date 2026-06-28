# -*- coding: utf-8 -*-
"""
丸亀 穴党ツール – データ更新スクリプト（その1：最終ST表）

このスクリプトは GitHub Actions（自動）で毎日動く想定です。
やること：
  1. 公式の競走成績（K）ファイルを直近12か月ぶんダウンロード
  2. lhafile（純Python）でLZHを解凍
  3. 丸亀の選手別スタートタイミング（ST）を集計（=当地）
  4. 期別成績（fan手帳）の全国コース別STを集計（=全国フォールバック）
  5. 当地優先・不足は全国、で合体 → data/丸亀_最終ST表.csv を出力

非プログラマーの方へ：このファイルを編集する必要はありません。
リポジトリの scripts/build.py に置くだけでOKです。
"""

import os
import re
import csv
import socket
import datetime
import urllib.request
from io import BytesIO
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import lhafile  # 純PythonのLZH解凍ライブラリ（workflowでpip installされます）

# ====== 設定 ======================================================
VENUE = "15"              # 丸亀の場コード
WINDOW_DAYS = 365         # 当地STを集計する期間（日数）。STは安定スキルなので12か月
LOCAL_FLOOR = 10          # 丸亀でこの走数以上なら当地値を採用、未満は全国フォールバック
OUT_DIR = "data"          # 出力先フォルダ
TMP_DIR = "_tmp"          # ダウンロード一時置き場（リポジトリには残しません）
UA = {"User-Agent": "Mozilla/5.0 (marugame-tool)"}
socket.setdefaulttimeout(30)

ST_NUM = re.compile(r"^\d\.\d+$")          # "0.14" のような正常STだけを拾う
BLOCK = None  # 後で会場ブロック抽出に使う

# ====== 共通ヘルパ =================================================
def daterange(days):
    """今日からさかのぼって days 日ぶんの 'YYMMDD' リストを返す"""
    today = datetime.date.today()
    return [(today - datetime.timedelta(d)).strftime("%y%m%d") for d in range(days)]

def fetch(url):
    """URLを取得してバイト列を返す。失敗したら None。"""
    for _ in range(2):  # 1回だけリトライ
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req).read()
        except Exception:
            continue
    return None

def lzh_to_text(raw_bytes):
    """LZHのバイト列を解凍して中のテキスト（Shift-JIS）を返す。失敗で None。"""
    if not raw_bytes:
        return None
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        tmp = os.path.join(TMP_DIR, "x%d.lzh" % (abs(hash(raw_bytes)) % 10**8))
        with open(tmp, "wb") as f:
            f.write(raw_bytes)
        arc = lhafile.Lhafile(tmp)
        data = arc.read(arc.namelist()[0])
        os.remove(tmp)
        return data.decode("shift_jis", errors="replace")
    except Exception:
        return None

# ====== K（競走成績）：丸亀のST集計 ===============================
def download_one_k(ymd):
    """1日ぶんのKファイルを取得・解凍して、丸亀ブロックのテキストを返す（無ければ None）"""
    url = "https://www1.mbrace.or.jp/od2/K/20%s/k%s.lzh" % (ymd[:4], ymd)
    text = lzh_to_text(fetch(url))
    if not text:
        return None
    m = re.search(VENUE + r"KBGN(.*?)" + VENUE + r"KEND", text, re.S)
    return m.group(1) if m else None

def collect_local_st():
    """丸亀のKを直近12か月集めて、選手×(スロー/ダッシュ)の平均STと走数・F本数を返す"""
    ssum = defaultdict(float); sn = defaultdict(int)
    total = defaultdict(int); fcount = defaultdict(int)
    days = daterange(WINDOW_DAYS)

    # ダウンロードは時間がかかるので並列で取得
    with ThreadPoolExecutor(max_workers=8) as ex:
        blocks = list(ex.map(download_one_k, days))

    for blk in blocks:
        if not blk:
            continue
        for ln in blk.split("\n"):
            s = ln.rstrip("\r")
            if len(s) > 21 and s[0:2] == "  " and s[8:12].isdigit() and s[6:7].isdigit():
                tail = s[21:].split()
                if len(tail) >= 5 and len(tail[3]) == 1 and tail[3] in "123456":
                    tb = s[8:12]; co = int(tail[3]); stv = tail[4]
                    total[tb] += 1
                    if stv.startswith("F"):
                        fcount[tb] += 1
                    elif ST_NUM.match(stv):
                        g = "S" if co <= 3 else "D"      # スロー(1-3)/ダッシュ(4-6)
                        ssum[(tb, g)] += float(stv); sn[(tb, g)] += 1

    def avg(tb, g):
        return round(ssum[(tb, g)] / sn[(tb, g)], 3) if sn[(tb, g)] > 0 else None
    return total, fcount, avg

# ====== fan（期別成績）：全国コース別STのフォールバック ===========
def latest_fan_text():
    """最新の期別成績（fan手帳）を探して解凍テキストを返す"""
    today = datetime.date.today(); y = today.year % 100
    # 直近の期末コード候補を新しい順に並べて、最初に取れたものを使う
    cands = ["%02d10" % y, "%02d04" % y, "%02d10" % (y - 1), "%02d04" % (y - 1)]
    # 未来の期は除外（例：まだ来ていない10月期など）
    if today.month < 11: cands = [c for c in cands if c != "%02d10" % y]
    if today.month < 5:  cands = [c for c in cands if c != "%02d04" % y]
    for code in cands:
        url = "https://www.boatrace.jp/static_extra/pc_static/download/data/kibetsu/fan%s.lzh" % code
        text = lzh_to_text(fetch(url))
        if text:
            print("  使用したfan手帳:", code)
            return text
    return None

def collect_national_st(text):
    """fan手帳テキストから 選手 -> (名前,級,スロー平均ST,ダッシュ平均ST) を返す"""
    nat = {}
    if not text:
        return nat
    raw = text.encode("shift_jis", errors="replace")  # 固定長はバイトで切る
    for r in raw.split(b"\r\n"):
        if len(r) < 400:
            continue
        tb = r[0:4].decode("ascii", "replace")
        nm = r[4:20].decode("shift_jis", "replace").replace("\u3000", "").strip()
        kyu = r[39:41].decode("shift_jis", "replace").strip()
        cs = {}
        for c in range(6):
            base = 82 + c * 13
            ent = int(r[base:base + 3]); avg = int(r[base + 7:base + 10]) / 100
            cs[c + 1] = (ent, avg)
        def grp(cos):
            num = sum(cs[c][0] * cs[c][1] for c in cos if cs[c][0] > 0)
            den = sum(cs[c][0] for c in cos if cs[c][0] > 0)
            return round(num / den, 3) if den > 0 else None
        nat[tb] = {"name": nm, "kyu": kyu, "S": grp([1, 2, 3]), "D": grp([4, 5, 6])}
    return nat

# ====== 合体して出力 ==============================================
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("丸亀のK（直近%d日）を取得・集計中..." % WINDOW_DAYS)
    total, fcount, loc = collect_local_st()
    print("  丸亀に乗った選手:", len(total), "人")

    print("全国フォールバック（fan手帳）を取得中...")
    nat = collect_national_st(latest_fan_text())
    print("  全国選手:", len(nat), "人")

    out = os.path.join(OUT_DIR, "丸亀_最終ST表.csv")
    nloc = nnat = 0
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["登番", "名前", "級", "採用元", "丸亀走数", "スロー平均ST",
                    "ダッシュ平均ST", "スロー巧者(<=.13)", "スロー遅れ警戒(>.18)",
                    "ダッシュ遅れ警戒(>.18)"])
        # fan手帳にいる全選手を土台に、丸亀で十分走っていれば当地値で上書き
        for tb, d in nat.items():
            use_loc = total.get(tb, 0) >= LOCAL_FLOOR and loc(tb, "S") is not None
            if use_loc:
                src = "当地"; S = loc(tb, "S"); D = loc(tb, "D"); nloc += 1
            else:
                src = "全国"; S = d["S"]; D = d["D"]; nnat += 1
            def flag(v, op, th):
                if v is None:
                    return ""
                return "●" if (v <= th if op == "le" else v > th) else ""
            w.writerow([tb, d["name"], d["kyu"], src, total.get(tb, 0),
                        S if S is not None else "", D if D is not None else "",
                        flag(S, "le", .13), flag(S, "gt", .18), flag(D, "gt", .18)])
    print("出力:", out, " 当地採用 %d人 / 全国 %d人" % (nloc, nnat))

if __name__ == "__main__":
    main()
