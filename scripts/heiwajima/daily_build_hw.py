# -*- coding: utf-8 -*-
"""平和島(04) 穴党ツール — 日次ビルド

毎朝1回、当日のBファイル（番組表）を取得し、平和島のレースに検証済みシグナルを
当てて heiwajima/index.html（静的ページ）を生成する。

正本ドキュメント（docs/heiwajima/）:
  spec_heiwajima.md … 採用/却下シグナルの正本
  spec_kikaku.md    … 企画レース判定（判定順序も仕様）
  memo_tables.md    … 6表の意味と使い方
  memo_motor.md     … モーターを採点に使わない根拠

★採点に使ってよいのは spec_heiwajima.md §2 の採用シグナルだけ。
  以下は採点禁止（このファイルで点数に触れさせないこと）:
    ・風向 / 風速 / 季節 / 潮位 / 開幕日  … 棄却またはヌル確定
    ・モーター                            … 暫定却下（参考表示のみ）
    ・レース番号 5R / 12R の鉄板扱い      … 廃止（企画はレース名で判定）

TODO(2026-10頃): モーター現行世代が中央値60走超 → 世代内ウォークフォワード再検定。
                 z>=2.0 なら「1号艇 低▲ = +1点」を有効化（docs/heiwajima/memo_motor.md §5）
TODO(2027-05〜06): モーター交換検出 → hw_motor_current.csv の世代起点を更新
TODO(月1回): レース名一覧を再集計し新企画名が出ていないか確認（spec_kikaku.md §6）
"""
import os
import re
import io
import csv
import html
import unicodedata
import urllib.request
from datetime import datetime, timezone, timedelta

from judge_kikaku import judge_heiwajima_race

JCD = '04'
JST = timezone(timedelta(hours=9))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
DATA_DIR = os.environ.get('HW_DATA_DIR', os.path.join(ROOT, 'data', 'heiwajima'))
OUT_PATH = os.environ.get('HW_OUT_PATH', os.path.join(ROOT, 'heiwajima', 'index.html'))

TODAY = datetime.now(JST)
if os.environ.get('DATE_OVERRIDE'):          # 例: DATE_OVERRIDE=2026-07-22（動作確認用）
    TODAY = datetime.strptime(os.environ['DATE_OVERRIDE'], '%Y-%m-%d').replace(tzinfo=JST)

# 特殊節（番組編成が通常と違う＝シグナルの信頼度が落ちる）の検出語
SPECIAL_MEET = ('G1', 'G2', 'SG', '女子', 'レディース', '新鋭', 'ヤング')


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
# 2. 出走表パース（平和島ブロック）
# ==================================================================
# 選手行の固定幅レイアウト（spec §5-2）:
#   ln[0]=艇番 / ln[2:6]=登番 / ln[6:10]=氏名 / ln[16:18]=級
BOAT_RE = re.compile(r'^([1-6]) (\d{4})(.{4})(\d{2})(..)(\d{2})([AB][12])(.*)$')
# 4つの率（全国勝率・全国2率・当地勝率・当地2率）の後ろがモーターNo・モーター2率
MOTOR_RE = re.compile(r'\d+\.\d\d\s+\d+\.\d\d\s+\d+\.\d\d\s+\d+\.\d\d\s+(\d+)\s+(\d+\.\d\d)')
HEAD_RE = re.compile(r'^\s*(\d{1,2})R\s+(\S+)')
DEADLINE_RE = re.compile(r'締切予定\s*(\d{1,2}:\d{2})')


