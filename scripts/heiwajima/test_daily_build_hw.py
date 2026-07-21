# -*- coding: utf-8 -*-
"""daily_build_hw.py の回帰テスト（ネットワーク不要）

実行:  python scripts/heiwajima/test_daily_build_hw.py

ここが守っているのは「採点仕様を勝手に増減しない」こと（HANDOVER §2-2・§4）。
表の閾値や加点を触ったらこのテストが落ちます。落ちたら仕様書を確認してください。
"""
import os
import re
import sys
import csv
import inspect
import tempfile

import daily_build_hw as d
from judge_kikaku import run_tests as judge_tests

FAILED = []


def check(name, cond, detail=''):
    print(('  OK  ' if cond else '  NG! ') + name + (('  << ' + detail) if (not cond and detail) else ''))
    if not cond:
        FAILED.append(name)


def mkrace(rno, rname, regnos):
    """テスト用のレースを組み立てる（1〜6号艇に指定の登番を並べる）"""
    return dict(rno=rno, rname=rname, deadline='11:00',
                boats=[dict(teiban=i + 1, regno=r, name='選手%d' % (i + 1), grade='B1',
                            motor_no=None, motor2=None)
                       for i, r in enumerate(regnos)])


# ------------------------------------------------------------------
# 印のない（＝加点ゼロの）登番を表から探しておく
# ------------------------------------------------------------------
def neutral_regnos(n):
    out = []
    for reg in d.T_ST:
        st = d.T_ST.get(reg, {})
        zan = d.T_ZAN.get(reg, {})
        wall = d.T_WALL.get(reg, {})
        sashi = d.T_SASHI.get(reg, {})
        shibori = d.T_SHIBORI.get(reg, {})
        v = d.fnum(st.get('採用スローST'))
        if v is None or v > 0.18:
            continue
        if zan.get('型') or wall.get('壁') or sashi.get('差し巧者') == '●':
            continue
        if shibori.get('絞りまくり') == '●':
            continue
        out.append(reg)
        if len(out) >= n:
            break
    return out


NEU = neutral_regnos(6)
R_ST_LATE = '3202'    # 三品隆浩  採用スローST 0.186 → スロー遅れ●
R_SUDOSHI = '4561'    # 藤山翔大  壁弱●(素通し型)
R_KUU = '5150'        # 坂本雄紀  壁弱●(食う型)
R_KABE = '4460'       # 後藤翔之  壁強●
R_SASHI = '3439'      # 大平誉史明 差し巧者●（壁の印なし＝+1.0を単独で測るため）
R_SASHI_KUU = '5196'  # 鰐部太空海 差し巧者● かつ 壁弱●(食う型) ＝重ね掛けの検体
R_TOBU = '3024'       # 西島義則  飛ぶ型
R_SHIBORI = '4496'    # 内堀学    絞りまくり●


