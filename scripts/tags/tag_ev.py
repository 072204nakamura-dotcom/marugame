# -*- coding: utf-8 -*-
"""店主の印象タグ × 結果 × 確定オッズ — さかのぼり検証

仮説（店主）: 「3枠と4枠が攻めると、5枠・6枠の出目が出る」

  攻めの定義は2系統を並べて出す:
    店主   … 台帳の「攻め」評価 4 以上（data/tags/racer_tags.json）
    機械   … 全国3コース・4コースのまくり系1着率が上位（nat_course.csv）※店主の評価が貯まるまでの仮の入力
  レースの分類: 3号艇・4号艇の両方が攻め型／片方だけ／どちらも違う（対照）

  出力する数字（全国24場・Kファイル約13か月ぶん）:
    5・6号艇の1着率、5か6が2着以内に入る率、1号艇の1着率
  確定オッズがある8場ぶん:
    頭5帯・頭6帯の均等買いROIと、市場の含意確率（実測との差＝市場が見落としているか）

実行: python scripts/tags/tag_ev.py            … 両系統
      python scripts/tags/tag_ev.py --min-n 15  … 機械判定の走数しきい値
"""
import os, re, csv, json, glob, math, argparse, unicodedata
from collections import defaultdict
import lhafile

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
os.chdir(REPO)
RACE_HDR = re.compile(r'^\s{2,}(\d{1,2})R\s+(.*?)\s+H(\d{3,4})m')
SANTAN = re.compile(r'3連単\s+([1-6]-[1-6]-[1-6])\s+(\d+)')
ODDS_VENUES = [d for d in sorted(os.listdir('data/odds')) if os.path.isdir(os.path.join('data/odds', d))]


def read_lzh(p):
    try:
        lf = lhafile.Lhafile(p)
        return lf.read(lf.infolist()[0].filename).decode('shift_jis', 'replace')
    except Exception:
        return ''


def is_fin(l):
    return len(l) > 21 and l[:2] == '  ' and l[6].isdigit() and l[8:12].isdigit()


def parse_k(path):
    """Kファイル1日ぶん → [(jcd, date, rno, boats{艇番:登番}, combo, payout)]"""
    raw = read_lzh(path)
    d = os.path.basename(path)[1:7]
    date = '20%s-%s-%s' % (d[:2], d[2:4], d[4:6])
    out = []
    for m in re.finditer(r'(\d{2})KBGN(.*?)\1KEND', raw, re.S):
        jcd, blk = m.group(1), m.group(2)
        cur = None
        for ln in blk.split('\n'):
            h = RACE_HDR.match(ln)
            if h and ('風' in ln or '波' in ln):
                if cur and cur['combo']:
                    out.append(cur)
                cur = dict(jcd=jcd, date=date, rno=int(h.group(1)), boats={}, combo='', payout=0)
                continue
            if cur is None:
                continue
            if is_fin(ln):
                cur['boats'][ln[6]] = ln[8:12]
                continue
            sm = SANTAN.search(unicodedata.normalize('NFKC', ln))
            if sm and not cur['combo']:
                cur['combo'], cur['payout'] = sm.group(1), int(sm.group(2))
        if cur and cur['combo']:
            out.append(cur)
    return [r for r in out if len(r['boats']) >= 5]