def parse_heiwajima(raw):
    """平和島ブロックを解析。非開催（ブロックなし）なら None。"""
    m = re.search(r'%sBBGN(.*?)%sBEND' % (JCD, JCD), raw, re.S)
    if not m:
        return None
    lines = m.group(1).split('\n')

    # 節タイトルと開催日目（ヘッダ数行に入っている）
    title, day_n = '', None
    for ln in lines[:12]:
        n = unicodedata.normalize('NFKC', ln)
        md = re.search(r'第\s*(\d+)\s*日', n)
        if md and day_n is None:
            day_n = int(md.group(1))
        s = n.strip()
        if s and not title and not re.match(r'^\d', s) \
                and 'BBGN' not in s and '番組表' not in s and 'ボートレース' not in s:
            title = s

    races, cur = [], None
    for ln in lines:
        n = unicodedata.normalize('NFKC', ln)
        mh = HEAD_RE.match(n)
        if mh:
            if cur:
                races.append(cur)
            md = DEADLINE_RE.search(n)
            cur = dict(rno=int(mh.group(1)), rname=mh.group(2),
                       deadline=md.group(1) if md else '', boats=[])
            continue
        mb = BOAT_RE.match(ln)
        if mb and cur is not None:
            motor_no, motor2 = None, None
            mm = MOTOR_RE.search(unicodedata.normalize('NFKC', mb.group(8)))
            if mm:
                motor_no, motor2 = mm.group(1), float(mm.group(2))
            cur['boats'].append(dict(
                teiban=int(ln[0]),
                regno=ln[2:6].strip(),
                name=ln[6:10].replace('　', '').strip(),
                grade=ln[16:18],
                motor_no=motor_no,
                motor2=motor2))
    if cur:
        races.append(cur)
    races = [r for r in races if len(r['boats']) >= 4]
    if not races:
        return None
    return dict(title=title, day_n=day_n, races=races)


# ==================================================================
# 3. 選手表（6表）の読込
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


T_ST = load_csv('hw_st.csv', 'regno')            # ST表（当地優先/全国フォールバック）
T_WALL = load_csv('hw_wall.csv', 'regno')        # 壁表
T_SASHI = load_csv('hw_c2sashi.csv', 'regno')    # 2コース差し表（差し水面固有の第6表）
T_ZAN = load_csv('hw_zanshi.csv', 'regno')       # 残し表
T_SHIBORI = load_csv('hw_shibori.csv', 'regno')  # 絞りまくり表
T_MOTOR = load_csv('hw_motor_current.csv', 'motor')   # 現行世代モーター（参考表示のみ）
T_NAT1C = load_csv('nat_1c.csv', 'touban')       # 全国1コース地力（参考表示のみ）

P0 = 0.549   # 全国1C平均逃げ率（本窓・spec §5）


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
def load_baselines():
    """hw_race_resid.csv から
         ・レース番号別の基礎イン率/万舟率（通常戦のみ）
         ・企画分類別の基礎イン率/万舟率
       を作る。

    レース番号別を「通常戦のみ」で出すのは意図的。全レース混みで出すと
    東京ベイランチ（イン78〜80%）が居るレース番号だけ跳ね上がり、
    spec が廃止した「番号＝鉄板」の誤読を招くため（spec_kikaku.md §0）。
    """
    path = os.path.join(DATA_DIR, 'hw_race_resid.csv')
    by_rno, by_cls = {}, {}
    if not os.path.exists(path):
        print('  [warn] アーカイブが見つかりません:', path)
        return by_rno, by_cls
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
            cls = judge_heiwajima_race(row.get('rname', ''), rno)[0]
            by_cls.setdefault(cls, []).append((inwin, man))
            if cls == '通常戦':
                by_rno.setdefault(rno, []).append((inwin, man))

    def summarize(d):
        out = {}
        for k, rows in d.items():
            n = len(rows)
            out[k] = dict(n=n,
                          in1=round(sum(a for a, _ in rows) / n * 100, 1),
                          man=round(sum(b for _, b in rows) / n * 100, 1))
        return out

    return summarize(by_rno), summarize(by_cls)


