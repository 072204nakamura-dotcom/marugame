# -*- coding: utf-8 -*-
"""津 穴党ツール 日次パイプライン
毎朝、当日のBファイル（番組表）を取得し、津(09)のレースに
検証済みシグナル（仕様書・各メモ参照）を適用して tsu/data.json を生成する。
"""
import os, re, io, json, unicodedata, urllib.request, csv
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST)
if os.environ.get('DATE_OVERRIDE'):  # 例: DATE_OVERRIDE=2026-07-14（動作確認用）
    TODAY = datetime.strptime(os.environ['DATE_OVERRIDE'], '%Y-%m-%d').replace(tzinfo=JST)
HERE = os.path.dirname(os.path.abspath(__file__))
TABLE_DIR = os.environ.get('TABLE_DIR', os.path.join(HERE, '..', 'tables'))
OUT_PATH = os.environ.get('OUT_PATH', os.path.join(HERE, '..', 'data.json'))
JCD = '09'

# ---------- Bファイル取得 ----------
def fetch_bfile(dt):
    ym = dt.strftime('%Y%m'); ymd = dt.strftime('%y%m%d')
    url = f'https://www1.mbrace.or.jp/od2/B/{ym}/b{ymd}.lzh'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        raw = urllib.request.urlopen(req, timeout=60).read()
    except Exception:
        return None
    if raw[:20].lower().startswith(b'<html'):
        return None
    try:
        import lhafile
        lf = lhafile.Lhafile(io.BytesIO(raw))
        return lf.read(lf.infolist()[0].filename).decode('shift_jis', errors='replace')
    except Exception:
        return None

# ---------- 津ブロック解析 ----------
def parse_tsu(raw):
    m = re.search(rf'{JCD}BBGN(.*?){JCD}BEND', raw, re.S)
    if not m:
        return None
    blk = m.group(1)
    lines = blk.split('\n')
    title, day_n = '', None
    for ln in lines[:12]:
        n = unicodedata.normalize('NFKC', ln)
        md = re.search(r'第\s*(\d+)\s*日', n)
        if md and day_n is None:
            day_n = int(md.group(1))
        s = n.strip()
        if s and not title and not re.match(r'^\d', s) and 'BBGN' not in s and '番組表' not in s and 'ボートレース' not in s:
            title = s
    races, cur = [], None
    for ln in lines:
        n = unicodedata.normalize('NFKC', ln)
        mh = re.match(r'^\s*(\d{1,2})R\s+(\S+).*?締切予定\s*(\d{1,2}:\d{2})', n)
        if mh:
            if cur: races.append(cur)
            cur = dict(rno=int(mh.group(1)), rname=mh.group(2), deadline=mh.group(3), boats=[])
            continue
        mb = re.match(r'^([1-6]) (\d{4})(.{4})(\d{2})(..)(\d{2})([AB][12])(.*)$', ln)
        if mb and cur is not None:
            toks = unicodedata.normalize('NFKC', mb.group(8)).split()
            motor_no, motor2 = None, None
            if len(toks) >= 6:
                try:
                    motor_no = int(toks[4]); motor2 = float(toks[5])
                except Exception:
                    pass
            cur['boats'].append(dict(
                teiban=int(mb.group(1)), regno=mb.group(2),
                name=mb.group(3).replace('\u3000', '').strip(),
                grade=mb.group(7), motor_no=motor_no, motor2=motor2))
    if cur: races.append(cur)
    races = [r for r in races if len(r['boats']) >= 4]
    return dict(title=title, day_n=day_n, races=races)

# ---------- テーブル読込 ----------
def load_csv(name, key):
    path = os.path.join(TABLE_DIR, name)
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            out[str(row[key]).strip()] = row
    return out

def fnum(v):
    try:
        return float(v)
    except Exception:
        return None

T_JIRIKI = load_csv('national_1c.csv', 'touban')
T_ST = load_csv('tsu_st.csv', 'regno')
T_F = load_csv('national_f_mochi.csv', 'regno')
T_MAK = load_csv('tsu_shibori_makuri.csv', 'regno')
T_NOK = load_csv('tsu_nokoshi.csv', 'regno')
T_KABE = load_csv('tsu_kabe.csv', 'regno')
T_MOTOR = load_csv('tsu_motor.csv', 'motor')
RNO_TABLE = json.load(open(os.path.join(TABLE_DIR, 'rno_table.json'), encoding='utf-8'))

P0 = 0.55  # 全国1コース平均逃げ率
def jiriki(regno):
    r = T_JIRIKI.get(regno)
    if not r:
        return None
    n, w = fnum(r['n1c']) or 0, fnum(r['win1c']) or 0
    return round((w + 20 * P0) / (n + 20) * 100, 1)

