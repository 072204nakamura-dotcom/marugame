# -*- coding: utf-8 -*-
"""若松(20) 穴党ツール — 日次ビルド

毎朝1回、当日のBファイル（番組表）を取得し、若松のレースに検証済みシグナルを
当てて wakamatsu/index.html（静的ページ）を生成する。

正本ドキュメント（docs/wakamatsu/）:
  spec_wakamatsu.md … 採用/却下シグナルの正本（§4 スコア・§5 買い目フォーム）
  memo_tables.md    … 表の意味と使い方

★採点に使ってよいのは spec_wakamatsu.md §4 の表に列挙したものだけ。
  以下は採点禁止（このファイルで点数に触れさせないこと）:
    ・風速 / 波高                          … 採用済みだが朝の時点では分からない＝「直前ルール」として表示だけ
    ・風向 / 潮位 / 季節 / 開催日目        … 棄却または監視
    ・モーター                              … 却下（参考表示のみ）
    ・レース番号単独（3R＝穴 等）          … 3Rは「1号艇B級×外に勝率1.5以上上の艇」のときだけ
    ・格差（3R以外）                        … 却下（3R以外では効かない）
    ・絞りまくり                            … 若松は当地15走以上が6人・●0人で作れない

TODO(2026-11下旬): モーター交換（前回 2025-11-26）→ wm_motor_current.csv の世代起点を更新
TODO(月1回):       レース名一覧を再集計し新しい企画名が出ていないか確認
"""
import os
import re
import io
import csv
import html
import unicodedata
import urllib.request
from datetime import datetime, timezone, timedelta

from judge_wakamatsu import judge_wakamatsu_race, GAP_3R

JCD = '20'
JST = timezone(timedelta(hours=9))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
DATA_DIR = os.environ.get('WM_DATA_DIR', os.path.join(ROOT, 'data', 'wakamatsu'))
OUT_PATH = os.environ.get('WM_OUT_PATH', os.path.join(ROOT, 'wakamatsu', 'index.html'))

TODAY = datetime.now(JST)
if os.environ.get('DATE_OVERRIDE'):          # 例: DATE_OVERRIDE=2026-10-09（動作確認用）
    TODAY = datetime.strptime(os.environ['DATE_OVERRIDE'], '%Y-%m-%d').replace(tzinfo=JST)

# 特殊節（番組編成が通常と違う＝シグナルの信頼度が落ちる）の検出語
SPECIAL_MEET = ('G1', 'G2', 'G3', 'SG', 'レディース', '女子', '新鋭', 'ヤング', 'ルーキー', 'マスターズ',
                '県内選手権', '周年', 'ダービー')


# ==================================================================
# 1. Bファイル取得
# ==================================================================
def fetch_bfile(dt):
    """当日のBファイル（番組表）を取ってShift-JISのテキストで返す。取れなければ None。"""
    url = 'https://www1.mbrace.or.jp/od2/B/%s/b%s.lzh' % (dt.strftime('%Y%m'), dt.strftime('%y%m%d'))
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    raw = urllib.request.urlopen(req, timeout=120).read()   # mbraceは遅い（1ファイル約10秒）
    if raw[:20].lower().startswith(b'<html'):               # 404がHTMLで返ることがある
        return None
    import lhafile
    lf = lhafile.Lhafile(io.BytesIO(raw))
    return lf.read(lf.infolist()[0].filename).decode('shift_jis', errors='replace')


# ==================================================================
# 2. 出走表パース（若松ブロック）
# ==================================================================
# 選手行の固定幅レイアウト:  ln[0]=艇番 / ln[2:6]=登番 / ln[6:10]=氏名 / ln[16:18]=級
BOAT_RE = re.compile(r'^([1-6]) (\d{4})(.{4})(\d{2})(..)(\d{2})([AB][12])(.*)$')
# 全国勝率・全国2率・当地勝率・当地2率・モーターNo・モーター2率・ボートNo・ボート2率
RATE_RE = re.compile(r'(\d+\.\d\d)\s+(\d+\.\d\d)\s+(\d+\.\d\d)\s+(\d+\.\d\d)\s+(\d+)\s+(\d+\.\d\d)\s+(\d+)\s+(\d+\.\d\d)')
HEAD_RE = re.compile(r'^\s*(\d{1,2})R\s+(\S+)(.*)$')
DEADLINE_RE = re.compile(r'締切予定\s*(\d{1,2}:\d{2})')


