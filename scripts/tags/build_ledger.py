# -*- coding: utf-8 -*-
"""選手タグ台帳（店主の印象タグ × 機械の参考値）を作る

1行＝1選手（直近13か月に全国で出走した全員）。左から
  基本情報 → 店主タグ10列（空欄。○を入れる）→ メモ → 機械の参考値
機械の参考値は既存パイプラインの表をそのまま読み、Kファイルからは「F前後のST変化」だけ新たに計算する。

  攻め手5    … 全国5コース15走以上でまくり系1着5%以上（戸田の攻め手判定と同じ）
  カド消し   … 4コースまくり力 <= -4（戸田表）
  まくり屋   … 実4まくり率20%以上・全国4走10以上（戸田 定義B）
  壁(2号艇)  … 平和島 壁表の判定（壁強／壁弱●）
  差し巧者   … 平和島 差し表の●
  F後ST変化  … 同じ審査期間内にF/Lを持った後の平均ST − 持つ前の平均ST（＋＝遅くなった）
  F慣れ候補  … F後の走数10以上で ST変化 0.00以下（全く遅くならない人）／ 慎重型 … +0.05以上

出力: data/tags/racers_ledger.csv（UTF-8 BOM、そのままスプレッドシートに読める）
実行: python scripts/tags/build_ledger.py
"""
import os, re, csv, glob
from collections import defaultdict
import lhafile

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
os.chdir(REPO)
OUT = 'data/tags/racers_ledger.csv'
TAGS = ['攻める', '攻めない', '伸び型を好む', '出足型', '壁になる', '差し屋', 'スタート早い', 'スタート遅い', '前付け', 'F慣れ']
REF = ['攻め手5', 'カド消し', 'まくり屋', '壁(2号艇)', '差し巧者', 'まくり系ゼロ',
       '4走', '4まくり系1着率', '5走', '5まくり系1着率', '6走', '6まくり系1着率', '4まくり力',
       '1着数', '逃げ', '差し', 'まくり', 'まくり差し', '抜き', '恵まれ',
       '平均ST', 'F本数', 'L本数', 'F前ST', 'F後ST', 'F後ST変化', 'F後の走数', 'F慣れ候補']


def read_lzh(p):
    try:
        lf = lhafile.Lhafile(p)
        return lf.read(lf.infolist()[0].filename).decode('shift_jis', 'replace')
    except Exception:
        return ''


def period(date):
    """級別審査期間: 5〜10月=前期, 11〜4月=後期（年をまたぐ）"""
    y, m = int(date[:4]), int(date[5:7])
    return ('%d前' % y) if 5 <= m <= 10 else ('%d後' % (y if m >= 11 else y - 1))


# ---------- Kファイル: 選手ごとの (日付, ST, F, L) ----------
def scan_k():
    rows = defaultdict(list)            # regno -> [(date, st or None, isF, isL)]
    for p in sorted(glob.glob('data/lzh_k/k*.lzh')):
        d = os.path.basename(p)[1:7]
        date = '20%s-%s-%s' % (d[:2], d[2:4], d[4:6])
        for ln in read_lzh(p).split('\n'):
            if not (len(ln) > 21 and ln[:2] == '  ' and ln[6].isdigit() and ln[8:12].isdigit()):
                continue
            t = ln[21:].split()
            st_raw = t[4] if len(t) > 4 else ''
            pos = ln[2:4].strip()
            isF = pos == 'F' or st_raw.startswith('F')
            isL = pos == 'L' or st_raw.startswith('L')
            st = None
            if not isF and not isL:
                try:
                    st = float(st_raw)
                except ValueError:
                    st = None
            rows[ln[8:12]].append((date, st, isF, isL))
    return rows


def f_profile(recs):
    """F/L持ちになる前後の平均STを比べる"""
    recs = sorted(recs, key=lambda r: r[0])
    nF = sum(1 for r in recs if r[2])
    nL = sum(1 for r in recs if r[3])
    all_st = [r[1] for r in recs if r[1] is not None]
    avg = sum(all_st) / len(all_st) if all_st else None
    acc = defaultdict(set)              # 審査期間 -> F/Lを切った日付
    for date, st, isF, isL in recs:
        if isF or isL:
            acc[period(date)].add(date)
    before, after = [], []
    for date, st, isF, isL in recs:
        if st is None:
            continue
        held = any(dd < date for dd in acc.get(period(date), ()))
        (after if held else before).append(st)
    b = sum(before) / len(before) if before else None
    a = sum(after) / len(after) if after else None
    diff = (a - b) if (a is not None and b is not None) else None
    return dict(avg=avg, nF=nF, nL=nL, st_before=b, st_after=a, n_after=len(after), diff=diff)


