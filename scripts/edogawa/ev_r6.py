# -*- coding: utf-8 -*-
"""江戸川(03) 検証 その3 — 「6R の +2点（2〜5R は +1点）」は残すべきか

仕様書 E-5 は 6R を「採用（従・暫定）」とした：顔ぶれ補正後の残差 −9.0pt(z=−2.62, n=175)、
前後半WFも一致。ただし「なぜ5Rや4Rでなく6Rが底か」は未解明のまま。
2026-10 に直近窓で 6R 37.4% / 3R 37.1% と底が入れ替わったため、窓の外で確かめる。

測るもの（期間ごと）
  A) レース番号別のイン1着率と、顔ぶれから見込まれる率（期待）との差＝残差
     期待＝1コースに入った選手の「全国1コース1着率」（同じ期間・江戸川以外のレースで集計、
     経験ベイズ縮小 k=20。edogawa_daily.py の nige_exp と同じ式）
  B) 6R の残差 − 2〜5R の残差 ＝ 6R に上乗せの+1点が乗る根拠。z はその差の標準誤差で割ったもの
  C) 仕様書を作った窓（〜2026-07）より前の3年は、仕様書と重ならない独立データ

Kファイルの置き場
  data/lzh_k/          … 直近1年（リポジトリに入っている）
  環境変数 EDO_OLD_K   … それより古いKファイルのフォルダ（任意）

実行: EDO_OLD_K=/path/to/edo_k python scripts/edogawa/ev_r6.py
"""
import os
import sys
import math
import datetime
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lhafile  # noqa: E402
import edogawa_daily as e  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
DIRS = [os.path.join(REPO, 'data', 'lzh_k')]
if os.environ.get('EDO_OLD_K'):
    DIRS.insert(0, os.environ['EDO_OLD_K'])

PERIODS = [
    ('2022/10〜2023/09', '2022-10-01', '2023-09-30'),
    ('2023/10〜2024/09', '2023-10-01', '2024-09-30'),
    ('2024/10〜2025/09', '2024-10-01', '2025-09-30'),
    ('2025/10〜2026/10（直近）', '2025-10-01', '2026-10-31'),
]
OOS = ('仕様書後 2026/08〜', '2026-08-01', '2026-10-31')   # 仕様書の窓のあと（本当の後出しデータ）
K = 20


def load_days():
    """{date: (nat, ed_races_with_boats)}。ed は c1 の選手と勝敗が要るので parse を少し拡張して持つ。"""
    files = {}
    for d in DIRS:
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if fn.startswith('k') and fn.endswith('.lzh'):
                files[fn] = os.path.join(d, fn)
    out = {}
    for fn in sorted(files):
        try:
            dt = datetime.datetime.strptime(fn[1:7], '%y%m%d').date()
            lf = lhafile.Lhafile(files[fn])
            raw = lf.read(lf.infolist()[0].filename).decode('shift_jis', errors='replace')
        except Exception:
            continue
        out[dt] = raw
    return out


def ed_races_with_c1(raw, dt):
    """江戸川の各レースについて (rno, nichime, c1の登番, c1が1着か) を返す。"""
    res = []
    import re
    import unicodedata
    for vm in re.finditer(r'(\d{2})KBGN(.*?)\1KEND', raw, re.S):
        if vm.group(1) != e.JCD:
            continue
        blk = vm.group(2)
        md = e.DAY_RE.search(unicodedata.normalize('NFKC', blk[:400]))
        nichime = int(md.group(1)) if md else None
        cur = None
        races = []
        for line in blk.split('\n'):
            hm = e.RACE_HDR.match(line)
            if hm and ('風' in line or '波' in line):
                cur = dict(rno=int(hm.group(1)), boats=[])
                races.append(cur)
                continue
            if cur is not None and e.is_finisher(line):
                tail = line[21:].split()
                course = tail[3] if (len(tail) >= 4 and tail[3] in ('1', '2', '3', '4', '5', '6')) else ''
                cur['boats'].append((line[2:4].strip(), line[8:12], course))
        for r in races:
            c1 = next((b for b in r['boats'] if b[2] == '1'), None)
            if c1 and any(b[0] == '01' for b in r['boats']):
                res.append((r['rno'], nichime, c1[1], 1 if c1[0] == '01' else 0))
    return res