def load_odds():
    """8場の確定オッズ {(jcd,date,rno): {combo: odds}}"""
    odds = {}
    for jcd in ODDS_VENUES:
        for fn in sorted(os.listdir(os.path.join('data/odds', jcd))):
            if not fn.endswith('.csv'):
                continue
            with open(os.path.join('data/odds', jcd, fn), encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    if row['odds']:
                        odds.setdefault((jcd, row['date'], int(row['race'])), {})[row['combo']] = float(row['odds'])
    return {k: v for k, v in odds.items() if len(v) >= 100}


def implied_head(om, head):
    inv = {c: 1.0 / o for c, o in om.items() if o > 0}
    t = sum(inv.values())
    return sum(v for c, v in inv.items() if c.startswith(head + '-')) / t if t else 0.0


# ---------------- 攻め型の定義（2系統） ----------------
def attackers_owner(min_score=4):
    p = 'data/tags/racer_tags.json'
    if not os.path.exists(p):
        return set(), 0
    d = json.load(open(p, encoding='utf-8'))
    rated = {r for r, v in d['racers'].items() if v.get('atk')}
    return {r for r, v in d['racers'].items() if (v.get('atk') or 0) >= min_score}, len(rated)


def attackers_machine(min_n=15, top_share=0.25):
    """全国3・4コースのまくり系1着率（2コース合算）で上位 top_share を攻め型とする"""
    agg = defaultdict(lambda: [0.0, 0.0])
    with open('data/edogawa/nat_course.csv', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['course'] in ('3', '4'):
                a = agg[r['regno']]
                a[0] += float(r['n']); a[1] += float(r['mk1'])
    rates = {r: mk / n for r, (n, mk) in agg.items() if n >= min_n}
    if not rates:
        return set(), 0.0
    cut = sorted(rates.values(), reverse=True)[max(0, int(len(rates) * top_share) - 1)]
    return {r for r, v in rates.items() if v >= cut}, cut


# ---------------- 集計 ----------------
def z(a, n, p0):
    """実測率 a（n回）と基準率 p0 の差の z 値"""
    se = math.sqrt(p0 * (1 - p0) / n) if n and 0 < p0 < 1 else 0
    return (a - p0) / se if se else 0.0


def summarize(label, races, odds, base=None):
    n = len(races)
    if not n:
        print('  %-26s データなし' % label); return None
    w5 = sum(1 for r in races if r['combo'][0] == '5')
    w6 = sum(1 for r in races if r['combo'][0] == '6')
    w1 = sum(1 for r in races if r['combo'][0] == '1')
    top2_56 = sum(1 for r in races if r['combo'][0] in '56' or r['combo'][2] in '56')
    r56 = (w5 + w6) / n
    line = '  %-26s n=%5d  5・6頭 %5.1f%%  (5頭 %4.1f%% 6頭 %4.1f%%)  5か6が2着内 %5.1f%%  1頭 %5.1f%%' % (
        label, n, r56 * 100, w5 / n * 100, w6 / n * 100, top2_56 / n * 100, w1 / n * 100)
    if base:
        line += '  対照比 %+.1fpt (z=%+.1f)' % ((r56 - base) * 100, z(r56, n, base))
    print(line)
    # オッズがある分だけ EV
    ev = [(r, odds[(r['jcd'], r['date'], r['rno'])]) for r in races if (r['jcd'], r['date'], r['rno']) in odds]
    if ev:
        for head in ('5', '6'):
            m = len(ev)
            hit = sum(1 for r, om in ev if r['combo'][0] == head)
            ret = sum(r['payout'] for r, om in ev if r['combo'][0] == head)
            imp = sum(implied_head(om, head) for r, om in ev) / m
            act = hit / m
            print('      └ オッズあり n=%4d 頭%s帯20点均等: 的中 %4.1f%% / 市場含意 %4.1f%% (差 %+.1fpt, z=%+.1f)  ROI %5.1f%%' % (
                m, head, act * 100, imp * 100, (act - imp) * 100, z(act, m, imp) if 0 < imp < 1 else 0, ret / (m * 2000) * 100))
    return r56


def load_grade():
    """台帳の級別（最新の番組表から）: regno -> 'A' / 'B'"""
    g = {}
    p = 'data/tags/racers_ledger.csv'
    if os.path.exists(p):
        with open(p, encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                g[r['登番']] = 'A' if r['級別'].startswith('A') else 'B'
    return g


def run(title, attackers, races, odds, grade=None):
    print()
    print('=== %s ===' % title)
    both = [r for r in races if r['boats'].get('3') in attackers and r['boats'].get('4') in attackers]
    one = [r for r in races if (r['boats'].get('3') in attackers) != (r['boats'].get('4') in attackers)]
    none = [r for r in races if r['boats'].get('3') not in attackers and r['boats'].get('4') not in attackers]
    base = summarize('対照（3・4とも攻め型でない）', none, odds)
    summarize('片方だけ攻め型', one, odds, base)
    summarize('★ 3・4とも攻め型', both, odds, base)
    # 参考: 3だけ／4だけ
    only3 = [r for r in one if r['boats'].get('3') in attackers]
    only4 = [r for r in one if r['boats'].get('4') in attackers]
    summarize('  （3だけ攻め型）', only3, odds, base)
    summarize('  （4だけ攻め型）', only4, odds, base)
    if not grade:
        return
    # 強さの影響を分ける: 3・4号艇の級別をそろえて比べる（A級2人／B級2人）
    print('  --- 級別をそろえた比較（攻め型の効果だけを見る）---')
    for lab, gs in (('3・4とも A級', ('A', 'A')), ('3・4とも B級', ('B', 'B'))):
        sub = [r for r in races if grade.get(r['boats'].get('3')) == gs[0] and grade.get(r['boats'].get('4')) == gs[1]]
        n_ = [r for r in sub if r['boats'].get('3') not in attackers and r['boats'].get('4') not in attackers]
        b_ = [r for r in sub if r['boats'].get('3') in attackers and r['boats'].get('4') in attackers]
        bb = summarize('%s・攻め型でない' % lab, n_, odds)
        summarize('%s・★ 両方攻め型' % lab, b_, odds, bb)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-n', type=int, default=15)
    ap.add_argument('--top', type=float, default=0.25, help='機械判定: まくり系1着率の上位何割を攻め型とするか')
    ap.add_argument('--owner-min', type=int, default=4, help='店主判定: 攻め評価のしきい値')
    a = ap.parse_args()

    races = []
    for p in sorted(glob.glob('data/lzh_k/k*.lzh')):
        races.extend(parse_k(p))
    odds = load_odds()
    print('Kファイル %d日 → 全国 %d レース（3連単あり）／ 確定オッズあり %d レース（%s）' % (
        len(glob.glob('data/lzh_k/k*.lzh')), len(races), sum(1 for r in races if (r['jcd'], r['date'], r['rno']) in odds),
        '・'.join(ODDS_VENUES)))

    grade = load_grade()
    own, n_rated = attackers_owner(a.owner_min)
    print('店主の評価: 攻め評価あり %d 人、うち %d 以上 = %d 人' % (n_rated, a.owner_min, len(own)))
    if len(own) >= 20:
        run('店主判定（攻め %d 以上）' % a.owner_min, own, races, odds, grade)
    else:
        print('  → 店主判定は 20 人以上貯まってから集計します（今は表示のみ）')

    mach, cut = attackers_machine(a.min_n, a.top)
    print('機械判定: 全国3・4コース %d走以上でまくり系1着率が上位 %.0f%%（%.1f%% 以上）= %d 人' % (a.min_n, a.top * 100, cut * 100, len(mach)))
    run('機械判定（仮の入力）', mach, races, odds, grade)
    print()
    print('読み方: 「★ 3・4とも攻め型」の 5・6頭率が対照より高く z>=2 なら仮説は本物。'
          'オッズ行の「差」がプラスで ROI が 100% を超えれば、市場もそれを見落としている。')


if __name__ == '__main__':
    main()