def parse_wakamatsu(raw):
    """若松ブロックを解析。非開催（ブロックなし）なら None。"""
    m = re.search(r'%sBBGN(.*?)%sBEND' % (JCD, JCD), raw, re.S)
    if not m:
        return None
    lines = m.group(1).split('\n')

    title, day_n = '', None
    for ln in lines[:12]:
        n = unicodedata.normalize('NFKC', ln)
        md = re.search(r'第\s*(\d+)\s*日', n)
        if md and day_n is None:
            day_n = int(md.group(1))
    # 節タイトル：「番組表」の行の次にある、日付や「第N日」を含まない最初の行
    seen_head = False
    for ln in lines[:12]:
        s = unicodedata.normalize('NFKC', ln).strip()
        if '番組表' in s:
            seen_head = True
            continue
        if seen_head and s and '第' not in s and 'ボートレース' not in s[:7]:
            title = s
            break

    races, cur = [], None
    for ln in lines:
        n = unicodedata.normalize('NFKC', ln)
        mh = HEAD_RE.match(n)
        if mh and ('締切' in n or 'H1800' in n or 'H1200' in n):
            if cur:
                races.append(cur)
            md = DEADLINE_RE.search(n)
            cur = dict(rno=int(mh.group(1)), rname=mh.group(2),
                       fixed=('進入固定' in n),                 # 若松は5R「進入固定戦隊」
                       deadline=md.group(1) if md else '', boats=[])
            continue
        mb = BOAT_RE.match(ln)
        if mb and cur is not None:
            mr = RATE_RE.search(unicodedata.normalize('NFKC', mb.group(8)))
            cur['boats'].append(dict(
                teiban=int(ln[0]),
                regno=ln[2:6].strip(),
                name=ln[6:10].replace('　', '').strip(),
                grade=ln[16:18],
                nat_win=float(mr.group(1)) if mr else None,
                motor_no=mr.group(5) if mr else None,
                motor2=float(mr.group(6)) if mr else None))
    if cur:
        races.append(cur)
    races = [r for r in races if len(r['boats']) >= 4]
    if not races:
        return None

    is_final = any(('優勝' in unicodedata.normalize('NFKC', r['rname'])
                    and '準優' not in unicodedata.normalize('NFKC', r['rname'])) for r in races)
    for r in races:
        r['gap1'] = gap_of(r['boats'])
    return dict(title=title, day_n=day_n, is_final=is_final, races=races)


def gap_of(boats):
    """1号艇の全国勝率 −（2〜6号艇の全国勝率の最大）。取れなければ None。"""
    b1 = next((b for b in boats if b['teiban'] == 1), None)
    outs = [b['nat_win'] for b in boats if b['teiban'] != 1 and b['nat_win'] is not None]
    if not b1 or b1['nat_win'] is None or not outs:
        return None
    return round(b1['nat_win'] - max(outs), 2)


