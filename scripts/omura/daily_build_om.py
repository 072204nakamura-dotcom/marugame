# -*- coding: utf-8 -*-
"""大村(24) 穴党ツール — 日次ビルド

毎朝1回、当日のBファイル（番組表）を取得し、大村のレースに検証済みシグナルを
当てて omura/index.html（静的ページ）を生成する。

正本ドキュメント（docs/omura/）:
  spec_omura.md   … 採用/却下シグナルの正本（§4 スコア・§5 買い目フォーム）
  memo_tables.md  … 5表の意味と使い方
  memo_motor.md   … モーターを採点に使わない根拠

★採点に使ってよいのは spec_omura.md §4 の表に列挙したものだけ。
  以下は採点禁止（このファイルで点数に触れさせないこと）:
    ・風向 / 風速 / 季節 / 潮位            … 棄却またはヌル確定
    ・モーター                              … 却下（参考表示のみ）
    ・レース番号単独（1〜6R＝穴 等）        … 却下（崩れは「初日の前半」だけ）
    ・「特選」の部分一致（一般特選は中立）  … 「予選特選」「特別選抜」だけを拾う

TODO(2026-12頃): モーター現行世代が中央値120走超 → 世代内WF再検定（memo_motor.md §4）
TODO(2027-05):   モーター交換検出 → om_motor_current.csv の世代起点を更新
TODO(月1回):     レース名一覧を再集計し新しい企画名が出ていないか確認
"""
import os
import re
import io
import csv
import html
import unicodedata
import urllib.request
from datetime import datetime, timezone, timedelta

from judge_omura import judge_omura_race

JCD = '24'
JST = timezone(timedelta(hours=9))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
DATA_DIR = os.environ.get('OM_DATA_DIR', os.path.join(ROOT, 'data', 'omura'))
OUT_PATH = os.environ.get('OM_OUT_PATH', os.path.join(ROOT, 'omura', 'index.html'))

TODAY = datetime.now(JST)
if os.environ.get('DATE_OVERRIDE'):          # 例: DATE_OVERRIDE=2026-09-18（動作確認用）
    TODAY = datetime.strptime(os.environ['DATE_OVERRIDE'], '%Y-%m-%d').replace(tzinfo=JST)

# 特殊節（番組編成が通常と違う＝シグナルの信頼度が落ちる）の検出語
SPECIAL_MEET = ('G1', 'G2', 'SG', 'レディース', '女子', '新鋭', 'ヤング', 'ルーキー', 'マスターズ', 'オール進入固定')


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
# 2. 出走表パース（大村ブロック）
# ==================================================================
# 選手行の固定幅レイアウト:  ln[0]=艇番 / ln[2:6]=登番 / ln[6:10]=氏名 / ln[16:18]=級
BOAT_RE = re.compile(r'^([1-6]) (\d{4})(.{4})(\d{2})(..)(\d{2})([AB][12])(.*)$')
# 全国勝率・全国2率・当地勝率・当地2率・モーターNo・モーター2率・ボートNo・ボート2率
RATE_RE = re.compile(r'(\d+\.\d\d)\s+(\d+\.\d\d)\s+(\d+\.\d\d)\s+(\d+\.\d\d)\s+(\d+)\s+(\d+\.\d\d)\s+(\d+)\s+(\d+\.\d\d)')
HEAD_RE = re.compile(r'^\s*(\d{1,2})R\s+(\S+)(.*)$')
DEADLINE_RE = re.compile(r'締切予定\s*(\d{1,2}:\d{2})')


