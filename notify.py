# -*- coding: utf-8 -*-
"""
丸亀 穴党ツール – 崩れ筋通知スクリプト

毎朝の自動実行の最後に動き、今日の丸亀のレースにスコアを付けて、
スコア2以上のレースがある日だけ、リポジトリにIssue（お知らせ）を作ります。
Issueが立つと、GitHubからメール／スマホアプリに通知が届きます。

・開催がない日、全レース平常（スコア0-1）の日は何もしません（静かな通知）
・同じ日のIssueが既にあれば二重に作りません
・このスクリプトが失敗しても、データ更新は止まりません（常に正常終了）
"""

import os
import csv
import json
import datetime
import urllib.request

DATA_DIR = os.environ.get("DATA_DIR", "data")
MIN_SCORE = 2   # このスコア以上のレースがある日だけ通知


def jst_today():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date()


def load_csv(name):
    """CSVを 登番->行リスト の辞書で返す。無ければ空辞書。"""
    path = os.path.join(DATA_DIR, name)
    m = {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        for r in rows[1:]:
            if r:
                m[r[0]] = r
    except Exception as e:
        print("CSV読めず:", name, e)
    return m


def fnum(v):
    try:
        return float(v)
    except Exception:
        return None


def score_races(card, st, ftab, mk, nk, wall):
    """1枚の出走表カードにスコアを付け、スコア>=MIN_SCOREのレース情報を返す"""
    hits = []
    for race in card.get("races", []):
        boats = {x["lane"]: x for x in race.get("racers", [])}
        if 1 not in boats:
            continue
        score = 0
        why = []
        b1 = boats[1]
        srow = st.get(b1["tb"])
        s1 = fnum(srow[5]) if srow else None
        if s1 is not None and s1 > 0.18:
            score += 1
            why.append("① 1号艇ST遅れ(%.2f)" % s1)
        frow = ftab.get(b1["tb"])
        fc = int(fnum(frow[4]) or 0) if frow else 0
        if fc >= 2:
            score += 2
            why.append("⑩ 1号艇F2持ち")
        elif fc == 1:
            score += 1
            why.append("⑩ 1号艇F1持ち")
        mks = [boats[l] for l in (3, 4)
               if l in boats and mk.get(boats[l]["tb"]) and mk[boats[l]["tb"]][8] == "●"]
        if mks:
            score += 1
            why.append("④ " + "・".join("%d号艇%s" % (x["lane"], x["name"]) for x in mks) + "が絞りまくり型")
        if 2 in boats:
            wrow = wall.get(boats[2]["tb"])
            if wrow and wrow[8] == "壁弱●":
                score += 1
                t = wrow[7]
                why.append("⑫ 2号艇%sが壁弱%s" % (boats[2]["name"], "（%s）" % t if t else ""))
        if card.get("day") == 1:
            score += 1
            why.append("⑨ 初日")
        if score >= MIN_SCORE:
            note = ""
            nrow = nk.get(b1["tb"])
            if nrow and nrow[6] in ("飛ぶ", "残す"):
                note = "／1号艇は%s型" % nrow[6]
            hits.append({"r": race["r"], "close": race.get("close", ""),
                         "score": score, "why": why, "note": note})
    return hits


def gh_api(url, data=None, token=None):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(data).encode("utf-8")
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))


def main():
    # 出走表を読む
    try:
        with open(os.path.join(DATA_DIR, "marugame_racecard.json"), encoding="utf-8") as f:
            rc = json.load(f)
    except Exception as e:
        print("出走表JSONなし:", e)
        return
    today = os.environ.get("NOTIFY_DATE") or jst_today().strftime("%Y-%m-%d")
    cards = [c for c in rc.get("cards", []) if c.get("date") == today]
    if not cards:
        print("本日(%s)の丸亀開催なし → 通知なし" % today)
        return

    st = load_csv("丸亀_最終ST表.csv")
    ftab = load_csv("丸亀_当期F持ち表.csv")
    mk = load_csv("丸亀_まくり表.csv")
    nk = load_csv("丸亀_残し表.csv")
    wall = load_csv("丸亀_壁表.csv")

    card = cards[0]
    hits = score_races(card, st, ftab, mk, nk, wall)
    if not hits:
        print("本日(%s・第%s日)は全レース平常（スコア%d未満）→ 通知なし" % (today, card.get("day"), MIN_SCORE))
        return

    fire = [h for h in hits if h["score"] >= 3]
    mark = "🔥" if fire else "⚠️"
    title = "%s 丸亀 %s 崩れ筋: %s" % (
        mark, today, "・".join("%dR(スコア%d)" % (h["r"], h["score"]) for h in hits))
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    owner = repo.split("/")[0] if "/" in repo else ""
    tool_url = "https://%s.github.io/%s/" % (owner, repo.split("/")[1]) if "/" in repo else ""
    lines = ["第%s日／スコア%d以上のレース：" % (card.get("day"), MIN_SCORE), ""]
    for h in hits:
        lines.append("### %dR（締切 %s）スコア %d%s" % (h["r"], h["close"], h["score"], h["note"]))
        for w in h["why"]:
            lines.append("- " + w)
        lines.append("")
    lines.append("風（⑧）は直前情報で要確認：6m以上 or 北・北西でスコア+1")
    if tool_url:
        lines.append("")
        lines.append("👉 ツールで詳細を見る: " + tool_url)
    body = "\n".join(lines)

    token = os.environ.get("GITHUB_TOKEN")
    if not token or not repo:
        print("=== ドライラン（トークンなし） ===")
        print(title)
        print(body)
        return

    # 二重投稿防止：同じ日付のIssueが既にあればスキップ
    try:
        existing = gh_api("https://api.github.com/repos/%s/issues?state=all&per_page=30" % repo,
                          token=token)
        if any(today in (i.get("title") or "") for i in existing):
            print("本日分のIssueは既にあります → スキップ")
            return
    except Exception as e:
        print("既存Issue確認に失敗（続行）:", e)

    try:
        res = gh_api("https://api.github.com/repos/%s/issues" % repo,
                     data={"title": title, "body": body}, token=token)
        print("Issue作成:", res.get("html_url"))
    except Exception as e:
        print("Issue作成に失敗:", e)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # 通知の失敗でワークフロー全体を落とさない
        print("notify.py エラー（無視して続行）:", e)
