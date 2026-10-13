# 若松（20）穴党アプリ 引継ぎ指示書 — Claude Code 向け

作成：2026-10-12 ／ 発注者：ももやん ／ 対象リポジトリ：`github.com/072204nakamura-dotcom/marugame`（ローカルにcloneして作業、mainブランチ直接push）
同梱パッケージ：`wakamatsu_app_package.zip`（data 11ファイル／scripts 3本＋fixture＋表更新用4本／docs 3本／workflow 1本／wakamatsu/index.html 初回生成物）

---

## 0. ゴール（完成条件）

1. `https://072204nakamura-dotcom.github.io/marugame/wakamatsu/` で若松ページが公開される。
2. GitHub Actions が毎朝 **UTC 20:15（JST 5:15）** に自動実行され、当日の出走表（Bファイル）に採用シグナルを当てたレースカードを静的HTMLで生成する。
3. 全ページの会場ナビに「若松」が出る（`venues.js` に1行追加）。
4. `scripts/odds.py` の対象場に **"20"** が加わり、`data/odds/20/` に確定オッズが蓄積され始める。
5. 既存9場のページ・ワークフローを**壊さない**。
6. 判定ロジックは本指示書と docs/wakamatsu/ の2文書が正本。**独自の解釈で採点条件を増減しない**こと。

## 1. まず読むもの

- 同梱 `docs/wakamatsu/spec_wakamatsu.md`（仕様書＝採用/却下シグナルの正本。§4 スコア表・§5 買い目フォーム・§6 技術メモ）
- 同梱 `docs/wakamatsu/memo_tables.md`（表の意味）
- リポジトリ内の **omura が兄弟実装**（`scripts/omura/daily_build_om.py` と同じ骨格・同じCSS）。
- `docs/SCHEDULE.md`（cron の枠取り）。

## 2. してはいけないこと（重要・先に読む）

1. **採点に使ってよいのは spec §4 の表に列挙したものだけ**。以下は採点禁止：
   - **風速・波高**（採用済みだが朝5時には分からない。「直前ルール」として表示するだけ。予報で自動加点しない）
   - 風向・潮位・季節・開催日目（初日／最終日）・ミッドナイトか否か（却下）
   - **モーター**（WF不一致＝却下。参考表示のみ）
   - **3R以外の格差**（却下。格差の加点は「3R×1号艇B級×格差≤−1.5」だけ）
   - 「特選」の部分一致（**一般特選は中立**。拾うのは「予選特選」「特別選抜」「準優」「ドリー」「優勝」）
   - 8R エイトビートを名前で鉄板にすること（場の補正後は中立）
2. **進入固定はBファイル見出し行の「進入固定」で判定**する（若松は毎日5R「進入固定戦隊」）。
3. 大村の「初日前半」「最終日A級」を若松に持ち込まない（若松では却下済み）。
4. オッズ収集を新規に作らない。`scripts/odds.py` の `VENUES` に "20" を足すだけ。
5. 既存会場のワークフロー cron と同時刻にしない（20:15 を使う。docs/SCHEDULE.md の表に追記）。
6. 表の閾値を勝手に再計算・変更しない。数値は同梱CSVの値をそのまま使う。
7. `data/odds/`・他場の `scripts/`・他場の `.github/workflows/*.yml` は触らない。

## 3. 成果物の構成（同梱zipをリポジトリのルートに展開すればこの形になる）

```
marugame/
├─ wakamatsu/
│   └─ index.html                  ← 生成物（Actionsが毎朝上書き）
├─ scripts/wakamatsu/
│   ├─ daily_build_wm.py           ← 日次ビルド本体（omura版と同じ骨格）
│   ├─ judge_wakamatsu.py          ← 判定モジュール（spec §4 の判定順序・回帰テスト19本）
│   ├─ test_daily_build_wm.py      ← 回帰テスト（ネット不要。Actionsの build 前に実行）
│   ├─ fixtures/b261009_wm.txt     ← テスト用の実Bファイル（2026-10-09・若松ブロックのみ）
│   └─ tables/                     ← 表の月次更新用（README.md 参照。Actionsでは使わない）
│        extract_wm.py / parse_b_wm.py / build_tables_wm.py / fetch_one.sh / README.md
├─ data/wakamatsu/
│   ├─ wm_st.csv  wm_wall.csv  wm_zanshi.csv                     ← 選手表（採点に使う）
│   ├─ wm_motor_current.csv                                       ← モーター（参考表示のみ）
│   ├─ wm_race_resid.csv                                          ← 残差・gap1付き（基礎率表示）
│   ├─ nat_1c.csv  nat_names.csv  wm_shibori.csv
│   └─ wm_races_archive.csv  wm_entries_archive.csv  wm_b_archive.csv   ← 検証用（アプリは読まない）
├─ docs/wakamatsu/
│   ├─ spec_wakamatsu.md  memo_tables.md  HANDOVER.md（本書）
└─ .github/workflows/wakamatsu.yml
```

## 4. 作業手順