def parse_omura(raw):
    """大村ブロックを解析。非開催（ブロックなし）なら None。"""
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
    # 節タイトルは6行目（Kファイル/Bファイル共通のレイアウト）。「ミッドナイトボートレースin大村」のように
    # 「ボートレース」を含む節名があるため、平和島版の除外ルールでは拾えない。
    if len(lines) > 5 and lines[5].strip():
        title = unicodedata.normalize('NFKC', lines[5]).strip()
    if not title:
        for ln in lines[:12]:
            s = unicodedata.normalize('NFKC', ln).strip()
            if s and not re.match(r'^\d', s) and 'BBGN' not in s and '番組表' not in s \
                    and not s.startswith('ボートレース大') and '照合' not in s:
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
                       fixed=('進入固定' in n),                 # ★大村固有：見出し行の「進入固定」
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

    # 最終日判定：本日のBファイルに「優勝戦」（準優を除く）がある（spec §6）
    is_final = any(('優勝' in unicodedata.normalize('NFKC', r['rname'])
                    and '準優' not in unicodedata.normalize('NFKC', r['rname'])) for r in races)
    # 1号艇の出走表内 全国勝率順位（同率は上位扱い）
    for r in races:
        wins = [b['nat_win'] for b in r['boats'] if b['nat_win'] is not None]
        b1 = next((b for b in r['boats'] if b['teiban'] == 1), None)
        if b1 and b1['nat_win'] is not None and wins:
            r['rank1'] = 1 + sum(1 for w in wins if w > b1['nat_win'])
        else:
            r['rank1'] = None
    return dict(title=title, day_n=day_n, is_final=is_final, races=races)


# ==================================================================
# 3. 選手表（5表）の読込
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


T_ST = load_csv('om_st.csv', 'regno')              # ST表（当地優先/全国フォールバック）
T_WALL = load_csv('om_wall.csv', 'regno')          # 壁表
T_ZAN = load_csv('om_zanshi.csv', 'regno')         # 残し表
T_SHIBORI = load_csv('om_shibori.csv', 'regno')    # 絞りまくり表（当地・薄い）
T_MOTOR = load_csv('om_motor_current.csv', 'motor')   # 現行世代モーター（参考表示のみ）
T_NAT1C = load_csv('nat_1c.csv', 'touban')         # 全国1コース地力（参考表示のみ）

P0 = 0.5537   # 全国1C平均逃げ率（本窓・spec §6）


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
    """om_race_resid.csv から
         ・レース番号別の基礎イン率/万舟率（通常戦・進入固定を除く・中日）
         ・初日×1〜6R のイン率/万舟率
       を作る。中日だけで出すのは意図的：初日1〜6Rの崩れ（イン36%）を混ぜると
       「毎日の前半が穴」という誤読を招く（spec §3 一行目）。"""
    path = os.path.join(DATA_DIR, 'om_race_resid.csv')
    by_rno, first = {}, []
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
            if row.get('fixed') == '1' or '準優' in nm or '予選特選' in nm or '特別選抜' in nm or '優勝' in nm:
                continue
            day = fnum(row.get('day_n'))
            if day == 1 and rno <= 6:
                first.append((inwin, man, o15))
            elif day is not None and day >= 2:
                by_rno.setdefault(rno, []).append((inwin, man, o15))

    def summarize(rows):
        n = len(rows)
        return dict(n=n, in1=round(sum(a for a, _, _ in rows) / n * 100, 1),
                    man=round(sum(b for _, b, _ in rows) / n * 100, 1),
                    o15=round(sum(c for _, _, c in rows) / n * 100, 1)) if n else None

    return {k: summarize(v) for k, v in by_rno.items()}, summarize(first)