# ---------- Bファイル: 最新の 級別・支部・年齢・勝率 ----------
def scan_b():
    info = {}
    pat = re.compile(r'^\s*[1-6] (\d{4})(.{4})(\d{2})(.{2})(\d{2})(A1|A2|B1|B2)\s+([\d.]+)')
    for p in sorted(glob.glob('data/lzh_b/b*.lzh'), reverse=True):      # 新しい順に見て最初の1件
        for ln in read_lzh(p).split('\n'):
            m = pat.match(ln)
            if m and m.group(1) not in info:
                info[m.group(1)] = dict(name=m.group(2).replace('　', '').strip(), age=m.group(3),
                                        branch=m.group(4).strip(), grade=m.group(6), win=m.group(7))
    return info


def fnum(x, nd=1):
    return '' if x is None else ('%.*f' % (nd, x))


def load_csv(path, key):
    with open(path, encoding='utf-8-sig') as f:
        return {r[key]: r for r in csv.DictReader(f)}


def main():
    krows = scan_k()
    binfo = scan_b()

    course = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0]))    # regno -> course -> [n, r1, mk1]
    with open('data/edogawa/nat_course.csv', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            a = course[r['regno']][r['course']]
            a[0] += float(r['n']); a[1] += float(r['r1']); a[2] += float(r['mk1'])
    prof = load_csv('data/全国_決まり手プロフィール.csv', 'regno')
    mak = load_csv('data/toda/toda_makuriya.csv', '登番')
    wall = load_csv('data/heiwajima/hw_wall.csv', 'regno')
    sashi = load_csv('data/heiwajima/hw_c2sashi.csv', 'regno')

    hdr = ['登番', '選手名', '級別', '支部', '年齢', '全国勝率', '出走(13か月)'] + TAGS + ['メモ'] + REF
    out = []
    for regno, recs in krows.items():
        b = binfo.get(regno, {})
        pr = prof.get(regno, {})
        name = b.get('name') or pr.get('選手名', '')
        c4, c5, c6 = course[regno]['4'], course[regno]['5'], course[regno]['6']

        def rate(a):
            return fnum(a[2] / a[0] * 100, 1) if a[0] else ''

        atk5 = '○' if c5[0] >= 15 and c5[2] / c5[0] >= 0.05 else ''
        m = mak.get(regno)
        kado = '○' if m and float(m['まくり力']) <= -4 else ''
        makuriya = '○' if m and float(m['実4まくり率']) >= 20 and int(m['全国4走']) >= 10 else ''
        fp = f_profile(recs)
        if fp['diff'] is None or fp['n_after'] < 10 or (fp['nF'] + fp['nL']) == 0:
            fnare = ''
        elif round(fp['diff'], 2) <= 0.0:
            fnare = '候補'
        elif round(fp['diff'], 2) >= 0.05:
            fnare = '慎重型'
        else:
            fnare = ''
        ref = [atk5, kado, makuriya, wall.get(regno, {}).get('壁', ''),
               '●' if sashi.get(regno, {}).get('差し巧者') == '●' else '',
               '○' if pr.get('まくり系ゼロ') else '',
               int(c4[0]), rate(c4), int(c5[0]), rate(c5), int(c6[0]), rate(c6),
               m['まくり力'] if m else '',
               pr.get('一着', ''), pr.get('逃げ', ''), pr.get('差し', ''), pr.get('まくり', ''),
               pr.get('まくり差し', ''), pr.get('抜き', ''), pr.get('恵まれ', ''),
               fnum(fp['avg'], 2), fp['nF'], fp['nL'], fnum(fp['st_before'], 2), fnum(fp['st_after'], 2),
               ('%+.2f' % fp['diff']) if fp['diff'] is not None else '', fp['n_after'], fnare]
        out.append([regno, name, b.get('grade', ''), b.get('branch', ''), b.get('age', ''), b.get('win', ''),
                    len(recs)] + [''] * len(TAGS) + [''] + ref)
    out.sort(key=lambda r: -r[6])                       # 出走の多い順（現役で走っている人が上）
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(hdr)
        w.writerows(out)

    col = {h: i for i, h in enumerate(hdr)}
    cnt = lambda h, v: sum(1 for r in out if r[col[h]] == v)
    print('選手 %d 人 → %s' % (len(out), OUT))
    print('  機械判定: 攻め手5 %d ／ カド消し %d ／ まくり屋 %d ／ 壁強 %d ／ 差し巧者 %d ／ F慣れ候補 %d ／ 慎重型 %d'
          % (cnt('攻め手5', '○'), cnt('カド消し', '○'), cnt('まくり屋', '○'), cnt('壁(2号艇)', '壁強●'),
             cnt('差し巧者', '●'), cnt('F慣れ候補', '候補'), cnt('F慣れ候補', '慎重型')))


if __name__ == '__main__':
    main()
