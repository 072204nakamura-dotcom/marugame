# -*- coding: utf-8 -*-
"""
福岡 穴党ツール：当日出走表（racecard.json）
  当日Bファイル → 出走表 ＋ シグナル結線 ＋ 潮位/うねり窓 ＋ 崩れ筋スコア ＋ 買い目方針
実行: python scripts/fukuoka_racecard.py（fukuoka_build.pyの後に）
"""
import os, re, json, unicodedata, urllib.request
from datetime import datetime, timedelta, timezone

JCD = '22'
LZH_B = 'data/lzh_b'
SIG_JSON = 'data/fukuoka_signals.json'
OUT = 'fukuoka/data/racecard.json'
TIDE_ST, TIDE_DIR = 'QF', 'data/tide'
UA = {'User-Agent': 'Mozilla/5.0'}
JST = timezone(timedelta(hours=9))

RE_RACE = re.compile(r'^\s*(\d{1,2})R\s+(\S+)\s+H\d+m\s+電話投票締切予定(\d{1,2}):(\d{2})')
RE_ENT = re.compile(r'^([1-6])\s?(\d{4})(\D+?)(\d{2})(\S{2,3}?)(\d{2})(A1|A2|B1|B2)')
RE_TAIL = re.compile(r'(A1|A2|B1|B2)\s*(\d{1,2}\.\d\d)\s*(\d{1,3}\.\d\d)\s*(\d{1,2}\.\d\d)'
                     r'\s*(\d{1,3}\.\d\d)\s*(\d{1,3})\s*(\d{1,3}\.\d\d)(\d{1,3})\s*(\d{1,3}\.\d\d)')

def today_jst():
    d = os.environ.get('RACECARD_DATE')  # テスト用オーバーライド YYYY-MM-DD
    return datetime.strptime(d, '%Y-%m-%d').date() if d else datetime.now(JST).date()

def get_b_block(d):
    ymd = d.strftime('%y%m%d')
    path = f'{LZH_B}/b{ymd}.lzh'
    if not os.path.exists(path):
        url = f"https://www1.mbrace.or.jp/od2/B/{d.strftime('%Y%m')}/b{ymd}.lzh"
        try:
            req = urllib.request.Request(url, headers=UA)
            data = urllib.request.urlopen(req, timeout=60).read()
            if len(data) > 1000:
                os.makedirs(LZH_B, exist_ok=True)
                open(path, 'wb').write(data)
        except Exception:
            return None
    if not os.path.exists(path):
        return None
    import lhafile
    lf = lhafile.Lhafile(path)
    raw = lf.read(lf.infolist()[0].filename).decode('shift_jis', errors='replace')
    if f'{JCD}BBGN' not in raw:
        return None
    return raw.split(f'{JCD}BBGN')[1].split(f'{JCD}BEND')[0]

def parse_b(blk):
    lines = blk.split('\n')
    title, day_n = '', None
    for i, ln in enumerate(lines[:10]):
        n = unicodedata.normalize('NFKC', ln)
        m = re.search(r'第\s*(\d+)\s*日', n)
        if m and day_n is None:
            day_n = int(m.group(1))
        if i == 5 and ln.strip():
            title = unicodedata.normalize('NFKC', ln.strip())
    races, cur = [], None
    for ln in lines:
        n = unicodedata.normalize('NFKC', ln.rstrip('\r'))
        m = RE_RACE.match(n)
        if m:
            if cur: races.append(cur)
            cur = dict(race=int(m.group(1)), rname=m.group(2),
                       deadline=f'{int(m.group(3)):02d}:{m.group(4)}', entries=[])
            continue
        if cur is None:
            continue
        me = RE_ENT.match(n)
        if me:
            mt = RE_TAIL.search(n)
            cur['entries'].append(dict(
                boat=int(me.group(1)), regno=me.group(2), name=me.group(3).strip(),
                klass=me.group(7),
                win_rate=float(mt.group(2)) if mt else None,
                motor=int(mt.group(6)) if mt else None,
                motor_r2=float(mt.group(7)) if mt else None))
    if cur: races.append(cur)
    return title, day_n, [r for r in races if len(r['entries']) >= 4]

def tide_hours(d):
    path = f'{TIDE_DIR}/{TIDE_ST}_{d.year}.txt'
    if not os.path.exists(path):
        return None
    key = d.isoformat()
    for ln in open(path):
        if len(ln) < 80 or ln[78:80] != TIDE_ST:
            continue
        dd = f"20{int(ln[72:74]):02d}-{int(ln[74:76]):02d}-{int(ln[76:78]):02d}"
        if dd == key:
            return [int(ln[i*3:i*3+3]) for i in range(24)]
    return None

def tide_at(vals, hhmm):
    h, m = map(int, hhmm.split(':'))
    t = min(h + m / 60.0, 23.0)
    i = int(t); j = min(i + 1, 23); f = t - i
    return vals[i] * (1 - f) + vals[j] * f

def daytype(day_n, races):
    rn = ' '.join(r['rname'] for r in races)
    if '優勝' in rn: return '優勝戦日'
    if '準優' in rn: return '準優日'
    if day_n == 1: return '初日'
    return '中盤予選'

DAYNOTE = {
    '優勝戦日': 'イン強化+9.8pt（z=4.1）の最堅日。穴は控えめに（番組全体が固め打ち）',
    '準優日': 'イン強化+5.5ptだが年により振れる（弱採用）',
    '初日': '福岡の初日は万舟率10.1%と全日タイプ中最低の堅い日（「初日は荒れる」は福岡では不成立）',
    '中盤予選': '平常運転（イン残差−2pt）',
}

