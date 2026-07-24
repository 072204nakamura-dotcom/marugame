# -*- coding: utf-8 -*-
"""江戸川(03) 穴党ツール の回帰テスト（ネットワーク不要）

実行: python scripts/edogawa/test_edogawa.py

指示書§8の受け入れテストを、蓄積済みデータから毎回計算して確認する。
仕様書の数値は2026-07構築時の窓のもの。こちらは毎朝windowが進むので完全一致はしない。
"""
import os
import csv
import sys
import json
import inspect
from collections import Counter, defaultdict

import edogawa_daily as e

FAILED = []


def check(name, cond, detail=''):
    print(('  OK  ' if cond else '  NG! ') + name +
          (('   << ' + detail) if not cond and detail else (('   ' + detail) if detail else '')))
    if not cond:
        FAILED.append(name)


def near(got, want, tol):
    return abs(got - want) <= tol


def load(f, bom=True):
    return list(csv.DictReader(open(os.path.join(e.DATA, f),
                                    encoding='utf-8-sig' if bom else 'utf-8')))


def main():
    races = [r for r in load('ed_races.csv', False) if r['win_course']]
    st = load('江戸川_ST表.csv')
    mak = load('江戸川_絞りまくり表.csv')
    zan = load('江戸川_残し表.csv')
    wall = load('江戸川_壁表.csv')
    fm = load('全国_F持ち_当期.csv')

    print('=== 8-1. データ土台 ===')
    days = len({r['date'] for r in races})
    check('開催日数 184日前後', 165 <= days <= 200, '実測 %d日' % days)
    check('レース数 2,043R前後', 1950 <= len(races) <= 2150, '実測 %dR' % len(races))

    base, rno_table = e.base_stats(races)
    check('1コース1着率 46.7%（±1.5）', near(base['in1'], 46.7, 1.5), '実測 %.1f%%' % base['in1'])
    check('初日イン1着率 40.5%（±2.5・全体より低い）',
          near(base['day1_in1'], 40.5, 2.5) and base['day1_in1'] < base['in1'],
          '実測 %.1f%%（n=%d）' % (base['day1_in1'], base['day1_n']))

    print('=== 決まり手の分布（仕様書: 逃げ912/まくり432/差し300/まくり差し208/抜き198/恵まれ24） ===')
    k = Counter(r['kimarite'] for r in races)
    for nm, want in (('逃げ', 912), ('まくり', 432), ('差し', 300),
                     ('まくり差し', 208), ('抜き', 198), ('恵まれ', 24)):
        check('%s %d本前後（±60）' % (nm, want), abs(k[nm] - want) <= 60,
              '実測 %d本' % k[nm])

    print('=== レース番号別イン1着率（前半戦が谷・6Rが底） ===')
    byr = {x['rno']: x for x in rno_table}
    for rno, want in ((1, 47.2), (6, 34.9), (12, 63.1)):
        got = byr[rno]['in1']
        check('%2dR イン%.1f%%（±3.0）' % (rno, want), near(got, want, 3.0),
              '実測 %.1f%%' % got)
    zone = [byr[r]['in1'] for r in range(2, 7)]
    check('6R が全番号で最も低い', byr[6]['in1'] == min(x['in1'] for x in rno_table),
          '6R %.1f%% / 最小 %.1f%%' % (byr[6]['in1'], min(x['in1'] for x in rno_table)))
    check('前半戦2-6R が後半戦9-12R より低い',
          sum(zone) / 5 < sum(byr[r]['in1'] for r in range(9, 13)) / 4,
          '前半 %.1f%% vs 後半 %.1f%%' % (sum(zone) / 5,
                                        sum(byr[r]['in1'] for r in range(9, 13)) / 4))

    print('=== 6コース連対率（仕様書: 2連率11.0% / 3連率27.1%＝全国最高） ===')
    ed = load('ed_course.csv', False)
    n6 = sum(float(x['n']) for x in ed if x['course'] == '6')
    r2 = sum(float(x['r1']) + float(x['r2']) for x in ed if x['course'] == '6')
    r3 = sum(float(x['r1']) + float(x['r2']) + float(x['r3']) for x in ed if x['course'] == '6')
    check('6コース2連率 11.0%（±1.5）', near(r2 / n6 * 100, 11.0, 1.5),
          '実測 %.1f%%' % (r2 / n6 * 100))
    check('6コース3連率 27.1%（±2.0）', near(r3 / n6 * 100, 27.1, 2.0),
          '実測 %.1f%%' % (r3 / n6 * 100))

    print('=== クロスウィンドウ検証（指示書§2-3・他4窓で再現済みの選手） ===')
    zn = {r['選手名']: r for r in zan}
    wl = {r['選手名']: r for r in wall}
    v = float(zn['太田和美']['残し率'])
    check('太田和美 残す型 76%前後（±6）', near(v * 100, 76, 6) and zn['太田和美']['型'] == '残す型',
          '実測 %.1f%% (%s)' % (v * 100, zn['太田和美']['型']))
    v = float(zn['岡田憲行']['残し率'])
    check('岡田憲行 飛ぶ型 17〜19%（±4）', near(v * 100, 18, 4) and zn['岡田憲行']['型'] == '飛ぶ型',
          '実測 %.1f%% (%s)' % (v * 100, zn['岡田憲行']['型']))
    v = float(wl['廣瀬将亨']['壁力'])
    check('廣瀬将亨 壁強 +16〜+24（±5）', 11 <= v <= 29 and wl['廣瀬将亨']['壁'] == '壁強●',
          '実測 %+.1f (%s)' % (v, wl['廣瀬将亨']['壁']))
    v = float(wl['西島義則']['壁力'])
    check('西島義則 壁弱 −22前後（±5）', near(v, -22, 5) and wl['西島義則']['壁'] == '壁弱●',
          '実測 %+.1f (%s %s)' % (v, wl['西島義則']['壁'], wl['西島義則']['弱タイプ']))

    print('=== テーブルの列構成が既存4場と同一か ===')
    check('ST表の列', [c for c in st[0]][:8] ==
          ['regno', '選手名', '全国スローn', '全国スローST', '当地スローn', '当地スローST',
           '採用スローST', 'スロー源'], str(list(st[0])[:8]))
    check('残し表に11-5の4列がある',
          all(c in zan[0] for c in ('艇番5乗艇', '艇番5_3連対率', '艇番6乗艇', '艇番6_3連対率')))
    check('残し表に6ヒモ外し候補がある', '6ヒモ外し候補' in zan[0])
    check('壁表の列', list(wall[0]) ==
          ['regno', '選手名', 'n2', 'nige', 'exp', '壁力', '負けn', '自分勝ち率',
           'まくり決着率', '壁', '弱タイプ'], str(list(wall[0])))
    check('絞りまくり表の列', list(mak[0]) ==
          ['regno', '選手名', 'n34', 'まくり系1着', '率', '絞りまくり', '暫定'])
    check('F持ち表に区分がある', set(x['区分'] for x in fm) <= {'F1', 'F2+', ''})

    print('=== 8-2. スコアリング（仕様書§4-1） ===')
    L = dict(st={}, mak={}, wall={}, zan={}, f={}, jiriki={}, P0=0.55)

    def mk(rno, regnos=None):
        return dict(rno=rno, rname='予選', deadline='11:00',
                    boats=[dict(teiban=i + 1, regno=(regnos or [''] * 6)[i],
                                name='x', grade='B1') for i in range(6)])

    def sc(rno, nichime, L2=None):
        return e.score_race(mk(rno), nichime, L2 or L)[0]

    check('初日は +2', sc(8, 1) == 2, 'score=%d' % sc(8, 1))
    check('2日目以降は日目加点0', sc(8, 2) == 0, 'score=%d' % sc(8, 2))
    for rno, want in ((1, 0), (2, 1), (3, 1), (4, 1), (5, 1), (6, 2),
                      (7, 0), (8, 0), (9, 0), (10, 0), (11, 0), (12, 0)):
        got = sc(rno, 3)
        check('%2dR の番号加点 +%d' % (rno, want), got == want, 'score=%d' % got)
    check('★初日の6R = ⑨+2 と ⑭+2 で計 +4', sc(6, 1) == 4, 'score=%d' % sc(6, 1))
    check('1R に番号加点が入らない（棄却済み）', sc(1, 3) == 0)
    check('9R に番号加点が入らない（棄却済み）', sc(9, 3) == 0)

    # 初日 × 6R × 1号艇F2 × 4号艇絞りまくり = +7
    L2 = dict(L, f={'A': 'F2+'}, mak={'B': dict(絞りまくり='●', 暫定='')})
    got = e.score_race(mk(6, ['A', '', '', 'B', '', '']), 1, L2)[0]
    check('★初日×6R×1号艇F2×4号艇絞りまくり = +7', got == 7, 'score=%d' % got)

    L3 = dict(L, st={'S': dict(採用スローST=0.20, スロー遅れ='●')})
    check('1号艇スローST>.18 で +1',
          e.score_race(mk(8, ['S'] + [''] * 5), 3, L3)[0] == 1)
    check('2号艇以降のST遅れは加点しない',
          e.score_race(mk(8, ['', 'S'] + [''] * 4), 3, L3)[0] == 0)
    L4 = dict(L, wall={'W': dict(壁='壁弱●', 弱タイプ='素通し型'),
                       'K': dict(壁='壁弱●', 弱タイプ='食う型')})
    check('2号艇が壁弱(素通し型) で +1',
          e.score_race(mk(8, ['', 'W'] + [''] * 4), 3, L4)[0] == 1)
    check('2号艇が壁弱(食う型) は加点しない（⑫は素通し型のみ）',
          e.score_race(mk(8, ['', 'K'] + [''] * 4), 3, L4)[0] == 0)

    print('=== 8-2. 棄却シグナルが混入していないか（仕様書§7） ===')
    src = inspect.getsource(e.score_race) + inspect.getsource(e.policy_for) + \
        inspect.getsource(e.label_for)
    for w in ('風', 'wdir', 'wspd', '潮', 'tide', '潮位', '展示', 'tenji', 'オッズ', 'odds'):
        check('採点系が「%s」を参照していない' % w, w not in src)

    print('=== 8-3. 表示 ===')
    hit = [r for r in zan if r['6ヒモ外し候補'] == '●']
    check('6ヒモ外し● が艇番6_3連対率<25%で立つ',
          all(float(r['艇番6_3連対率']) < 0.25 for r in hit if r['艇番6_3連対率'] != ''),
          '該当 %d人' % len(hit))
    def pol_of(rno, nichime):
        s, forms, notes = e.score_race(mk(rno), nichime, L)
        return e.policy_for(s, forms, notes)

    # 指示書§5は単独初日を「主軸」、重ね掛けを「本線」と書き分けている
    p = pol_of(8, 1)
    check('初日（単独）の方針に「頭≠1を主軸」が出る', '頭≠1を主軸' in p, p[:60])
    p = pol_of(3, 1)
    check('初日×前半戦の方針に「頭≠1を本線」が出る', '頭≠1を本線' in p and '32.5%' in p, p[:60])
    p = pol_of(6, 1)
    check('初日×6R が最濃条件として出る', '初日の6R' in p, p[:60])
    p = pol_of(6, 3)
    check('6R単独（2日目以降）も頭≠1を主軸', '頭≠1を主軸' in p and '34.9%' in p, p[:60])
    check('方針に6の土台ヒモが出る', '3連率27.1%' in pol_of(8, 2), pol_of(8, 2)[:80])
    check('無印レースは中立', '中立' in pol_of(8, 3), pol_of(8, 3)[:40])
    check('江戸川ブロックが無ければ None', e.parse_b('01BBGN\nx\n01BEND') is None)

    if os.path.exists(e.OUT_JSON):
        d = json.load(open(e.OUT_JSON, encoding='utf-8'))
        check('data.json のキーが既存会場と同一',
              all(k in d for k in ('date', 'updated', 'kaisai', 'rno_table')))
        if d.get('kaisai'):
            hh = [int(r['deadline'].split(':')[0]) for r in d['races'] if r['deadline']]
            check('締切時刻の欠損なし',
                  all(r['deadline'] for r in d['races']),
                  '%d/%dR' % (sum(1 for r in d['races'] if r['deadline']), len(d['races'])))
            check('デイタイム開催（締切10〜16時台）', 10 <= min(hh) and max(hh) <= 16,
                  '%d〜%d時' % (min(hh), max(hh)))

    print()
    if FAILED:
        print('NG %d件: %s' % (len(FAILED), ' / '.join(FAILED)))
        return 1
    print('全テスト通過')
    return 0


if __name__ == '__main__':
    sys.exit(main())
