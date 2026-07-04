# -*- coding: utf-8 -*-
"""
丸亀 穴党ツール – 出走表取得スクリプト
毎朝、公式の番組表（B）から今日（と明日）の丸亀の出走表を取り、
data/marugame_racecard.json に保存します。
"""

import os
import re
import json
import socket
import datetime
import unicodedata
import urllib.request

import lhafile

VENUE = "15"
OUT = "data/marugame_racecard.json"
TMP = "_tmp"
UA = {"User-Agent": "Mozilla/5.0 (marugame-tool)"}
socket.setdefaulttimeout(30)


def jst_today():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date()


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
        os.makedirs(TMP, exist_ok=True)
        tmp = os.path.join(TMP, "b%d.lzh" % (abs(hash(raw)) % 10**9))
        with open(tmp, "wb") as f:
            f.write(raw)
        arc = lhafile.Lhafile(tmp)
        data = arc.read(arc.namelist()[0])
        os.remove(tmp)
        return data.decode("shift_jis", errors="replace")
    except Exception:
        return None


def parse_bcard(text):
    m = re.search(VENUE + r"BBGN(.*?)" + VENUE + r"BEND", text, re.S)
    if not m:
        return None
    blk = m.group(1)
    nfkc = unicodedata.normalize("NFKC", blk)
    day = None
    md = re.search(r"第\s*(\d+)\s*日", nfkc)
    if md:
        day = int(md.group(1))
    races = []
    cur = None
    for ln in blk.split("\n"):
        s = ln.rstrip("\r")
        n = unicodedata.normalize("NFKC", s)
        mr = re.match(r"\s*(\d+)R\s+(\S*)", n)
        if mr and ("締切" in n or "予定" in n):
            tm = re.search(r"締切予定\s*(\d{1,2}:\d{2})", n)
            cur = {"r": int(mr.group(1)), "kind": mr.group(2),
                   "close": tm.group(1) if tm else "", "racers": []}
            races.append(cur)
            continue
        mm2 = re.match(r"^([1-6]) (\d{4})(.+?)(\d{2})(..)(\d{2})(A1|A2|B1|B2)", s)
        if mm2 and cur is not None:
            cur["racers"].append({
                "lane": int(mm2.group(1)),
                "tb": mm2.group(2),
                "name": mm2.group(3).replace("\u3000", "").strip(),
                "kyu": mm2.group(7),
            })
    return {"day": day, "races": races}


def get_card(d):
    ymd = d.strftime("%y%m%d")
    url = "https://www1.mbrace.or.jp/od2/B/20%s/b%s.lzh" % (ymd[:4], ymd)
    text = lzh_to_text(fetch(url))
    if not text:
        return None
    card = parse_bcard(text)
    if not card or not card["races"]:
        return None
    card["date"] = d.strftime("%Y-%m-%d")
    return card


def main():
    os.makedirs("data", exist_ok=True)
    today = jst_today()
    cards = []
    for d in (today, today + datetime.timedelta(days=1)):
        c = get_card(d)
        if c:
            cards.append(c)
            print("card ok:", c["date"], "day", c["day"], len(c["races"]), "races")
        else:
            print("no race:", d.strftime("%Y-%m-%d"))
    out = {
        "updated": (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M"),
        "cards": cards,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("saved:", OUT)


if __name__ == "__main__":
    main()