# ==================================================================
# 5. 採点（spec_heiwajima.md §2 / HANDOVER §4-3 のみ）
# ==================================================================
def score_race(r):
    """レースを採点して (合計点, 分類, フラグ, フォーム, 印dict, 注記list, 2号艇タイプ) を返す。"""
    cls, pts, flag, form = judge_heiwajima_race(r['rname'], r['rno'])
    score = float(pts)
    marks = {b['teiban']: [] for b in r['boats']}
    notes = []
    c2type = None          # 2号艇の壁/差しタイプ（買い目方針の分岐キー）
    boats = {b['teiban']: b for b in r['boats']}

    # --- 1号艇：スロー遅れ（採用スローST > 0.18） +1.0 ---
    b1 = boats.get(1)
    if b1:
        st = T_ST.get(b1['regno'])
        if st:
            v = fnum(st.get('採用スローST'))
            if v is not None:
                b1['st_txt'] = '%.2f（%s）' % (v, st.get('スロー源', ''))
                if v > 0.18:
                    marks[1].append('スロー遅れ●')
                    score += 1.0
                    notes.append('1号艇の採用スローST %.2f（>0.18）＝出足で遅れやすい。' % v)
        # 残し表：飛ぶ型 +0.5
        zan = T_ZAN.get(b1['regno'])
        if zan:
            if zan.get('型') == '飛ぶ型':
                marks[1].append('飛ぶ型')
                score += 0.5
                notes.append('1号艇は飛ぶ型（負けると2着にも残らない）＝頭を譲ると総崩れ。')
            elif zan.get('型') == '残す型':
                marks[1].append('残す型')
                notes.append('1号艇は残す型＝差されても2着に残りやすい（X-1-Y の裏付け）。')
        b1['jiriki'] = jiriki(b1['regno'])

    # --- 2号艇：壁弱● +1.0 ／ 差し巧者● +1.0 ---
    b2 = boats.get(2)
    if b2:
        wall = T_WALL.get(b2['regno'])
        if wall:
            if wall.get('壁') == '壁弱●':
                wt = wall.get('弱タイプ', '')
                marks[2].append('壁弱●' + ('(%s)' % wt if wt else ''))
                score += 1.0
                c2type = wt or '壁弱'
                if wt == '素通し型':
                    notes.append('2号艇が素通し型＝2号艇自身は残らず、外の攻めがそのまま通る。')
                elif wt == '食う型':
                    notes.append('2号艇が食う型＝2号艇自身が1号艇を食う（2アタマ本線）。')
            elif wall.get('壁') == '壁強●':
                marks[2].append('壁強●')
                c2type = '壁強'
                notes.append('2号艇が壁強＝外を止める。イン信頼寄りで穴妙味は薄い。')
        sashi = T_SASHI.get(b2['regno'])
        if sashi and sashi.get('差し巧者') == '●':
            marks[2].append('差し巧者●')
            score += 1.0
            c2type = '差し巧者'
            notes.append('2号艇が差し巧者＝2アタマ本線（差し水面の本命崩し役）。')
        elif sashi and sashi.get('差し不発') == '●':
            marks[2].append('差し不発')

    # --- 3・4号艇：絞りまくり●（暫定） +0.5（どちらかに居れば1回だけ） ---
    if any(T_SHIBORI.get(boats[t]['regno'], {}).get('絞りまくり') == '●'
           for t in (3, 4) if t in boats):
        for t in (3, 4):
            if t in boats and T_SHIBORI.get(boats[t]['regno'], {}).get('絞りまくり') == '●':
                marks[t].append('絞りまくり●(暫)')
        score += 0.5
        notes.append('3/4号艇に絞りまくり●（暫定シグナル）。')

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
        if tb == 6:
            zan = T_ZAN.get(b['regno'])
            if zan and zan.get('6ヒモ外し候補') == '●':
                marks[6].append('6外し●')
        b['marks'] = marks[b['teiban']]

    return score, cls, flag, form, notes, c2type


# ==================================================================
# 6. 買い目方針（HANDOVER §4-4 / spec_kikaku.md §3）
# ==================================================================
def policy_for(cls, flag, form, c2type, notes):
    """企画分類が最優先。通常戦系だけ2号艇のタイプで差し水面フォームを分岐する。"""
    if cls == '東京ベイランチ':
        head = ('【鉄板・穴買い禁止】1号艇A級／他B級の編成でイン78〜80%。'
                'このツールの主旨（穴）から外れるため見送り推奨。')
    elif cls == 'ベイブレイク':
        head = ('【カド攻め】1&4号艇A級の編成。崩れ筋は4カドまくり＝'
                '本線 4-1／4-流し。差し水面フォーム（2C/3Cアタマ）は当てはめない。')
        if c2type in ('素通し型', '壁弱'):
            head += ' 2枠が壁弱＝4まくりが刺さりやすい。'
    elif cls == '優勝戦':
        head = '【鉄板寄り】イン76.7%。1アタマ基本・穴は見送り寄り。'
    else:
        # 差し水面フォーム（通常戦・準優勝戦・記者選抜・選抜系）
        if c2type in ('食う型', '差し巧者'):
            head = ('本線 2-1-全（4点）＋押さえ 2-3-1・2-4-1。'
                    '2号艇が1号艇を差し切る型で、1号艇は2着に残る。')
        elif c2type == '素通し型':
            head = ('2アタマは買わず 3-1-全／4-1-全。'
                    '万舟狙いは X-X-1（1号艇の3着沈み）。')
        elif c2type == '壁強':
            head = '見送り推奨（2号艇が壁強のレースはイン65.5%・万舟10.9%）。'
        else:
            head = '標準：2-1-全 ＋ 3-1-全（10点）。'
    return (head + ' ' + ' '.join(notes)).strip()


