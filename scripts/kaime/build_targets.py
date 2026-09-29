# -*- coding: utf-8 -*-
"""買い目シグナル — 毎朝の候補作り（GitHub Actions・JST 5:25）

当日のBファイル（番組表）を取り、対象場の全レースについて
  最終日か／1号艇の出走表内勝率順位／外(2〜6号艇)の勝率上位3艇／締切時刻
を計算し、番組・季節・日程の条件だけで当てはまるルールを付けて
data/kaime/targets/YYYY-MM-DD.json と latest.json に書き出す。
風とオッズの判定は締切約5分前に GAS（gas/kaime/Code.gs）が行う。

使い方
  python scripts/kaime/build_targets.py
  DATE_OVERRIDE=2026-10-12 python scripts/kaime/build_targets.py   # 日付を指定して動作確認
"""
import os
import io
import re
import sys
import json
import unicodedata
import urllib.request
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules import TARGET_VENUES, VENUE_NAMES, NEED_3T, NEED_2T, NEED_3F, match_rules  # noqa: E402

JST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
OUT_DIR = os.path.join(ROOT, 'data', 'kaime', 'targets')

HEAD_RE = re.compile(r'^\s*(\d{1,2})R\s+(\S+).*?締切予定(\d{1,2}):(\d{2})')
BOAT_RE = re.compile(r'^([1-6]) (\d{4})(.+?)(\d{2})(\D+?)(\d{2})([AB][12])\s+([\d.]+)\s+([\d.]+)')


def fetch_bfile(dt):
    """当日のBファイルをShift-JISのテキストで返す。取れなければ None。"""
    url = 'https://www1.mbrace.or.jp/od2/B/%s/b%s.lzh' % (dt.strftime('%Y%m'), dt.strftime('%y%m%d'))
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (marugame-tool)'})
    raw = urllib.request.urlopen(req, timeout=120).read()
    if raw[:20].lower().startswith(b'<html'):
        return None
    import lhafile
    lf = lhafile.Lhafile(io.BytesIO(raw))
    return lf.read(lf.infolist()[0].filename).decode('shift_jis', errors='replace')


def parse_venue(raw, jcd):
    """場ブロックを読んで (is_final_day, races) を返す。開催なしなら None。"""
    m = re.search(r'%sBBGN(.*?)%sBEND' % (jcd, jcd), raw, re.S)
    if not m:
        return None
    races, cur = [], None
    for ln in m.group(1).splitlines():
        n = unicodedata.normalize('NFKC', ln)
        mh = HEAD_RE.match(n)
        if mh:
            cur = dict(race=int(mh.group(1)), rname=mh.group(2),
                       deadline='%02d:%s' % (int(mh.group(3)), mh.group(4)), wins={})
            races.append(cur)
            continue
        mb = BOAT_RE.match(n)
        if mb and cur is not None:
            cur['wins'][int(mb.group(1))] = float(mb.group(8))
    races = [r for r in races if len(r['wins']) == 6]
    if not races:
        return None
    # 最終日：レース名に「優勝」を含み「準優」を含まないレースがある（日目の数字では判定しない）
    is_final = any('優勝' in r['rname'] and '準優' not in r['rname'] for r in races)
    return is_final, races


def race_features(wins):
    """wins={艇番: 全国勝率} → rank1, boat_win, outer_top3, weakest_is_boat1_gap"""
    w1 = wins[1]
    rank1 = 1 + sum(1 for b in range(2, 7) if wins[b] > w1)          # 同率は上位扱い（method='min'）
    outer_top3 = sorted(range(2, 7), key=lambda b: (-wins[b], b))[:3]  # 同率は艇番の若い方を上
    others = sorted(wins[b] for b in range(2, 7))
    gap = round(others[0] - w1, 2) if others[0] > w1 else None       # 1号艇が単独最下位のときだけ
    return dict(rank1=rank1, boat_win=[wins[b] for b in range(1, 7)],
                outer_top3=outer_top3, weakest_is_boat1_gap=gap)


def build(raw, dt):
    out = []
    for jcd in TARGET_VENUES:
        pv = parse_venue(raw, jcd) if raw else None
        if not pv:
            continue
        is_final, races = pv
        for r in races:
            f = race_features(r['wins'])
            ids = match_rules(jcd, dt.month, is_final, r['race'], f['rank1'], f['weakest_is_boat1_gap'])
            if not ids:
                continue
            out.append(dict(
                jcd=jcd, venue=VENUE_NAMES[jcd], race=r['race'], deadline=r['deadline'],
                rname=r['rname'], is_final_day=is_final, **f, rules=ids,
                needs=dict(wind=True,                       # 風を見ないルールも記録のため取る
                           odds3t=bool(set(ids) & NEED_3T),
                           odds2t=bool(set(ids) & NEED_2T),
                           odds3f=bool(set(ids) & NEED_3F))))
    out.sort(key=lambda x: (x['deadline'], x['jcd'], x['race']))
    return out


def main():
    today = datetime.now(JST)
    if os.environ.get('DATE_OVERRIDE'):
        today = datetime.strptime(os.environ['DATE_OVERRIDE'], '%Y-%m-%d').replace(tzinfo=JST)
    raw = None
    try:
        raw = fetch_bfile(today)
    except Exception as e:                      # 取れなくても候補ゼロで出す（ページが「本日の候補なし」を出せるように）
        print('Bファイル取得失敗:', e)
    races = build(raw, today)
    obj = dict(date=today.strftime('%Y-%m-%d'),
               generated_at=datetime.now(JST).isoformat(timespec='seconds'),
               bfile_ok=raw is not None, races=races)
    os.makedirs(OUT_DIR, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, indent=1)
    for name in (obj['date'] + '.json', 'latest.json'):
        with open(os.path.join(OUT_DIR, name), 'w', encoding='utf-8') as f:
            f.write(txt)
    print('候補 %d レース → %s' % (len(races), OUT_DIR))
    for r in races:
        print('  %s %s %2dR %s %s' % (r['deadline'], r['venue'], r['race'], ','.join(r['rules']),
                                     '最終日' if r['is_final_day'] else ''))


if __name__ == '__main__':
    main()