# ==================================================================
# 5. 採点（spec_omura.md §4 のみ）
# ==================================================================
def score_race(r, day_n, is_final):
    """レースを採点して (合計点, 分類, フラグ, フォーム, 注記list, 型情報dict) を返す。"""
    boats = {b['teiban']: b for b in r['boats']}
    b1 = boats.get(1)
    g1 = b1['grade'] if b1 else ''
    cls, pts, flag, form = judge_omura_race(r['rname'], r['rno'], r.get('fixed', False),
                                            day_n, is_final, r.get('rank1'), g1)
    score = float(pts)
    marks = {b['teiban']: [] for b in r['boats']}
    notes = []
    kata = dict(zan1='', c2type='')        # 買い目分岐キー

    if '初日前半' in flag:
        notes.append('初日の1〜6R＝大村の主戦場（イン36%・万舟21%・15倍以上77%）。慣らし前の1号艇は平均ST0.166と遅い。')
    if '1号艇勝率4位以下' in flag:
        notes.append('1号艇の全国勝率が出走表内で4位以下（大村はイン44%まで落ちる相対地力の場）。')
    if '1号艇勝率1位A級' in flag:
        notes.append('1号艇が出走表内で勝率1位のA級（イン77%）＝鉄板寄り。')
    if '最終日A級' in flag:
        notes.append('最終日の前半でA級が1号艇＝今節成績順の番組（イン76%）。穴は見送り寄り。')
    if '2日目前半' in flag:
        notes.append('2日目の前半×B級1号艇（−7pt・暫定）。')

    # --- 1号艇：スロー遅れ● +1 ／ 巧者● −1 ／ 残す型・飛ぶ型（表示・フォーム分岐） ---
    if b1:
        st = T_ST.get(b1['regno'])
        if st:
            v = fnum(st.get('採用スローST'))
            if v is not None:
                b1['st_txt'] = '%.2f（%s）' % (v, st.get('スロー源', ''))
                if v > 0.18:
                    marks[1].append('スロー遅れ●'); score += 1.0
                    notes.append('1号艇の採用スローST %.2f（>0.18）＝大村内でもイン31%%まで落ちる型。' % v)
                elif v <= 0.13:
                    marks[1].append('スロー巧者●'); score -= 1.0
                    notes.append('1号艇はスロー巧者（ST≤0.13・イン76%）＝鉄板寄り。')
        zan = T_ZAN.get(b1['regno'])
        if zan:
            if zan.get('型') == '飛ぶ型':
                marks[1].append('飛ぶ型'); kata['zan1'] = '飛ぶ型'
                notes.append('1号艇は飛ぶ型（負けると2着にも残らない・大村内38%）＝X-1-Yを外す。')
            elif zan.get('型') == '残す型':
                marks[1].append('残す型'); kata['zan1'] = '残す型'
                notes.append('1号艇は残す型（負けても2着に70%）＝X-1-Yを厚く。')
        b1['jiriki'] = jiriki(b1['regno'])

    # --- 2号艇：壁弱● +1 ／ 壁強● −1 ---
    b2 = boats.get(2)
    if b2:
        wall = T_WALL.get(b2['regno'])
        if wall:
            if wall.get('壁') == '壁弱●':
                wt = wall.get('弱タイプ', '')
                marks[2].append('壁弱●' + ('(%s)' % wt if wt else '')); score += 1.0
                kata['c2type'] = wt or '壁弱'
                if wt == '素通し型':
                    notes.append('2号艇が素通し型＝外の攻めがそのまま通る（4アタマ筋）。2号艇は消し。')
                elif wt == '食う型':
                    notes.append('2号艇が食う型＝2号艇自身が1号艇を食う（2アタマ本線）。')
            elif wall.get('壁') == '壁強●':
                marks[2].append('壁強●'); score -= 1.0; kata['c2type'] = '壁強'
                notes.append('2号艇が壁強＝外を止める（イン77%）。穴妙味は薄い。')

    # --- 3・4号艇：絞りまくり●（暫定） +0.5（どちらかに居れば1回だけ） ---
    hit = False
    for t in (3, 4):
        if t in boats and T_SHIBORI.get(boats[t]['regno'], {}).get('絞りまくり') == '●':
            marks[t].append('絞りまくり●(暫)'); hit = True
    if hit:
        score += 0.5
        notes.append('3/4号艇に当地の絞りまくり●（暫定・当地表は薄い）。')

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

    return score, cls, flag, form, notes, kata


