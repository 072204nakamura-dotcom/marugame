# -*- coding: utf-8 -*-
"""選手タグ台帳（Googleスプレッドシート）から店主の評価を取り込む

台帳: https://docs.google.com/spreadsheets/d/1h3tlHkd5t5brxsOaYnuJTfGcepg1WIJD8s4-XmkYzIY/
      （リンクを知っている全員が閲覧可 → CSV書き出しURLを認証なしで読める）

台帳の評価列（2026-09-11 に入力しやすい形へ変更）:
  攻め … 1〜5（1=まったく攻めない 3=普通 5=攻める）
  ST   … 1〜5（1=遅い 5=早い）
  型   … 複数選択（伸び型／出足型／壁／差し屋／前付け／F慣れ）カンマ区切りで入る
  メモ … 自由記述

出力:
  data/tags/racer_tags.json … {regno: {name, atk, st, types:[...], memo}} 何か入っている選手だけ
  data/tags/racer_tags.csv  … 同じ内容の表（人が読む用・差分が追いやすい）
各ページは tags.js が racer_tags.json を読んで、出走表の選手名の横にバッジを出す。

実行: python scripts/tags/fetch_tags.py   （毎日 JST 4:50 に tags.yml が実行）
取得に失敗したときは何も書き換えない（前回のタグがそのまま残る）。
"""
import os, io, re, csv, json, datetime, urllib.request

SHEET_ID = '1h3tlHkd5t5brxsOaYnuJTfGcepg1WIJD8s4-XmkYzIY'
URL = 'https://docs.google.com/spreadsheets/d/%s/export?format=csv&gid=0' % SHEET_ID
OUT_JSON = 'data/tags/racer_tags.json'
OUT_CSV = 'data/tags/racer_tags.csv'
TYPES = ['伸び型', '出足型', '壁', '差し屋', '前付け', 'F慣れ']


def fetch():
    req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0 (marugame-tool)'})
    raw = urllib.request.urlopen(req, timeout=60).read().decode('utf-8-sig')
    rows = list(csv.DictReader(io.StringIO(raw)))
    if not rows or '登番' not in rows[0] or '攻め' not in rows[0] or '型' not in rows[0]:
        raise RuntimeError('台帳の形が想定と違う（列見出しに 登番／攻め／型 が無い）')
    return rows


def score(v):
    v = (v or '').strip()
    m = re.match(r'^[1-5]$', v)
    return int(v) if m else None


def main():
    rows = fetch()
    tagged = {}
    for r in rows:
        regno = (r.get('登番') or '').strip()
        if not regno:
            continue
        atk, st = score(r.get('攻め')), score(r.get('ST'))
        types = [t.strip() for t in re.split(r'[,、，/／\s]+', r.get('型') or '') if t.strip()]
        types = [t for t in types if t in TYPES] or types          # 想定外の語もそのまま残す
        memo = (r.get('メモ') or '').strip()
        if atk or st or types or memo:
            tagged[regno] = dict(name=(r.get('選手名') or '').replace('　', '').replace(' ', ''),
                                 atk=atk, st=st, types=types, memo=memo)
    now = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).strftime('%Y-%m-%d %H:%M')
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(dict(updated=now, sheet=SHEET_ID, total=len(rows), tagged=len(tagged), racers=tagged),
                  f, ensure_ascii=False, indent=1)
    with open(OUT_CSV, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['登番', '選手名', '攻め', 'ST', '型', 'メモ'])
        for regno, v in sorted(tagged.items()):
            w.writerow([regno, v['name'], v['atk'] or '', v['st'] or '', '、'.join(v['types']), v['memo']])
    n_atk = sum(1 for v in tagged.values() if v['atk'])
    n_st = sum(1 for v in tagged.values() if v['st'])
    n_ty = sum(1 for v in tagged.values() if v['types'])
    print('台帳 %d 人 → 評価あり %d 人（攻め%d・ST%d・型%d）' % (len(rows), len(tagged), n_atk, n_st, n_ty))


if __name__ == '__main__':
    main()