def label_for(cls, flag, score):
    """カード右肩のラベル（クラス名, 表示文字）。"""
    if flag == '鉄板・穴買い禁止':
        return 'katame', '鉄板・見送り'
    if flag == '鉄板寄り':
        return 'katame', '鉄板寄り'
    if flag == 'カド攻め':
        return 'nitaku', 'カド攻め'
    if score >= 3.5:
        return 'ana', '穴の巣'
    if score >= 2.0:
        return 'ana', '崩れゾーン'
    if score >= 1.0:
        return 'nitaku', '要注意'
    return 'chukan', '中立'


# ==================================================================
# 7. HTML生成
# ==================================================================
def esc(s):
    return html.escape(str(s if s is not None else ''))


CSS = """
:root{
  --kon:#232a4d;        /* 紺桔梗: ヘッダー */
  --kikyo:#3b4a8c;      /* 桔梗: 見出し文字 */
  --gin:#eceef4;        /* 銀鼠がかった藤: 背景 */
  --asagi:#3d7ea6;      /* 浅葱: 堅め */
  --shu:#c04a37;        /* 朱: 穴・警告 */
  --kincha:#b8862e;     /* 金茶: 二択・注意 */
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
header h1 .nami{color:#8f9fd8}
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

/* イン率地形図（レース番号別・通常戦のみ） */
.terrain{background:var(--kon);padding:2px 16px 14px}
.terrain .cap{font-size:10px;color:#98a2c8;letter-spacing:.1em;margin-bottom:4px}
.tbars{display:flex;align-items:flex-end;gap:3px;height:64px}
.tbar{flex:1;display:flex;flex-direction:column;justify-content:flex-end}
.tbar .col{border-radius:2px 2px 0 0;min-height:4px}
.tbar .num{font-size:9px;text-align:center;color:#a3adcf;margin-top:3px;font-variant-numeric:tabular-nums}
.tbar .pct{font-size:8px;text-align:center;color:#7b85ab;font-variant-numeric:tabular-nums}

.banner{background:linear-gradient(90deg,#8c2f39,#c04a37);color:#fff;font-size:12.5px;font-weight:800;
  padding:8px 16px;text-align:center;letter-spacing:.04em}
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
.sub{font-size:10.5px;color:#7c8794;font-variant-numeric:tabular-nums}
.badge{display:inline-block;font-size:10px;font-weight:800;padding:1.5px 6px;border-radius:4px;margin:1px 3px 1px 0}
.bg-st{background:#fdeccc;color:#8f6410}
.bg-wall{background:#e2ecf7;color:#245a9e}
.bg-sashi{background:#fbe0db;color:#a1301f}
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
<div><b>買い目カバー率は「条件付き」の実測です</b>：差し系決着546Rに限った集計で、
2-1-全＝的中19.8%・回収233%、＋2-3-1・2-4-1＝24.4%・208%、＋3-1-全＝34.2%・172%。
<b>そもそも差し系決着になるのは崩れゾーンでも3割前後</b>なので、この数字は
「差しになった時にどれだけ拾えるか」であって、全レースに当てはめた期待値ではありません。</div>
<div><b>平和島は本物の差し水面</b>（場残差 −7.8pt）。崩れ筋は6コースの一発まくりではなく
<b>2C・3Cの差し／まくり差しで1号艇が飲まれる</b>形。買い目は外流しでなく2・3コース差しを軸に。
1号艇は負けても33%は2着に残るので X-1-Y のヒモ確保が基本です。</div>
<div><b>企画レースはレース番号でなくレース名で判定</b>しています。東京ベイランチは夏（薄暮開催）は2R・
他季は5Rへ移動するため、番号で見ると季節で反転します。5R/12Rの鉄板扱いは廃止済みです。</div>
<div><b>直前情報（このページに入っていないもの）</b>：風は採点に入れていません（平和島は風速・風向とも
レース単位の主効果にならないことが検証済み）。ただし機構レベルでは
<b>北風3m+で1号艇のST優位が痩せる</b>（まくり差し警戒＝3-1／4-1／5-1系）ので、直前に北風3m以上なら頭に入れてください。</div>
<div><b>モーターは採点に使っていません</b>（参考表示のみ）。現行世代は2026-06-18起点でまだ走行数が足りず、
旧世代の検定でも有意水準に届きませんでした。2026年10月頃に再検定予定です。</div>
<div>スコアは平和島の365日・1,923レース検証で三条件（方向・有意・前後半一致）を通ったシグナルだけを積んだものです。
機械買いは控除の壁の内側＝スコアは候補絞り用途、オッズの歪みは締切前に人間が判断してください。</div>
"""