# ==================================================================
# 6. 買い目方針（spec_omura.md §5）
# ==================================================================
def policy_for(cls, flag, score, kata, notes):
    if cls == '進入固定':
        head = ('【鉄板・穴買い禁止】進入固定＝イン75%・万舟8%・配当中央値1,080円。'
                'このツールの主旨（穴）から外れるため見送り推奨。')
    elif cls in ('準優勝戦', '特選系'):
        head = ('【鉄板寄り】イン78〜81%。乗るなら中穴フォーム＝1頭固定・2着を4〜6号艇に寄せる'
                '（1-4-全・1-5-全・1-6-2/3）。51番人気以降は買わない。')
    elif cls == '優勝戦':
        head = '【中立】6人全員強豪で相対地力が消える（イン62%）。'
    elif score >= 2.0:
        if kata.get('c2type') == '素通し型':
            head = ('本線 3-1-全・4-1-全（8点）。2号艇は消し（素通し型）。'
                    '万舟狙いは 3-4-1/4-3-1。')
        elif kata.get('c2type') in ('食う型', '壁弱'):
            head = ('本線 2-1-全（4点）＋押さえ 2-3-1・2-4-1。'
                    '2号艇が1号艇を食う型。1号艇は2着に残る。')
        elif kata.get('zan1') == '飛ぶ型':
            head = ('1号艇は飛ぶ型なので X-1-Y を外し 2-3-全・3-2-全＋4-2-3・4-3-2。'
                    '51番人気以降（目安170倍超）は買わない。')
        else:
            head = ('本線 2-1-全・3-1-全（8点）＋押さえ 4-1-2・4-1-3。'
                    '大村の崩れは均等型（頭は3≧2＞4）で1号艇は負けても45%が2着に残る。')
    elif score >= 1.0:
        head = ('要注意：2-1-全・3-1-全を薄く、本命側は 1-4/1-5 の2着流し。')
    else:
        head = ('中穴フォーム：1頭固定・2着を4〜6号艇に寄せる（1-4-全・1-5-全・1-6-2/3）。'
                '大村のイン逃げ決着の43%は15倍以上、その2着は54〜57%が4〜6号艇。')
    return (head + ' ' + ' '.join(notes)).strip()