def main():
    print('=== 1. 企画レース判定（spec_kikaku.md §5） ===')
    check('judge_kikaku 11/11', judge_tests())

    print('=== 2. 中立レースの土台 ===')
    check('中立な登番を6人確保できた', len(NEU) == 6, '見つかった数=%d' % len(NEU))
    base4 = d.score_race(mkrace(4, '予選', NEU))[0]
    check('通常戦4R・全員無印 → 0点', base4 == 0, '実際=%g' % base4)

    print('=== 3. レース番号点（企画でない通常戦のみ） ===')
    for rno, want in ((7, 2.0), (3, 1.0), (1, 0.5), (6, 0.5), (5, 0.0), (12, 0.0), (2, 0.0)):
        got = d.score_race(mkrace(rno, '予選', NEU))[0]
        check('通常戦%2dR → +%g' % (rno, want), got == want, '実際=%g' % got)

    print('=== 4. 選手表JOINの加点（HANDOVER §4-3） ===')
    cases = [
        ('1号艇スロー遅れ● +1.0', [R_ST_LATE] + NEU[1:], 1.0),
        ('2号艇壁弱●(素通し) +1.0', [NEU[0], R_SUDOSHI] + NEU[2:], 1.0),
        ('2号艇壁弱●(食う型) +1.0', [NEU[0], R_KUU] + NEU[2:], 1.0),
        ('2号艇差し巧者● +1.0', [NEU[0], R_SASHI] + NEU[2:], 1.0),
        ('1号艇飛ぶ型 +0.5', [R_TOBU] + NEU[1:], 0.5),
        ('3号艇絞りまくり● +0.5', [NEU[0], NEU[1], R_SHIBORI] + NEU[3:], 0.5),
        ('4号艇絞りまくり● +0.5', NEU[:3] + [R_SHIBORI] + NEU[4:], 0.5),
        ('2号艇壁強● 加点なし', [NEU[0], R_KABE] + NEU[2:], 0.0),
    ]
    for label, regs, want in cases:
        got = d.score_race(mkrace(4, '予選', regs))[0]
        check(label, got == want, '実際=%g' % got)

    print('=== 5. 加点の重ね掛け ===')
    got = d.score_race(mkrace(7, '予選', [R_ST_LATE, R_SUDOSHI] + NEU[2:]))[0]
    check('7R(2.0)+スロー遅れ(1.0)+壁弱(1.0) = 4.0', got == 4.0, '実際=%g' % got)
    # 壁弱●と差し巧者●は §4-3 で別々の条件として列挙されているので両方乗る
    got = d.score_race(mkrace(4, '予選', [NEU[0], R_SASHI_KUU] + NEU[2:]))[0]
    check('2号艇が壁弱●かつ差し巧者● = 2.0', got == 2.0, '実際=%g' % got)
    sc, cls, flag, form, notes, c2 = d.score_race(mkrace(7, '予選', [R_ST_LATE, R_SASHI_KUU] + NEU[2:]))
    check('最濃筋 7R+スロー遅れ+壁弱+差し巧者 = 5.0', sc == 5.0, '実際=%g' % sc)
    check('重ね掛け時は差し巧者が方針を決める（§4-4の並び順）', c2 == '差し巧者', 'c2=%s' % c2)

    print('=== 6. 買い目方針の分岐（HANDOVER §4-4 / spec_kikaku.md §3） ===')
    def pol(regs, rno=7, rname='予選'):
        sc, cls, flag, form, notes, c2 = d.score_race(mkrace(rno, rname, regs))
        return d.policy_for(cls, flag, form, c2, notes)
    p = pol([NEU[0], R_KUU] + NEU[2:])
    check('食う型 → 本線2-1-全＋押さえ2-3-1・2-4-1', '2-1-全' in p and '2-3-1' in p, p[:60])
    p = pol([NEU[0], R_SASHI] + NEU[2:])
    check('差し巧者● → 本線2-1-全', '2-1-全' in p, p[:60])
    p = pol([NEU[0], R_SUDOSHI] + NEU[2:])
    check('素通し型 → 3-1-全／4-1-全・2アタマ買わず', '3-1-全' in p and '4-1-全' in p and '2アタマは買わず' in p, p[:60])
    check('素通し型 → 万舟はX-X-1', 'X-X-1' in p, p[:80])
    p = pol([NEU[0], R_KABE] + NEU[2:])
    check('壁強● → 見送り推奨', '見送り推奨' in p, p[:60])
    p = pol(NEU)
    check('印なし → 標準 2-1-全＋3-1-全', '標準' in p and '3-1-全' in p, p[:60])
    p = pol(NEU, 2, '東京ベイラン')
    check('東京ベイランチ → 穴買い禁止・見送り', '穴買い禁止' in p and '見送り' in p, p[:60])
    p = pol([NEU[0], R_SUDOSHI] + NEU[2:], 8, 'ベイブレイク')
    check('ベイブレイク → 4-1／4-流し（差し水面を当てない）', '4-1' in p and '差し水面フォーム（2C/3Cアタマ）は当てはめない' in p, p[:60])
    check('ベイブレイク×2枠壁弱 → 刺さりやすい注記', '刺さりやすい' in p, p[:120])

    print('=== 7. 採点禁止項目が score_race に入り込んでいないか ===')
    src = inspect.getsource(d.score_race)
    for word in ('風', 'wdir', 'wspd', '季節', 'month', 'season', 'motor', 'モーター', '潮', '開幕', 'day_n'):
        check('score_race が「%s」を参照していない' % word, word not in src)
    # モーター番号を変えてもスコアが動かないこと
    r1 = mkrace(7, '予選', NEU)
    r2 = mkrace(7, '予選', NEU)
    for b in r2['boats']:
        b['motor_no'], b['motor2'] = '27', 65.0
    check('モーター番号を変えてもスコア不変', d.score_race(r1)[0] == d.score_race(r2)[0])

    print('=== 8. 基礎率がspec §2の実測値を再現するか ===')
    by_rno, by_cls = d.load_baselines()
    for cls, in1, n in (('東京ベイランチ', 79.0, 100), ('ベイブレイク', 46.5, 99),
                        ('選抜系', 49.4, 87), ('記者選抜', 69.9, 73),
                        ('準優勝戦', 62.5, 64), ('優勝戦', 76.7, 30)):
        v = by_cls.get(cls, {})
        check('%s イン%.1f%% n=%d' % (cls, in1, n),
              abs(v.get('in1', -1) - in1) < 0.15 and v.get('n') == n, str(v))
    for rno, in1, n in ((7, 31.1, 161), (3, 31.7, 161), (1, 33.5, 161), (6, 37.9, 161)):
        v = by_rno.get(rno, {})
        check('通常戦%dR イン%.1f%% n=%d' % (rno, in1, n),
              abs(v.get('in1', -1) - in1) < 0.15 and v.get('n') == n, str(v))

    print('=== 9. 非開催日のページ ===')
    check('04ブロックが無ければ None', d.parse_heiwajima('01BBGN\n dummy \n01BEND') is None)
    page = d.render_page(None, by_rno, by_cls)
    check('「本日非開催」の文言が出る', '本日、平和島の開催はありません' in page)
    check('非開催でも地形図は出る', 'レース番号別イン率' in page)
    check('非開催でも会場ナビが入る', 'data-venue="heiwajima"' in page)

    print('=== 10. 更新失敗時は前回ページを残す（HANDOVER §5） ===')
    tmp = tempfile.mkdtemp()
    saved = d.OUT_PATH
    try:
        d.OUT_PATH = os.path.join(tmp, 'index.html')
        with open(d.OUT_PATH, 'w', encoding='utf-8') as f:
            f.write(d.render_page(None, by_rno, by_cls))
        d.write_failnote('更新失敗（テスト）')
        cur = open(d.OUT_PATH, encoding='utf-8').read()
        check('前回の中身が残っている', '本日、平和島の開催はありません' in cur)
        check('更新失敗が表示される', '更新失敗（テスト）' in cur)
        d.write_failnote('更新失敗（2回目）')
        cur = open(d.OUT_PATH, encoding='utf-8').read()
        check('失敗表示が二重に積み上がらない', cur.count('class="failnote"') == 1)
    finally:
        d.OUT_PATH = saved

    print('=== 11. 生成HTMLの体裁 ===')
    r = mkrace(7, '予選', [R_ST_LATE, R_SUDOSHI] + NEU[2:])
    r['_sc'] = d.score_race(r)
    card = d.render_card(r, by_rno, by_cls)
    check('主戦場バッジが出る', '主戦場' in card, card[:200])
    check('崩れ度が出る', '崩れ度 +4' in card)
    check('スロー遅れ●の印が出る', 'スロー遅れ●' in card)
    check('壁弱●の印が出る', '壁弱●' in card)
    page = d.render_page(dict(title='テスト節', day_n=1, races=[r]), by_rno, by_cls)
    check('カバー率の「条件付き」注意書きが載る', '条件付き' in page and '19.8%' in page)
    check('モーターは参考表示の注記つき', 'モーターは採点に使っていません' in page)
    check('北風3m+の参考注記が載る', '北風3m+' in page)
    page_sp = d.render_page(dict(title='G1 開設記念', day_n=1, races=[r]), by_rno, by_cls)
    check('特殊節バナーが出る（G1）', '特殊節' in page_sp)
    check('通常節ではバナーが出ない', '特殊節' not in page)

    print()
    if FAILED:
        print('NG %d件: %s' % (len(FAILED), ' / '.join(FAILED)))
        return 1
    print('全テスト通過')
    return 0


if __name__ == '__main__':
    sys.exit(main())