def stats(days, lo, hi):
    lo, hi = datetime.date.fromisoformat(lo), datetime.date.fromisoformat(hi)
    jn, jw = defaultdict(int), defaultdict(int)
    ed = []
    for dt, raw in days.items():
        if not (lo <= dt <= hi):
            continue
        nat = e.parse_k_day(raw, dt)[0]
        for regno, course, _teiban, chaku, _st, _mk, is_ed in nat:
            if course == 1 and not is_ed:              # 地力は江戸川以外で測る（自己参照を避ける）
                jn[regno] += 1
                jw[regno] += 1 if chaku == '01' else 0
        ed += [(dt,) + x for x in ed_races_with_c1(raw, dt)]
    tn, tw = sum(jn.values()), sum(jw.values())
    p0 = tw / tn if tn else 0.55

    def exp(r):
        return (jw[r] + K * p0) / (jn[r] + K)

    by = defaultdict(lambda: [0, 0, 0.0, 0.0])     # n, win, exp_sum, var_sum
    for _dt, rno, nichime, reg, win in ed:
        p = exp(reg)
        for key in (rno, 'all', 'z25' if 2 <= rno <= 5 else None, 'day1_6' if (nichime == 1 and rno == 6) else None,
                    'day1_25' if (nichime == 1 and 2 <= rno <= 5) else None):
            if key is None:
                continue
            a = by[key]
            a[0] += 1
            a[1] += win
            a[2] += p
            a[3] += p * (1 - p)
    return by, len({x[0] for x in ed})


def line(label, a):
    n, w, es, vs = a
    if not n:
        return '  %-6s データなし' % label
    res = (w - es) / n * 100
    z = (w - es) / math.sqrt(vs) if vs else 0
    return '  %-6s n=%4d  実測 %5.1f%%  期待 %5.1f%%  残差 %+5.1fpt (z=%+.2f)' % (
        label, n, w / n * 100, es / n * 100, res, z)


def diff_6_vs_25(by):
    """6R残差 − 2〜5R残差 と、その z（独立とみなした差の標準誤差）"""
    a6, a25 = by[6], by['z25']
    if not a6[0] or not a25[0]:
        return None
    r6 = (a6[1] - a6[2]) / a6[0]
    r25 = (a25[1] - a25[2]) / a25[0]
    se = math.sqrt(a6[3] / a6[0] ** 2 + a25[3] / a25[0] ** 2)
    return (r6 - r25) * 100, (r6 - r25) / se if se else 0


def main():
    days = load_days()
    print('Kファイル %d日分（%s〜%s）' % (len(days), min(days), max(days)))
    pooled = defaultdict(lambda: [0, 0, 0.0, 0.0])
    summary = []
    for label, lo, hi in PERIODS + [OOS]:
        by, nd = stats(days, lo, hi)
        print()
        print('=== %s  江戸川 %d開催日 ===' % (label, nd))
        print(line('全体', by['all']))
        for rno in range(1, 13):
            print(line('%dR' % rno, by[rno]) + ('   ← 6R' if rno == 6 else ''))
        print(line('2-5R', by['z25']))
        print(line('初日6R', by['day1_6']))
        print(line('初日2-5R', by['day1_25']))
        d = diff_6_vs_25(by)
        if d:
            rank = sorted(range(1, 13), key=lambda r: (by[r][1] - by[r][2]) / by[r][0] if by[r][0] else 9).index(6) + 1
            print('  → 6Rの上乗せ（6R残差−2〜5R残差）: %+.1fpt (z=%+.2f)／残差の深さ順位 %d位/12' % (d[0], d[1], rank))
            summary.append((label, d[0], d[1], rank, by[6][0]))
        if lo < '2025-10-01' and label != OOS[0]:
            for key, a in by.items():
                for i in range(4):
                    pooled[key][i] += a[i]
    print()
    print('=== 仕様書と重ならない3年（2022/10〜2025/09）の合算 ===')
    for rno in range(1, 13):
        print(line('%dR' % rno, pooled[rno]) + ('   ← 6R' if rno == 6 else ''))
    print(line('2-5R', pooled['z25']))
    print(line('初日6R', pooled['day1_6']))
    print(line('初日2-5R', pooled['day1_25']))
    d = diff_6_vs_25(pooled)
    if d:
        print('  → 6Rの上乗せ: %+.1fpt (z=%+.2f)' % d)
    print()
    print('=== まとめ（6Rの上乗せ＝+2点のうち「6Rだけの+1点」の根拠） ===')
    for label, dd, zz, rank, n in summary:
        print('  %-24s 上乗せ %+5.1fpt (z=%+.2f)  深さ%2d位  n=%d' % (label, dd, zz, rank, n))


if __name__ == '__main__':
    main()