def build_race(r, sig, motors, tide_cm, race_base):
    score, parts = 0, []
    ents = []
    e_by_boat = {e['boat']: e for e in r['entries']}
    for e in r['entries']:
        s = sig.get(e['regno'], {})
        mo = motors.get(str(e['motor']), {}) if e['motor'] is not None else {}
        chips = []
        if e['boat'] == 1:
            if s.get('st_slow_flag') == '遅れ':
                score += 1; parts.append(f"1号艇スローST{s.get('st_slow')}")
                chips.append(dict(t=f"ST遅れ{s.get('st_slow')}", c='warn'))
            elif s.get('st_slow_flag') == '巧者':
                chips.append(dict(t=f"ST巧者{s.get('st_slow')}", c='safe'))
            f = s.get('f', 0)
            if f >= 2:
                score += 2; parts.append('1号艇F2+'); chips.append(dict(t=f'F{f}', c='warn'))
            elif f == 1:
                score += 1; parts.append('1号艇F1'); chips.append(dict(t='F1', c='warn'))
            if s.get('n1_type'):
                chips.append(dict(t=f"{s['n1_type']}{int(s.get('n1_rate',0)*100)}%",
                                  c='warn' if s['n1_type'] == '飛ぶ型' else 'safe'))
            if mo.get('flag') == '低▲':
                score += 1; parts.append(f"1号艇モーター低▲({mo.get('r2')}%)")
        else:
            if s.get('st_slow_flag') == '巧者':
                chips.append(dict(t='ST巧者', c='info'))
            f = s.get('f', 0)
            if f: chips.append(dict(t=f'F{f}', c='info'))
        if e['boat'] == 2 and s.get('kabe'):
            if s['kabe'] == '壁弱':
                score += 1
                parts.append(f"2号艇壁弱{'(' + s.get('kabe_type') + ')' if s.get('kabe_type') else ''}")
                chips.append(dict(t=f"壁弱{s.get('kabe_type','')}", c='warn'))
            else:
                chips.append(dict(t='壁強', c='safe'))
        if e['boat'] in (3, 4) and s.get('makuri'):
            score += 1; parts.append(f"{e['boat']}号艇絞りまくり")
            chips.append(dict(t='絞りまくり' + ('(暫)' if s.get('makuri_prov') else ''), c='warn'))
        if e['boat'] == 5 and s.get('b5_low'):
            chips.append(dict(t='艇番5低率', c='cut'))
        if e['boat'] == 6:
            if s.get('b6_low'):
                chips.append(dict(t='6ヒモ外し●', c='cut'))
            elif s.get('k6_p2', 0) >= 0.15:
                chips.append(dict(t=f"6コ2着{int(s['k6_p2']*100)}%", c='info'))
        mflag = mo.get('flag', '')
        if mflag == '高●' and e['boat'] >= 3:
            chips.append(dict(t=f"機◎{mo.get('r2')}%", c='hot'))
        ents.append(dict(boat=e['boat'], name=e['name'] or s.get('name', ''),
                         klass=e['klass'], win_rate=e['win_rate'],
                         motor=e['motor'], motor_r2=mo.get('r2'),
                         motor_flag=mflag, chips=chips))
    unari = tide_cm is not None and tide_cm >= 170
    # 買い目方針
    pol = []
    if unari:
        pol.append('うねり窓：2頭(差し系)本線・5頭押さえ／1頭ならヒモ広く／6ヒモ厚張り禁物')
    s1 = sig.get(e_by_boat.get(1, {}).get('regno', ''), {})
    if score >= 3:
        if s1.get('n1_type') == '飛ぶ型':
            pol.append('スコア3+×飛ぶ型：1切りの穴目')
        elif s1.get('n1_type') == '残す型':
            pol.append('スコア3+×残す型：[1]2着固定')
        else:
            pol.append('スコア3+：本気の崩れ筋候補')
    s2 = sig.get(e_by_boat.get(2, {}).get('regno', ''), {})
    if s2.get('kabe_type') == '食う型':
        pol.append('2号艇食う型：2アタマ(2-1)筋')
    if s2.get('kabe_type') == '素通し型' and any(
            sig.get(e_by_boat.get(b, {}).get('regno', ''), {}).get('makuri') for b in (3, 4)):
        pol.append('素通し×絞りまくり：まくり艇アタマ・1,2消しの万舟筋')
    return dict(race=r['race'], rname=r['rname'], deadline=r['deadline'],
                tide=round(tide_cm, 1) if tide_cm is not None else None,
                unari=unari, score=score, parts=parts, policy=pol,
                in_base=race_base.get(str(r['race'])), entries=ents)

def main():
    d = today_jst()
    with open(SIG_JSON, encoding='utf-8') as f:
        S = json.load(f)
    sig, motors = S['racers'], S['motors']
    blk = get_b_block(d)
    out = dict(date=d.isoformat(), updated=datetime.now(JST).isoformat(timespec='minutes'),
               unari_cal=S['unari'], gen_start=S['gen_start'], racing=False)
    vals = tide_hours(d)
    out['tide_today'] = vals
    if blk:
        title, day_n, races = parse_b(blk)
        dt = daytype(day_n, races)
        out.update(racing=True, title=title, day_n=day_n, daytype=dt,
                   daynote=DAYNOTE.get(dt, ''))
        out['races'] = [build_race(r, sig, motors,
                                   tide_at(vals, r['deadline']) if vals else None,
                                   S.get('race_base', {})) for r in races]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('racecard:', d, '開催' if out['racing'] else '非開催',
          f"/ races: {len(out.get('races', []))}")

if __name__ == '__main__':
    main()
