# -*- coding: utf-8 -*-
"""
穴党ツール – 確定オッズ収集スクリプト（複数場対応）

毎朝の自動実行で、昨日（と一昨日、取りこぼし対策）の対象場の
3連単・確定オッズ（全120通り）を公式サイトから回収し、
data/odds/場コード/YYYY-MM-DD.csv に保存します。

・対象場：丸亀(15)・江戸川(03)・福岡(22)・戸田(02)・鳴門(14)・宮島(17)  ※VENUESで増減可
・開催がなかった日は何もしません
・既に保存済みの日はスキップ（二重取得しない）
・1場1年で約8MBと小さいので容量の心配はありません
・将来のEV（期待値）検証用のデータ蓄積が目的です
"""

import os
import re
import csv
import time
import datetime
import urllib.request

OUT_DIR = "data/odds"
VENUES = ["15", "03", "22", "02", "14", "17"]   # 丸亀・江戸川・福岡・戸田・鳴門・宮島
UA = {"User-Agent": "Mozilla/5.0 (marugame-tool)"}


def jst_today():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date()


def fetch(url):
    for i in range(4):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="replace")
        except Exception:
            time.sleep(2 + i * 2)   # 少し待って再挑戦（2,4,6秒）
    return None


def parse_odds3t(html):
    """3連単オッズページから {(1着,2着,3着): オッズ} を返す。取れなければ None。"""
    if not html:
        return None
    vals = re.findall(r'class="oddsPoint[^"]*">([^<]*)<', html)
    if len(vals) != 120:
        return None
    out = {}
    for i, v in enumerate(vals):
        r, hidx = divmod(i, 6)          # 行(0-19)、列=1着(0-5)
        head = hidx + 1
        others = [b for b in range(1, 7) if b != head]
        second = others[r // 4]
        thirds = [b for b in range(1, 7) if b != head and b != second]
        third = thirds[r % 4]
        v = v.strip()
        try:
            out[(head, second, third)] = float(v)
        except ValueError:
            out[(head, second, third)] = None   # 欠場など
    return out


def collect_day(d):
    """1日ぶん（12レース）の確定オッズを取ってCSV保存。開催なしなら False。"""
    ds = d.strftime("%Y-%m-%d")
def collect_day(d, jcd):
    """1場・1日ぶん（12レース）の確定オッズを取ってCSV保存。開催なしなら False。"""
    ds = d.strftime("%Y-%m-%d")
    vdir = os.path.join(OUT_DIR, jcd)
    path = os.path.join(vdir, ds + ".csv")
    if os.path.exists(path):
        print("既に保存済み:", jcd, ds)
        return True
    hd = d.strftime("%Y%m%d")
    # 1Rで開催チェック
    html = fetch("https://www.boatrace.jp/owpc/pc/race/odds3t?rno=1&jcd=%s&hd=%s" % (jcd, hd))
    first = parse_odds3t(html)
    if first is None:
        print("開催なし/未確定:", jcd, ds)
        return False
    os.makedirs(vdir, exist_ok=True)
    rows = []
    for rno in range(1, 13):
        if rno == 1:
            odds = first
        else:
            time.sleep(3)   # 公式サイトへの配慮
            url = "https://www.boatrace.jp/owpc/pc/race/odds3t?rno=%d&jcd=%s&hd=%s" % (rno, jcd, hd)
            odds = parse_odds3t(fetch(url))
            if odds is None:          # 一時的に弾かれた場合は待ってもう一度だけ
                time.sleep(20)
                odds = parse_odds3t(fetch(url))
        if odds is None:
            print("  %dR: 取得できず（中止等の可能性）" % rno)
            continue
        for (h, s, t), v in sorted(odds.items()):
            rows.append([ds, rno, "%d-%d-%d" % (h, s, t), v if v is not None else ""])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "race", "combo", "odds"])
        w.writerows(rows)
    print("保存:", path, "(%d行)" % len(rows))
    return True


def main():
    today = jst_today()
    for jcd in VENUES:
        for back in (1, 2):   # 昨日と一昨日（取りこぼし対策）
            collect_day(today - datetime.timedelta(days=back), jcd)
        time.sleep(3)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("odds.py エラー（無視して続行）:", e)