TERRAIN_MIN_N = 50   # 通常戦のnがこれ未満のレース番号は数値を出さない（12R等は大半が企画で残らない）


def render_terrain(by_rno):
    if not by_rno:
        return ''
    solid = [v['in1'] for v in by_rno.values() if v['n'] >= TERRAIN_MIN_N]
    mx = max(solid) if solid else 1
    bars = []
    for rno in range(1, 13):
        v = by_rno.get(rno)
        if not v:
            continue
        if v['n'] < TERRAIN_MIN_N:
            # n不足のセルは高さを持たせない。棒にすると跳ね上がって誤読を招くため。
            bars.append('<div class="tbar"><div class="col" style="height:5px;background:#4b5170"></div>'
                        '<div class="num">%d</div><div class="pct">—</div></div>' % rno)
            continue
        h = max(4, round(v['in1'] / mx * 52))
        color = '#d96a55' if v['in1'] < 40 else ('#5b93bd' if v['in1'] >= 58 else '#4a5a9c')
        bars.append('<div class="tbar"><div class="col" style="height:%dpx;background:%s"></div>'
                    '<div class="num">%d</div><div class="pct">%d</div></div>'
                    % (h, color, rno, round(v['in1'])))
    return ('<div class="terrain"><div class="cap">レース番号別イン率（通常戦のみ・直近12か月）'
            '— 谷が穴場／「—」は通常戦が少なく参考外</div>'
            '<div class="tbars">%s</div></div>' % ''.join(bars))


def render_card(r, by_rno, by_cls):
    score, cls, flag, form, notes, c2type = r['_sc']
    lab_cls, lab_txt = label_for(cls, flag, score)
    card_cls = 'card'
    if lab_cls == 'katame':
        card_cls += ' tetsu'
    elif lab_cls == 'ana' and score >= 2.0:
        card_cls += ' ana'

    # 基礎率：通常戦はレース番号別、企画は分類別を出す（番号別は企画を除いてあるため）
    base = by_rno.get(r['rno']) if cls == '通常戦' else by_cls.get(cls)
    base_src = 'この番号の通常戦' if cls == '通常戦' else cls
    # 分類チップ＋フラグチップ（主戦場／カド攻め／鉄板・穴買い禁止 など）
    base_html = '<span class="cls">%s</span>' % esc(cls)
    if flag:
        base_html += '<span class="cls flag">%s</span>' % esc(flag)
    if base and base['n'] >= TERRAIN_MIN_N:
        base_html += ('<span>基礎イン率 <b>%d%%</b></span><span class="man">万舟率 <b>%d%%</b></span>'
                      '<span class="nn">%s n=%d</span>'
                      % (round(base['in1']), round(base['man']), esc(base_src), base['n']))

    score_html = ('<span class="score">崩れ度 +%s</span>' % ('%g' % score)) if score > 0 else ''

    rows = []
    for b in sorted(r['boats'], key=lambda x: x['teiban']):
        badges = ''.join('<span class="badge %s">%s</span>' % (badge_cls(m), esc(m))
                         for m in b.get('marks', []))
        subs = []
        if b.get('jiriki') is not None:
            subs.append('全国逃げ率 %.1f%%' % b['jiriki'])
        if b.get('st_txt'):
            subs.append('平均ST ' + b['st_txt'])
        if b['teiban'] == 1 and b.get('motor_txt'):
            subs.append(b['motor_txt'])
        rows.append(
            '<tr><td style="width:34px"><div class="bn b%d">%d</div></td>'
            '<td><span class="pname">%s</span><span class="grade g%s">%s</span><br>'
            '<span class="sub">%s</span></td>'
            '<td style="text-align:right">%s</td></tr>'
            % (b['teiban'], b['teiban'], esc(b['name']), esc(b['grade']), esc(b['grade']),
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
               esc(policy_for(cls, flag, form, c2type, notes))))