### 4-1. 展開と動作確認（ネット不要）
```bash
cd marugame
unzip -o ~/Downloads/wakamatsu_app_package.zip -d .
pip install lhafile
python scripts/wakamatsu/test_daily_build_wm.py        # 最後に ALL OK と出ること
```
テストが落ちたら**コードを直さず**、展開先のパスが合っているか（`data/wakamatsu/*.csv` が読めているか）を確認する。

### 4-2. 実ビルド（ネット必要・mbraceは遅い）
```bash
python scripts/wakamatsu/daily_build_wm.py             # wakamatsu/index.html を上書き
```
- `開催あり: <節名> 第N日 ／ 12 レース` と出れば成功。非開催日は `本日非開催` で開催なしページを作る。
- 手元のBファイルで確認：`WM_BFILE=scripts/wakamatsu/fixtures/b261009_wm.txt DATE_OVERRIDE=2026-10-09 python scripts/wakamatsu/daily_build_wm.py`（確認後は `git checkout wakamatsu/index.html` で戻してよい）

### 4-3. 会場ナビに若松を追加（`venues.js`）
`VENUES` 配列の **福岡（22）の前・宮島（17）の後**（場コード順）に1行足す：
```js
  { name: '宮島',   path: 'miyajima'  },  // 17
  { name: '若松',   path: 'wakamatsu' },  // 20   ← 追加
  { name: '福岡',   path: 'fukuoka'   },  // 22
```
`wakamatsu/index.html` には `data-venue="wakamatsu"` が入っている。

### 4-4. オッズ収集に若松を追加（`scripts/odds.py`）
`VENUES` のリストに `"20"` を足す（末尾でよい）。コメントの場名列にも「若松」を足す。ほかは触らない。

### 4-5. スケジュール表に追記（`docs/SCHEDULE.md`）
「現在の枠」の表の 20:10 の行と 20:20 の行の間に1行追加：`| 20:15 ／ 5:15 | wakamatsu.yml | 若松 |`
見出しの「全8場」は「全10場」に直してよい。

### 4-6. コミット＆プッシュ
```bash
git add wakamatsu scripts/wakamatsu data/wakamatsu docs/wakamatsu .github/workflows/wakamatsu.yml venues.js scripts/odds.py docs/SCHEDULE.md
git commit -m "若松(20): 穴党ツール追加（3R格差戦・勝率最上位・型2種・直前の風波ルール／odds 20）"
git pull --rebase origin main
git push
```
pushが弾かれたら `git pull --rebase origin main` してから再push（朝5〜6時台は自動ビルドと競合しうる）。

### 4-7. 公開確認
1. GitHub → Actions → `wakamatsu-daily` → **Run workflow** → 緑になること（test → build → push）。
2. `https://072204nakamura-dotcom.github.io/marugame/wakamatsu/` … ヘッダー「若松 夜 穴党ツール」・地形図（5Rは「—」）・直前ルールのバナーが出る。非開催日は「本日、若松の開催はありません」。
3. 他ページのナビに「若松」タブが出てタップで遷移できる。
4. 翌朝、`data/odds/20/` にCSVが1つ増えている（開催日のみ）。

## 5. 受け入れ基準（アプリの振る舞い）

- 3Rで1号艇B級・外に勝率1.5以上上の艇 → **「3R格差戦」チップ**・崩れ度+2以上・「穴の巣」。基礎率は「3R格差戦 n=114（イン29%）」。
- 3R以外は格差が大きくても加点なし（1号艇の「格差」バッジが赤になるのは3Rだけ）。
- 1号艇が出走表で勝率最上位（同率含む）→ 「1号艇勝率最上位」・堅さ−1。
- 5R進入固定戦隊 → **「鉄板・見送り」**（型があっても0点）。準優・予選特選・ドリーム・優勝 → 「鉄板寄り」。一般特選・選抜戦・エイトビートは通常戦。
- 1号艇スロー遅れ● +1、2号艇壁弱● +1（食う型／素通し型で方針文が変わる）。
- B級1号艇の通常戦の方針文に「★直前ルール：風5m以上か波5cm以上なら…崩れ度+1で読む」が付く。風・波・モーターは崩れ度の数字を動かさない。
- ページ下部の注記に「3R格差戦」「進入固定戦隊」「直前ルール」「51番人気」の説明がある。

## 6. 運用メモ

- スコア構成：3R格差戦 +2／1号艇勝率最上位 −1／1号艇スロー遅れ● +1／2号艇壁弱● +1（特選系・進入固定には型を加点しない）
- ラベル：≥2 穴の巣／≥1 崩れゾーン／≤−1 鉄板寄り／進入固定は鉄板・見送り／特選系は鉄板寄り
- 表の更新は月1回（`scripts/wakamatsu/tables/README.md`）。**モーター世代の起点は2025-11-26。次回交換は2026年11月下旬見込み**（`build_tables_wm.py` の `GEN_CUT`）。
- 次の別タスク：kaime（GAS）に若松の直前ルール（B級1号艇×風5m+/波5cm+）を足す／EV検証はオッズ100R蓄積後（spec §7）。
- 作業が終わったら、作業ログ（ももやんnote\店\アプリ開発\作業ログ.md）に「## 2026-MM-DD 若松 穴党ツール公開」を追記し、ダッシュボードのやりかけ「若松」カードを完了にする。