def label_for(cls, flag, score):
    """カード右肩のラベル（クラス名, 表示文字）。"""
    if cls == '進入固定':
        return 'katame', '鉄板・見送り'
    if cls in ('準優勝戦', '特選系'):
        return 'katame', '鉄板寄り'
    if score >= 3.0:
        return 'ana', '穴の巣'
    if score >= 2.0:
        return 'ana', '崩れゾーン'
    if score >= 1.0:
        return 'nitaku', '要注意'
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
<div><b>大村は「番組が支配するイン水面」</b>（場残差 +3.7pt・イン61%＝全国3位）。崩れるかどうかは
<b>1号艇が出走表の中で相対的に強いか</b>で決まります（勝率1位A級＝イン77%／4位以下＝44%）。
番組表に見えている条件なので、市場も概ね織り込んでいる前提で「候補を絞る道具」として使ってください。</div>
<div><b>主戦場は「初日の1〜6R」</b>（イン36%・万舟21%・15倍以上77%）。慣らし前の1号艇は平均ST0.166と遅く、
級で統制しても−12〜−19pt。7R以降は元に戻る（+8pt）ので「初日」でなく「初日の前半」です。
中日の1〜6Rはほぼ公正で、<b>毎日の前半が穴ではありません</b>。</div>
<div><b>7Rの進入固定は鉄板</b>（イン75%・万舟8%・配当中央値1,080円）。レース番号でなく番組表の「進入固定」で判定しています。
<b>最終日の前半でA級が1号艇</b>（今節成績順の番組・イン76%）、<b>準優・予選特選</b>（イン78〜81%）も見送り寄りです。</div>
<div><b>夜（7R以降・18時台〜）の大村は構造的にイン水面</b>で、番号や級では穴が見つかりませんでした。
夜の買い方は<b>中穴フォーム＝1頭固定・2着を4〜6号艇に寄せる</b>（イン逃げ決着の43%が15倍以上、その2着は54〜57%が4〜6号艇）と、
<b>選手の型</b>（1号艇スロー遅れ●・2号艇壁弱●）の重ね掛けです。3連単51番人気以降（目安170倍超）は買いません。</div>
<div><b>1号艇は負けても45%が2着に残る</b>（残す型70%・飛ぶ型38%）＝X-1-Yが基本。崩れの決まり手はまくり・まくり差し・差しが三等分で、
頭は3≧2＞4。差し水面（平和島）でもまくり水面でもない「均等型」です。</div>
<div><b>風・季節・モーターは採点に入れていません</b>（風速は主効果なし、北系風はWF不一致、季節はヌル、モーターは旧・現行両世代でWF不一致）。
西風・東風3m以上の崩れ（−16／−12pt・n不足）だけ監視中＝直前に西風3m以上なら頭に入れてください。</div>
<div>スコアは大村の365日・2,462レース検証で三条件（方向・有意・前後半一致）を通ったシグナルだけを積んだものです。
機械買いは控除の壁の内側＝スコアは候補絞り用途、オッズの歪みは締切前に人間が判断してください。</div>
"""


TERRAIN_MIN_N = 40


def render_terrain(by_rno, first):
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
        color = '#d96a55' if v['in1'] < 50 else ('#5b93bd' if v['in1'] >= 65 else '#4a5a9c')
        bars.append('<div class="tbar"><div class="col" style="height:%dpx;background:%s"></div>'
                    '<div class="num">%d</div><div class="pct">%d</div></div>'
                    % (h, color, rno, round(v['in1'])))
    cap = 'レース番号別イン率（中日の通常戦・進入固定と特選系を除く・直近12か月）— 7Rは進入固定が大半のため「—」'
    extra = ''
    if first:
        extra = ('<div class="cap" style="margin-top:6px">初日の1〜6R：イン <b style="color:#ffd98a">%d%%</b>・万舟 %d%%・15倍以上 %d%%'
                 '（n=%d）＝ここだけが主戦場</div>' % (round(first['in1']), round(first['man']), round(first['o15']), first['n']))
    return ('<div class="terrain"><div class="cap">%s</div><div class="tbars">%s</div>%s</div>'
            % (cap, ''.join(bars), extra))


def badge_cls(m):
    if m.startswith('スロー遅れ'):
        return 'bg-st'
    if m.startswith('スロー巧者'):
        return 'bg-good'
    if m.startswith('壁強'):
        return 'bg-good'
    if m.startswith('壁'):
        return 'bg-wall'
    if m.startswith('飛ぶ型') or '外し' in m:
        return 'bg-out'
    if m.startswith('残す型'):
        return 'bg-good'
    if m.startswith('絞りまくり'):
        return 'bg-wall'
    return 'bg-low'


def render_card(r, by_rno, first, day_n):
    score, cls, flag, form, notes, kata = r['_sc']
    lab_cls, lab_txt = label_for(cls, flag, score)
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
    base = None
    base_src = ''
    if cls == '通常戦' and not r.get('fixed'):
        if day_n == 1 and r['rno'] <= 6 and first:
            base, base_src = first, '初日1〜6R'
        else:
            base, base_src = by_rno.get(r['rno']), 'この番号の中日'
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
        if b['teiban'] == 1 and r.get('rank1'):
            rk = '<span class="rk%s">勝率%d位</span>' % (' low' if r['rank1'] >= 4 else '', r['rank1'])
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


def render_page(parsed, by_rno, first, failnote=''):
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
                      '日程・級シグナルの信頼度が下がります</div>')
        if day_n == 1:
            banner += ('<div class="banner day1">初日：1〜6R（15〜18時台）が大村の主戦場。'
                       '7R以降は慣らしが終わり元のイン水面に戻ります</div>')
        if parsed.get('is_final'):
            banner += ('<div class="banner final">最終日：前半でA級が1号艇なら今節成績順の番組＝鉄板寄り。'
                       '穴は見送り、乗るなら中穴フォーム（1-4/5/6の2着流し）</div>')
        cards = [render_card(r, by_rno, first, day_n) for r in parsed['races']]
        body = ''.join(cards)
    else:
        body = ('<div class="nokaisai"><b>本日、大村の開催はありません</b>'
                '上の地形図は直近12か月の基礎率です。次回開催日にまた自動更新されます。</div>')

    return """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>大村 穴党ツール</title>