# ==================================================================
# 3. 選手表の読込
# ==================================================================
def load_csv(name, key):
    path = os.path.join(DATA_DIR, name)
    out = {}
    if not os.path.exists(path):
        print('  [warn] 表が見つかりません:', path)
        return out
    with open(path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            out[str(row[key]).strip()] = row
    return out


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


T_ST = load_csv('wm_st.csv', 'regno')                  # ST表（当地優先/全国フォールバック）
T_WALL = load_csv('wm_wall.csv', 'regno')              # 壁表（全国）
T_ZAN = load_csv('wm_zanshi.csv', 'regno')             # 残し表（全国）
T_MOTOR = load_csv('wm_motor_current.csv', 'motor')    # 現行世代モーター（参考表示のみ）
T_NAT1C = load_csv('nat_1c.csv', 'touban')             # 全国1コース地力（参考表示のみ）

P0 = 0.5541   # 全国1C平均逃げ率（本窓・spec §6）


def jiriki(regno):
    """全国1コース逃げ率を経験ベイズ縮小(k=20)で。参考表示のみ・採点には使わない。"""
    r = T_NAT1C.get(regno)
    if not r:
        return None
    n, w = fnum(r.get('n1c')) or 0, fnum(r.get('win1c')) or 0
    return round((w + 20 * P0) / (n + 20) * 100, 1)


# ==================================================================
# 4. 基礎率（アーカイブから算出）— 表示専用、採点には使わない
# ==================================================================
KATAME_WORDS = ('準優勝', '予選特選', '特別選抜', 'ドリー', '優勝')


def load_baselines():
    """wm_race_resid.csv から
         ・レース番号別の基礎イン率/万舟率（通常戦のみ・進入固定と特選系を除く・全日程）
         ・3R格差戦（3R×1号艇B級×格差≤−1.5）のイン率/万舟率
       を作る。"""
    path = os.path.join(DATA_DIR, 'wm_race_resid.csv')
    by_rno, kakusa = {}, []
    if not os.path.exists(path):
        print('  [warn] アーカイブが見つかりません:', path)
        return by_rno, None
    with open(path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            try:
                rno = int(row['race'])
            except (TypeError, ValueError):
                continue
            inwin = fnum(row.get('inwin'))
            payout = fnum(row.get('payout'))
            if inwin is None:
                continue
            man = 1 if (payout is not None and payout >= 10000) else 0
            o15 = 1 if (payout is not None and payout >= 1500) else 0
            nm = unicodedata.normalize('NFKC', row.get('rname', ''))
            if row.get('fixed') == '1' or any(k in nm for k in KATAME_WORDS):
                continue
            by_rno.setdefault(rno, []).append((inwin, man, o15))
            gap = fnum(row.get('gap1'))
            if rno == 3 and (row.get('g1') or '').startswith('B') and gap is not None and gap <= GAP_3R:
                kakusa.append((inwin, man, o15))

    def summarize(rows):
        n = len(rows)
        return dict(n=n, in1=round(sum(a for a, _, _ in rows) / n * 100, 1),
                    man=round(sum(b for _, b, _ in rows) / n * 100, 1),
                    o15=round(sum(c for _, _, c in rows) / n * 100, 1)) if n else None

    return {k: summarize(v) for k, v in by_rno.items()}, summarize(kakusa)


# ==================================================================
# 5. 採点（spec_wakamatsu.md §4 のみ）
# ==================================================================
def score_race(r):
    """レースを採点して (合計点, 分類, フラグ, 注記list, 型情報dict) を返す。"""
    boats = {b['teiban']: b for b in r['boats']}
    b1 = boats.get(1)
    g1 = b1['grade'] if b1 else ''
    cls, pts, flag = judge_wakamatsu_race(r['rname'], r['rno'], r.get('fixed', False), g1, r.get('gap1'))
    score = float(pts)
    marks = {b['teiban']: [] for b in r['boats']}
    notes = []
    kata = dict(zan1='', c2type='', b1=g1.startswith('B'))

    if '3R格差戦' in flag:
        notes.append('3R格差戦＝若松の主戦場（B級1号艇の外に勝率%.1f上の艇。イン29%%・15倍以上91%%）。'
                     % abs(r['gap1']))
    if '1号艇勝率最上位' in flag:
        notes.append('1号艇が出走表で勝率最上位（イン75%）＝鉄板寄り。')

    if cls == '通常戦' and b1:
        # --- 1号艇：スロー遅れ● +1 ／ 巧者（表示のみ） ---
        st = T_ST.get(b1['regno'])
        if st:
            v = fnum(st.get('採用スローST'))
            if v is not None:
                b1['st_txt'] = '%.2f（%s）' % (v, st.get('スロー源', ''))
                if v > 0.18:
                    marks[1].append('スロー遅れ●'); score += 1.0
                    notes.append('1号艇の採用スローST %.2f（>0.18）＝若松内でイン35%%まで落ちる型。' % v)
                elif v <= 0.13:
                    marks[1].append('スロー巧者')
        # --- 2号艇：壁弱● +1 ／ 壁強（表示のみ） ---
        b2 = boats.get(2)
        if b2:
            wall = T_WALL.get(b2['regno'])
            if wall:
                if wall.get('壁') == '壁弱●':
                    wt = wall.get('弱タイプ', '')
                    marks[2].append('壁弱●' + ('(%s)' % wt if wt else '')); score += 1.0
                    kata['c2type'] = wt or '壁弱'
                    if wt == '食う型':
                        notes.append('2号艇が食う型＝2号艇自身が1号艇を差す（若松内イン24%）。2アタマ本線。')
                    else:
                        notes.append('2号艇が壁弱（素通し型）＝外の攻めが通る。2号艇は頭より消し寄り。')
                elif wall.get('壁') == '壁強●':
                    marks[2].append('壁強')
    if b1:
        zan = T_ZAN.get(b1['regno'])
        if zan:
            if zan.get('型') == '飛ぶ型':
                marks[1].append('飛ぶ型'); kata['zan1'] = '飛ぶ型'
            elif zan.get('型') == '残す型':
                marks[1].append('残す型'); kata['zan1'] = '残す型'
        b1['jiriki'] = jiriki(b1['regno'])

    # --- 以下は参考表示のみ。採点には一切加算しない ---
    for b in r['boats']:
        tb = b['teiban']
        if tb != 1:
            st = T_ST.get(b['regno'])
            if st:
                col = '採用スローST' if tb <= 3 else '採用ダッシュST'
                v = fnum(st.get(col))
                if v is not None:
                    b['st_txt'] = '%.2f（%s）' % (v, st.get('スロー源' if tb <= 3 else 'ダッシュ源', ''))
        b['marks'] = marks[b['teiban']]

    return score, cls, flag, notes, kata


# ==================================================================
# 6. 買い目方針（spec_wakamatsu.md §5）
# ==================================================================
def policy_for(cls, flag, score, kata, notes):
    if cls == '進入固定':
        head = ('【鉄板・穴買い禁止】5R進入固定戦隊＝イン75%・万舟8%。'
                'このツールの主旨（穴）から外れるため見送り推奨。')
    elif cls == '特選系':
        head = ('【鉄板寄り】準優・予選特選・ドリーム・優勝はイン75%。乗るなら1頭固定・2着を4〜6号艇に寄せる'
                '（1-4-全・1-5-全）。51番人気以降は買わない。')
    elif score >= 1.0:
        if kata.get('c2type') == '食う型':
            head = '本線 2-1-全・2-3-全（8点）。2号艇が1号艇を差す型。'
        elif kata.get('zan1') == '飛ぶ型':
            head = '1号艇は飛ぶ型なので1を外し 2-3-全・3-2-全＋4-2-3・4-3-2。'
        elif kata.get('c2type') == '素通し型':
            head = '本線 3-1-全・4-1-全・3-4-全（12点）。2号艇は頭から外す。'
        else:
            head = ('本線 2-1-全・3-1-全（8点）＋ 2-3-全・3-2-全（8点）。'
                    '若松の崩れは頭が2≧3＞4、1号艇が2着に残るのは負けた時の4分の1。'
                    '3連複なら 1-2-3・1-2-4・1-2-5・1-3-4（崩れ時の4割）。')
        head += ' 3連単51番人気以降（目安170倍超）は買わない。'
    elif score <= -1.0:
        head = ('【鉄板寄り】中穴に寄せるなら1頭固定・2着を4〜6号艇（1-4-全・1-5-全・1-6-2/3）。'
                '若松のイン逃げは半分が15倍以上、その57%は2着4〜6号艇。')
    else:
        head = ('中立：1号艇B級なら直前の風・波を見る（5m以上／5cm以上で崩れ側へ）。'
                '平常なら中穴フォーム（1-4-全・1-5-全）。')
    if kata.get('b1') and cls == '通常戦':
        head += ' ★直前ルール：風5m以上か波5cm以上ならB級1号艇はイン31%まで落ちる＝崩れ度+1で読む。'
    return (head + ' ' + ' '.join(notes)).strip()


def label_for(cls, score):
    """カード右肩のラベル（クラス名, 表示文字）。"""
    if cls == '進入固定':
        return 'katame', '鉄板・見送り'
    if cls == '特選系':
        return 'katame', '鉄板寄り'
    if score >= 2.0:
        return 'ana', '穴の巣'
    if score >= 1.0:
        return 'ana', '崩れゾーン'
    if score <= -1.0:
        return 'katame', '鉄板寄り'
    return 'chukan', '中立'


# ==================================================================
# 7. HTML生成
# ==================================================================
def esc(s):
    return html.escape(str(s if s is not None else ''))


CSS = """
:root{
  --kon:#1b2340;        /* 夜の紺: ヘッダー */
  --kikyo:#3a4a8a;      /* 見出し文字 */
  --gin:#eceef4;        /* 背景 */
  --asagi:#3d7ea6;      /* 堅め */
  --shu:#c04a37;        /* 穴・警告 */
  --kincha:#b8862e;     /* 二択・注意 */
  --sumi:#2b2f36;
  --paper:#ffffff;
  --line:#d3d7e2;
}
*{margin:0;padding:0;box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{font-family:"Hiragino Kaku Gothic ProN","Hiragino Sans","Yu Gothic Medium","Noto Sans JP",sans-serif;
  background:var(--gin);color:var(--sumi);font-size:14px;line-height:1.55;font-feature-settings:"palt"}
.wrap{max-width:660px;margin:0 auto;padding-bottom:60px}

header{background:var(--kon);color:#e8eaf5;padding:14px 16px 10px}
header .brand{display:flex;align-items:baseline;gap:10px}
header h1{font-size:19px;font-weight:800;letter-spacing:.06em}
header h1 .nami{color:#ffd98a}
header .datebox{font-size:12px;opacity:.85;margin-left:auto;text-align:right;font-variant-numeric:tabular-nums}
header .meet{font-size:12px;margin-top:4px;opacity:.9}
header .meet b{color:#ffd98a;font-weight:700}
.venues{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}
.venues a,.venues .on{font-size:12px;font-weight:800;padding:4px 14px;border-radius:99px;text-decoration:none;letter-spacing:.04em}
.venues a{color:#bcc4e0;border:1px solid #46528a;background:transparent}
.venues a:active{background:#2f3a68}
.venues .on{background:#e8eaf5;color:var(--kon)}

.summary{background:var(--kon);color:#c3cbe8;font-size:11.5px;padding:0 16px 12px;letter-spacing:.02em}
.summary b{color:#ffd98a}

.terrain{background:var(--kon);padding:2px 16px 14px}
.terrain .cap{font-size:10px;color:#98a2c8;letter-spacing:.1em;margin-bottom:4px}
.tbars{display:flex;align-items:flex-end;gap:3px;height:64px}
.tbar{flex:1;display:flex;flex-direction:column;justify-content:flex-end}
.tbar .col{border-radius:2px 2px 0 0;min-height:4px}
.tbar .num{font-size:9px;text-align:center;color:#a3adcf;margin-top:3px;font-variant-numeric:tabular-nums}
.tbar .pct{font-size:8px;text-align:center;color:#7b85ab;font-variant-numeric:tabular-nums}

.banner{background:linear-gradient(90deg,#8c2f39,#c04a37);color:#fff;font-size:12.5px;font-weight:800;
  padding:8px 16px;text-align:center;letter-spacing:.04em}
.banner.day1{background:linear-gradient(90deg,#8c5a1f,#c08a2e)}
.banner.final{background:linear-gradient(90deg,#24507a,#3d7ea6)}
.failnote{background:#fdf6ec;border-bottom:1px solid #e6d3ac;color:#8a6a1f;font-size:11.5px;padding:6px 16px;text-align:center}

main{padding:12px 10px}
.card{background:var(--paper);border:1px solid var(--line);border-radius:10px;margin-bottom:12px;overflow:hidden}
.card.tetsu{border:2px solid var(--asagi)}
.card.ana{border:2px solid var(--shu)}
.card-head{display:flex;align-items:center;gap:10px;padding:10px 12px;border-bottom:1px solid var(--line)}
.rno{font-size:26px;font-weight:900;color:var(--kikyo);min-width:52px;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.rno small{font-size:13px;font-weight:700}
.rmeta{flex:1;min-width:0}
.rname{font-size:14px;font-weight:800;color:var(--kikyo)}
.deadline{font-size:11px;color:#6b7683;font-variant-numeric:tabular-nums}
.label{font-size:11px;font-weight:800;padding:3px 9px;border-radius:99px;white-space:nowrap;color:#fff}
.label.ana{background:var(--shu)}
.label.katame{background:var(--asagi)}
.label.nitaku{background:var(--kincha)}
.label.chukan{background:#7a8794}
.base{display:flex;flex-wrap:wrap;gap:12px;padding:7px 12px;background:#f1f3f8;font-size:12px;color:#4a5560;
  border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
.base b{color:var(--kikyo);font-weight:800}
.base .man b{color:var(--shu)}
.base .score{margin-left:auto;font-weight:800;color:var(--shu)}
.base .score.minus{color:var(--asagi)}
.cls{font-size:10.5px;font-weight:800;color:#5a6478;background:#e4e8f2;border-radius:4px;padding:1px 7px}
.cls.flag{background:var(--kincha);color:#fff}
.base .nn{font-size:10.5px;color:#8a94a6}

table{width:100%;border-collapse:collapse}
td{padding:5px 8px;border-bottom:1px dashed #e5e8ef;vertical-align:middle;font-size:13px}
tr:last-child td{border-bottom:none}
.bn{width:26px;height:26px;border-radius:5px;display:flex;align-items:center;justify-content:center;
    font-weight:900;font-size:14px;font-variant-numeric:tabular-nums}
.b1{background:#fff;color:#222;border:1.5px solid #999}
.b2{background:#222;color:#fff}
.b3{background:#c8352b;color:#fff}
.b4{background:#1e58c8;color:#fff}
.b5{background:#f2c500;color:#333}
.b6{background:#1f9e50;color:#fff}
.pname{font-weight:700}
.grade{font-size:10px;font-weight:800;padding:1px 5px;border-radius:3px;margin-left:5px;vertical-align:1px}
.gA1{background:#fbe3c9;color:#9a5b12}
.gA2{background:#fdf1de;color:#a97c2f}
.gB1,.gB2{background:#eef1f4;color:#7a8590}
.rk{font-size:10px;font-weight:800;padding:1px 5px;border-radius:3px;margin-left:4px;background:#e4e8f2;color:#3a4a8a}
.rk.low{background:#fbe0db;color:#a1301f}
.sub{font-size:10.5px;color:#7c8794;font-variant-numeric:tabular-nums}
.badge{display:inline-block;font-size:10px;font-weight:800;padding:1.5px 6px;border-radius:4px;margin:1px 3px 1px 0}
.bg-st{background:#fdeccc;color:#8f6410}
.bg-wall{background:#e2ecf7;color:#245a9e}
.bg-good{background:#e3f1ea;color:#1f6b45}
.bg-out{background:#2b2f36;color:#ffd98a}
.bg-low{background:#eef1f4;color:#5b6672;border:1px solid #d5dce2}

.policy{padding:9px 12px;background:#fbf8f0;border-top:1px solid #ece4cf;font-size:12.5px;color:#5a4d2e}
.policy::before{content:"方針 ";font-weight:900;color:var(--kincha);letter-spacing:.08em}

.nokaisai{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:28px 16px;text-align:center;color:#5a6572}
.nokaisai b{display:block;font-size:16px;color:var(--kikyo);margin-bottom:6px}
.notes{margin:18px 4px 0;font-size:11px;color:#6b7683;line-height:1.75}
.notes div{margin-bottom:7px}
.notes b{color:var(--shu)}
footer{padding:14px;text-align:center;font-size:10px;color:#93a1ad}
"""

NOTES_HTML = """
<div><b>買うのは3連単50番人気まで</b>（目安：オッズ約170倍まで）。それより先の大穴は買わない。</div>
<div><b>若松はイン60%（全国6位）</b>で、場の補正後はほぼ中立（+1.3pt）。日程（初日・最終日）や季節では崩れません。
崩れを決めるのは<b>番組の組み方</b>と<b>選手の型</b>と<b>風・波</b>の3つです。</div>
<div><b>主戦場は「3R格差戦」</b>：3Rで1号艇がB級、外（2〜6号艇）に全国勝率が1.5以上高い艇がいるレース。
若松の3Rは「B級の1号艇の外にA級を置く」番組が多く、イン29%・15倍以上91%（前後半とも−16pt前後）。
3R以外は同じ格差でも効きません（−5pt・有意でない）。</div>
<div><b>5Rの進入固定戦隊は鉄板</b>（イン75%・万舟8%）。<b>準優・予選特選・ドリーム・優勝</b>もイン75%で見送り寄り。
8Rエイトビート（A級を内に置く企画）は万舟11%と堅めですが、場の補正後は中立なので点は付けていません。</div>
<div><b>風5m以上・波5cm以上はB級1号艇を飛ばす</b>（イン31%・前後半とも−14〜−20pt。A級1号艇は効かない）。
朝の時点では分からないので点数に入れていません。<b>直前情報で風5m以上か波5cm以上なら、B級1号艇のレースは崩れ度+1で読んでください</b>。
1Rが荒れていれば、その日の後のレースも55%は荒れたままです。</div>
<div><b>選手の型</b>：1号艇スロー遅れ●（ST>0.18・イン35%）と2号艇壁弱●（イン45%、食う型はイン24%）が若松でも再現。
スロー巧者・壁強・残す/飛ぶは表示のみ。崩れたとき1号艇が2着に残るのは負けた時の4分の1（大村45%より低い）＝X-1-Yに頼りすぎない。</div>
<div><b>風向・潮位・開催日目・モーターは採点に入れていません</b>（風向は風速の別名、上げ潮の強い時間のイン強化は後半で弱く監視、
初日/最終日は前後半で符号が割れる、モーターはWF不一致）。</div>
<div>スコアは若松の365日・2,245レース検証で三条件（方向・有意・前後半一致）を通ったシグナルだけを積んだものです。
機械買いは控除の壁の内側＝スコアは候補絞り用途、オッズの歪みは締切前に人間が判断してください。</div>
"""


TERRAIN_MIN_N = 40


def render_terrain(by_rno, kakusa):
    if not by_rno:
        return ''
    solid = [v['in1'] for v in by_rno.values() if v and v['n'] >= TERRAIN_MIN_N]
    mx = max(solid) if solid else 1
    bars = []
    for rno in range(1, 13):
        v = by_rno.get(rno)
        if not v or v['n'] < TERRAIN_MIN_N:
            bars.append('<div class="tbar"><div class="col" style="height:5px;background:#4b5170"></div>'
                        '<div class="num">%d</div><div class="pct">—</div></div>' % rno)
            continue
        h = max(4, round(v['in1'] / mx * 52))
        color = '#d96a55' if v['in1'] < 45 else ('#5b93bd' if v['in1'] >= 65 else '#4a5a9c')
        bars.append('<div class="tbar"><div class="col" style="height:%dpx;background:%s"></div>'
                    '<div class="num">%d</div><div class="pct">%d</div></div>'
                    % (h, color, rno, round(v['in1'])))
    cap = 'レース番号別イン率（通常戦・進入固定と特選系を除く・直近12か月）— 5Rは進入固定戦隊のため「—」'
    extra = ''
    if kakusa:
        extra = ('<div class="cap" style="margin-top:6px">3R格差戦：イン <b style="color:#ffd98a">%d%%</b>・万舟 %d%%・15倍以上 %d%%'
                 '（n=%d）＝ここが主戦場</div>' % (round(kakusa['in1']), round(kakusa['man']), round(kakusa['o15']), kakusa['n']))
    return ('<div class="terrain"><div class="cap">%s</div><div class="tbars">%s</div>%s</div>'
            % (cap, ''.join(bars), extra))


def badge_cls(m):
    if m.startswith('スロー遅れ'):
        return 'bg-st'
    if m.startswith('スロー巧者') or m.startswith('壁強') or m.startswith('残す型'):
        return 'bg-good'
    if m.startswith('壁'):
        return 'bg-wall'
    if m.startswith('飛ぶ型'):
        return 'bg-out'
    return 'bg-low'


def render_card(r, by_rno, kakusa):
    score, cls, flag, notes, kata = r['_sc']
    lab_cls, lab_txt = label_for(cls, score)
    card_cls = 'card'
    if lab_cls == 'katame':
        card_cls += ' tetsu'
    elif lab_cls == 'ana':
        card_cls += ' ana'

    base_html = '<span class="cls">%s</span>' % esc(cls)
    if r.get('fixed'):
        base_html += '<span class="cls flag">進入固定</span>'
    for f in [x for x in flag.split('・') if x]:
        base_html += '<span class="cls flag">%s</span>' % esc(f)
    base, base_src = None, ''
    if cls == '通常戦':
        if '3R格差戦' in flag and kakusa:
            base, base_src = kakusa, '3R格差戦'
        else:
            base, base_src = by_rno.get(r['rno']), 'この番号'
    if base and base['n'] >= TERRAIN_MIN_N:
        base_html += ('<span>基礎イン率 <b>%d%%</b></span><span class="man">万舟率 <b>%d%%</b></span>'
                      '<span>15倍+ <b>%d%%</b></span><span class="nn">%s n=%d</span>'
                      % (round(base['in1']), round(base['man']), round(base['o15']), esc(base_src), base['n']))
    if score > 0:
        score_html = '<span class="score">崩れ度 +%s</span>' % ('%g' % score)
    elif score < 0:
        score_html = '<span class="score minus">堅さ %s</span>' % ('%g' % score)
    else:
        score_html = ''

    rows = []
    for b in sorted(r['boats'], key=lambda x: x['teiban']):
        badges = ''.join('<span class="badge %s">%s</span>' % (badge_cls(m), esc(m)) for m in b.get('marks', []))
        subs = []
        if b.get('nat_win') is not None:
            subs.append('勝率 %.2f' % b['nat_win'])
        if b['teiban'] == 1 and b.get('jiriki') is not None:
            subs.append('全国逃げ率 %.1f%%' % b['jiriki'])
        if b.get('st_txt'):
            subs.append('平均ST ' + b['st_txt'])
        if b['teiban'] == 1 and b.get('motor_txt'):
            subs.append(b['motor_txt'])
        rk = ''
        if b['teiban'] == 1 and r.get('gap1') is not None:
            g = r['gap1']
            rk = '<span class="rk%s">格差 %+.2f</span>' % (' low' if (g <= GAP_3R and r['rno'] == 3) else '', g)
        rows.append(
            '<tr><td style="width:34px"><div class="bn b%d">%d</div></td>'
            '<td><span class="pname">%s</span><span class="grade g%s">%s</span>%s<br>'
            '<span class="sub">%s</span></td>'
            '<td style="text-align:right">%s</td></tr>'
            % (b['teiban'], b['teiban'], esc(b['name']), esc(b['grade']), esc(b['grade']), rk,
               esc(' ／ '.join(subs)), badges))

    return ('<div class="%s" id="race%d">'
            '<div class="card-head"><div class="rno">%d<small>R</small></div>'
            '<div class="rmeta"><div class="rname">%s</div><div class="deadline">%s</div></div>'
            '<span class="label %s">%s</span></div>'
            '<div class="base">%s%s</div>'
            '<table>%s</table>'
            '<div class="policy">%s</div></div>'
            % (card_cls, r['rno'], r['rno'], esc(r['rname']),
               ('締切 ' + esc(r['deadline'])) if r['deadline'] else '',
               lab_cls, esc(lab_txt), base_html, score_html, ''.join(rows),
               esc(policy_for(cls, flag, score, kata, notes))))


def render_page(parsed, by_rno, kakusa, failnote=''):
    date_s = TODAY.strftime('%Y-%m-%d')
    updated = TODAY.strftime('%Y-%m-%d %H:%M JST')

    meet_html, banner, body = '', '', ''
    if parsed:
        title = parsed.get('title') or ''
        day_n = parsed.get('day_n')
        meet_html = esc(title) + (' <b>第%d日</b>' % day_n if day_n else '')
        if parsed.get('is_final'):
            meet_html += ' <b>最終日</b>'
        norm_title = unicodedata.normalize('NFKC', title)
        if any(k in norm_title for k in SPECIAL_MEET):
            banner = ('<div class="banner">特殊節：番組編成が通常と異なるため、'
                      '3R格差戦の信頼度が下がります</div>')
        banner += ('<div class="banner day1">直前ルール：風5m以上か波5cm以上なら、B級1号艇のレースは崩れ度+1'
                   '（イン31%）。1Rが荒れたらその日は荒れが続きやすい</div>')
        body = ''.join(render_card(r, by_rno, kakusa) for r in parsed['races'])
    else:
        body = ('<div class="nokaisai"><b>本日、若松の開催はありません</b>'
                '上の地形図は直近12か月の基礎率です。次回開催日にまた自動更新されます。</div>')

    return """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>若松 穴党ツール</title>
<style>%s</style>
<script src="../venues.js" defer></script>
</head>
<body>
<div class="wrap">
<header>
  <div class="brand">
    <h1>若松 <span class="nami">夜</span> 穴党ツール</h1>
    <div class="datebox">%s%s</div>
  </div>
  <div class="meet">%s</div>
  <nav class="venues" data-venue="wakamatsu"></nav>
</header>
<div class="summary">イン<b>60%%</b>・万舟<b>14.7%%</b>（場の補正後ほぼ中立）／主戦場 <b>3R格差戦</b>（イン29%%）／5R<b>進入固定</b>は鉄板／<b>風5m・波5cm</b>以上はB級1号艇が飛ぶ（直前判断）</div>
%s
<div id="failnote">%s</div>
%s
<main>%s</main>
<div class="notes">%s</div>
<footer>更新: %s ／ 若松(20)・365日2,245レース検証</footer>
</div>
</body>
</html>
""" % (CSS, esc(date_s), '' if parsed else '（開催なし）', meet_html,
       render_terrain(by_rno, kakusa), failnote, banner, body, NOTES_HTML, esc(updated))


# ==================================================================
# 8. メイン
# ==================================================================
FAIL_RE = re.compile(r'(<div id="failnote">)(.*?)(</div>)', re.S)


def write_failnote(msg):
    """失敗時は前回のindex.htmlを残したまま、小さく更新失敗を出す（既存方針）。"""
    note = '<div class="failnote">%s</div>' % esc(msg)
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding='utf-8') as f:
            cur = f.read()
        if FAIL_RE.search(cur):
            new = FAIL_RE.sub(lambda m: m.group(1) + note + m.group(3), cur, count=1)
            with open(OUT_PATH, 'w', encoding='utf-8') as f:
                f.write(new)
            print('  前回ページを残して更新失敗を表示:', msg)
            return
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(render_page(None, {}, None, failnote=note))
    print('  ページが無かったため最小ページを生成:', msg)


def build(raw):
    """Bファイルのテキスト → (parsed, by_rno, kakusa)。テストからも呼ぶ。"""
    by_rno, kakusa = load_baselines()
    parsed = parse_wakamatsu(raw) if raw else None
    if parsed:
        for r in parsed['races']:
            r['_sc'] = score_race(r)
            for b in r['boats']:                 # モーターは参考表示のみ
                if b['teiban'] == 1 and b.get('motor_no'):
                    mt = T_MOTOR.get(str(int(b['motor_no'])))
                    if mt and fnum(mt.get('二連率')) is not None and mt.get('暫定') != 'n不足':
                        b['motor_txt'] = 'M%s 二連率 %.1f%%（参考）' % (b['motor_no'], fnum(mt['二連率']))
                    elif b.get('motor2') is not None:
                        b['motor_txt'] = 'M%s 二連率 %.1f%%（参考）' % (b['motor_no'], b['motor2'])
    return parsed, by_rno, kakusa


def main():
    print('若松(20) 日次ビルド', TODAY.strftime('%Y-%m-%d'))
    try:
        if os.environ.get('WM_BFILE'):                       # ローカル検証用：手元のBファイル(テキスト)
            with open(os.environ['WM_BFILE'], encoding='shift_jis', errors='replace') as f:
                raw = f.read()
        else:
            raw = fetch_bfile(TODAY)
        parsed, by_rno, kakusa = build(raw)
    except Exception as e:                       # 落とさない（既存方針）
        write_failnote('更新失敗（%s）：番組表を取得できませんでした。前回の内容を表示しています。'
                       % TODAY.strftime('%Y-%m-%d %H:%M'))
        print('  [error]', type(e).__name__, e)
        return
    print('  基礎率: レース番号別', len(by_rno), '／ 3R格差戦', (kakusa or {}).get('n'))
    if parsed:
        print('  開催あり:', parsed.get('title'), '第%s日' % parsed.get('day_n'),
              '最終日' if parsed.get('is_final') else '', '／', len(parsed['races']), 'レース')
    else:
        print('  本日非開催')
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(render_page(parsed, by_rno, kakusa))
    print('  ->', OUT_PATH)


if __name__ == '__main__':
    main()