def badge_cls(m):
    if m.startswith('スロー遅れ'):
        return 'bg-st'
    if m.startswith('壁'):
        return 'bg-wall'
    if m.startswith('差し'):
        return 'bg-sashi'
    if m.startswith('飛ぶ型') or '外し' in m:
        return 'bg-out'
    if m.startswith('絞りまくり'):
        return 'bg-wall'
    return 'bg-low'


def render_page(parsed, by_rno, by_cls, failnote=''):
    date_s = TODAY.strftime('%Y-%m-%d')
    updated = TODAY.strftime('%Y-%m-%d %H:%M JST')

    meet_html, banner, body = '', '', ''
    if parsed:
        title = parsed.get('title') or ''
        meet_html = esc(title) + (' <b>第%d日</b>' % parsed['day_n'] if parsed.get('day_n') else '')
        norm_title = unicodedata.normalize('NFKC', title)
        if any(k in norm_title for k in SPECIAL_MEET):
            banner = ('<div class="banner">特殊節：番組編成が通常と異なるため、'
                      'レース番号・企画シグナルの信頼度が下がります</div>')
        cards = [render_card(r, by_rno, by_cls) for r in parsed['races']]
        body = ''.join(cards)
    else:
        body = ('<div class="nokaisai"><b>本日、平和島の開催はありません</b>'
                '上の地形図は直近12か月の基礎率です。次回開催日にまた自動更新されます。</div>')

    return """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>平和島 穴党ツール</title>
<style>%s</style>
<script src="../venues.js" defer></script>
</head>
<body>
<div class="wrap">
<header>
  <div class="brand">
    <h1>平和島 <span class="nami">差</span> 穴党ツール</h1>
    <div class="datebox">%s%s</div>
  </div>
  <div class="meet">%s</div>
  <nav class="venues" data-venue="heiwajima"></nav>
</header>
<div class="summary">差し水面（場残差 <b>&minus;7.8pt</b>）／イン<b>46%%</b>・万舟<b>17.3%%</b>／主戦場 <b>7R</b>・準主戦場 <b>3R</b>／企画は<b>レース名</b>で判定</div>
%s
<div id="failnote">%s</div>
%s
<main>%s</main>
<div class="notes">%s</div>
<footer>更新: %s ／ 平和島(04)・365日1,923レース検証</footer>
</div>
</body>
</html>
""" % (CSS, esc(date_s), '' if parsed else '（開催なし）', meet_html,
       render_terrain(by_rno), failnote, banner, body, NOTES_HTML, esc(updated))


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
        f.write(render_page(None, {}, {}, failnote=note))
    print('  ページが無かったため最小ページを生成:', msg)


def main():
    print('平和島(04) 日次ビルド', TODAY.strftime('%Y-%m-%d'))
    by_rno, by_cls = load_baselines()
    print('  基礎率: レース番号別', len(by_rno), '／ 分類別', len(by_cls))
    try:
        raw = fetch_bfile(TODAY)
        parsed = parse_heiwajima(raw) if raw else None
    except Exception as e:                       # 落とさない（既存方針）
        write_failnote('更新失敗（%s）：番組表を取得できませんでした。前回の内容を表示しています。'
                       % TODAY.strftime('%Y-%m-%d %H:%M'))
        print('  [error]', type(e).__name__, e)
        return
    if parsed:
        for r in parsed['races']:
            r['_sc'] = score_race(r)
            for b in r['boats']:                 # モーターは参考表示のみ
                if b['teiban'] == 1 and b.get('motor_no'):
                    mt = T_MOTOR.get(str(b['motor_no']))
                    if mt and fnum(mt.get('二連率')) is not None:
                        b['motor_txt'] = 'M%s 二連率 %.1f%%（参考・n不足）' % (b['motor_no'], fnum(mt['二連率']))
                    elif b.get('motor2') is not None:
                        b['motor_txt'] = 'M%s 二連率 %.1f%%（参考）' % (b['motor_no'], b['motor2'])
        print('  開催あり:', parsed.get('title'), '第%s日' % parsed.get('day_n'),
              '／', len(parsed['races']), 'レース')
    else:
        print('  本日非開催')
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(render_page(parsed, by_rno, by_cls))
    print('  ->', OUT_PATH)


if __name__ == '__main__':
    main()