# ---------- 津式スコアリング ----------
def score_race(r, day_n):
    score, badges, notes = 0, {b['teiban']: [] for b in r['boats']}, []
    rno = r['rno']
    # 番組構造
    if rno == 4:
        score += 2; notes.append('津の主戦場4R（イン36%・万舟23%）。崩れは差し系＝2-1-X主軸、2-3/2-4が万舟ゾーン。3は頭でなくヒモ。')
    if rno == 7:
        score += 1; notes.append('準穴ゾーン7R（イン43%）。')
    # 節内カーブ
    if day_n:
        if day_n <= 3:
            score += 1
            if day_n == 3:
                score += 1; notes.append('節内最荒れの3日目（万舟20%・イン残差−7pt）。')
            else:
                notes.append('節序盤はイン苦戦（万舟19%）。')
        elif day_n >= 5:
            score -= 1; notes.append('節終盤はイン鉄板化（残差+10pt）。穴は控えめに。')
    for b in r['boats']:
        tb, reg = b['teiban'], b['regno']
        # F持ち
        f = T_F.get(reg)
        if f:
            kb = f.get('区分', '')
            if kb == 'F2+':
                badges[tb].append('F2持ち')
                if tb == 1: score += 2
            elif kb == 'F1':
                badges[tb].append('F1')
                if tb == 1: score += 1
        # ST
        st = T_ST.get(reg)
        if st:
            v = fnum(st.get('採用スローST')) if tb <= 3 else fnum(st.get('採用ダッシュST'))
            if v is not None:
                b['st_avg'] = f'{v:.2f}'
            if tb == 1 and fnum(st.get('採用スローST')) is not None and fnum(st['採用スローST']) > 0.18:
                badges[tb].append('ST遅れ'); score += 1
        # 絞りまくり（3・4号艇）
        mk = T_MAK.get(reg)
        if tb in (3, 4) and mk and mk.get('絞りまくり') == '●':
            badges[tb].append('まくり型' + ('(暫)' if mk.get('暫定') else ''))
            score += 1
        # 壁（2号艇）
        kb2 = T_KABE.get(reg)
        if tb == 2 and kb2:
            if kb2.get('壁') == '壁弱●':
                wt = kb2.get('弱タイプ', '')
                badges[tb].append('壁弱' + (f'({wt})' if wt else ''))
                score += 1
                if wt == '食う型':
                    notes.append('2号艇が食う型（2差し率2倍）→2アタマ（2-1-X）強調。')
                elif wt == '素通し型':
                    notes.append('2号艇が素通し型→まくり系決着に警戒。')
            elif kb2.get('壁') == '壁強●':
                badges[tb].append('壁強')
                notes.append('2号艇が壁（2差し6%）→2-1は消し・イン信頼寄り。')
        # 残し表
        nk = T_NOK.get(reg)
        if nk:
            if tb == 1 and nk.get('型') == '飛ぶ型':
                badges[tb].append('飛ぶ型')
            if tb == 1 and nk.get('型') == '残す型':
                badges[tb].append('残す型')
            if tb == 6:
                r62 = fnum(nk.get('6コ2着率'))
                b['teiban'] = tb
                b['teiban_rate'] = round((fnum(nk.get('艇番6_3連対率')) or 0) * 100, 1) if nk.get('艇番6_3連対率') else None
                if nk.get('6ヒモ外し候補') == '●':
                    badges[tb].append('6外し●')
                elif nk.get('6残し有効') == '○' and r62 is not None and r62 >= 0.12:
                    badges[tb].append('6の2着型')
            if tb == 5 and nk.get('艇番5低率') == '●':
                badges[tb].append('5低率')
                b['teiban_rate'] = round((fnum(nk.get('艇番5_3連対率')) or 0) * 100, 1)
        # モーター
        mt = T_MOTOR.get(str(b.get('motor_no'))) if b.get('motor_no') else None
        if mt:
            if mt.get('判定') == '高●':
                badges[tb].append('M高●')
                if tb == 1:
                    score -= 1; notes.append('1号艇が高●機（WFイン残差+6pt）→イン信頼側。')
            elif mt.get('判定') == '低▲':
                badges[tb].append('M低▲')
                if tb == 1:
                    score += 1; notes.append('1号艇が低▲機（WFイン残差−10pt・万舟増）。')
        if tb == 1:
            b['jiriki'] = jiriki(reg)
    for b in r['boats']:
        b['badges'] = badges[b['teiban']]
        b['motor2'] = f"{b['motor2']:.1f}" if b.get('motor2') is not None else None
        b.pop('motor_no', None)
    return score, notes

def label_for(rno, score):
    if rno in (1, 5):
        return '鉄板企画'
    if score >= 4:
        return '穴の巣'
    if score >= 2:
        return 'イン受難ゾーン'
    if score == 1:
        return '中間'
    return 'イン堅め'

def policy_for(rno, score, notes, label):
    base = {
        '鉄板企画': '穴買い禁止ゾーン。1固定の相手探しに徹する（1R=ツッキー・5R=企画、イン77〜79%）。',
        '穴の巣': '本命崩れの最有力。差し系（2-1-X）主軸で3・4着に4-5-6を回す。',
        'イン受難ゾーン': '崩れ含み。オッズと相談して差し系の穴を検討。',
        '中間': '基礎率どおり。無理に穴を追わない。',
        'イン堅め': 'イン信頼寄り。穴は見送り推奨。',
    }[label]
    extra = ' '.join(notes)
    return (base + ' ' + extra).strip()

# ---------- メイン ----------
def main():
    raw = fetch_bfile(TODAY)
    data = dict(date=TODAY.strftime('%Y-%m-%d'),
                updated=TODAY.strftime('%Y-%m-%d %H:%M JST'),
                kaisai=False, rno_table=RNO_TABLE)
    parsed = parse_tsu(raw) if raw else None
    if parsed and parsed['races']:
        data['kaisai'] = True
        data['title'] = parsed['title']
        data['nichime'] = parsed['day_n']
        out_races = []
        for r in parsed['races']:
            sc, notes = score_race(r, parsed['day_n'])
            lab = label_for(r['rno'], sc)
            base = next((x for x in RNO_TABLE if x['rno'] == r['rno']), None)
            out_races.append(dict(
                rno=r['rno'], rname=r['rname'], deadline=r['deadline'],
                label=lab, score=max(sc, 0),
                base_in1=base['in1'] if base else None,
                policy=policy_for(r['rno'], sc, notes, lab),
                boats=r['boats']))
        data['races'] = out_races
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    json.dump(data, open(OUT_PATH, 'w', encoding='utf-8'), ensure_ascii=False)
    print('kaisai:', data['kaisai'], 'races:', len(data.get('races', [])), '->', OUT_PATH)

if __name__ == '__main__':
    main()