<style>%s</style>
<script src="../venues.js" defer></script>
</head>
<body>
<div class="wrap">
<header>
  <div class="brand">
    <h1>大村 <span class="nami">夜</span> 穴党ツール</h1>
    <div class="datebox">%s%s</div>
  </div>
  <div class="meet">%s</div>
  <nav class="venues" data-venue="omura"></nav>
</header>
<div class="summary">イン水面（場残差 <b>+3.7pt</b>）／イン<b>61%%</b>・万舟<b>15.6%%</b>／主戦場 <b>初日の1〜6R</b>（イン36%%）／7R<b>進入固定</b>は鉄板／夜は<b>中穴フォーム</b>（1-4/5/6の2着流し・50番人気まで）</div>
%s
<div id="failnote">%s</div>
%s
<main>%s</main>
<div class="notes">%s</div>
<footer>更新: %s ／ 大村(24)・365日2,462レース検証</footer>
</div>
</body>
</html>
""" % (CSS, esc(date_s), '' if parsed else '（開催なし）', meet_html,
       render_terrain(by_rno, first), failnote, banner, body, NOTES_HTML, esc(updated))


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


def main():
    print('大村(24) 日次ビルド', TODAY.strftime('%Y-%m-%d'))
    by_rno, first = load_baselines()
    print('  基礎率: レース番号別', len(by_rno), '／ 初日1〜6R', (first or {}).get('n'))
    try:
        if os.environ.get('OM_BFILE'):                       # ローカル検証用：手元のBファイル(テキスト)
            with open(os.environ['OM_BFILE'], encoding='shift_jis', errors='replace') as f:
                raw = f.read()
        else:
            raw = fetch_bfile(TODAY)
        parsed = parse_omura(raw) if raw else None
    except Exception as e:                       # 落とさない（既存方針）
        write_failnote('更新失敗（%s）：番組表を取得できませんでした。前回の内容を表示しています。'
                       % TODAY.strftime('%Y-%m-%d %H:%M'))
        print('  [error]', type(e).__name__, e)
        return
    if parsed:
        for r in parsed['races']:
            r['_sc'] = score_race(r, parsed.get('day_n'), parsed.get('is_final'))
            for b in r['boats']:                 # モーターは参考表示のみ
                if b['teiban'] == 1 and b.get('motor_no'):
                    mt = T_MOTOR.get(str(b['motor_no']))
                    if mt and fnum(mt.get('二連率')) is not None and mt.get('暫定') != 'n不足':
                        b['motor_txt'] = 'M%s 二連率 %.1f%%（参考）' % (b['motor_no'], fnum(mt['二連率']))
                    elif b.get('motor2') is not None:
                        b['motor_txt'] = 'M%s 二連率 %.1f%%（参考）' % (b['motor_no'], b['motor2'])
        print('  開催あり:', parsed.get('title'), '第%s日' % parsed.get('day_n'),
              '最終日' if parsed.get('is_final') else '', '／', len(parsed['races']), 'レース')
    else:
        print('  本日非開催')
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(render_page(parsed, by_rno, first))
    print('  ->', OUT_PATH)


if __name__ == '__main__':
    main()
