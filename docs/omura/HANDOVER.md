# 大村（24）穴党アプリ 引継ぎ指示書 — Claude Code 向け

作成：2026-09-19 ／ 発注者：ももやん ／ 対象リポジトリ：`github.com/072204nakamura-dotcom/marugame`（ローカルにcloneして作業、mainブランチ直接push）
同梱パッケージ：`omura_app_package.zip`（data 12ファイル／scripts 3本＋表更新用4本／docs 4本／workflow 1本／omura/index.html 初回生成物）

---

## 0. ゴール（完成条件）

1. `https://072204nakamura-dotcom.github.io/marugame/omura/` で大村ページが公開される。
2. GitHub Actions が毎朝 **UTC 20:05（JST 5:05）** に自動実行され、当日の出走表（Bファイル）に採用シグナルを当てたレースカードを静的HTMLで生成する。
3. 全ページの会場ナビに「大村」が出る（`venues.js` に1行追加）。
4. `scripts/odds.py` の対象場に **"24"** が加わり、`data/odds/24/` に確定オッズが蓄積され始める。
5. 既存8場のページ・ワークフローを**壊さない**。
6. 判定ロジックは本指示書と docs/omura/ の3文書が正本。**独自の解釈で採点条件を増減しない**こと。

## 1. まず読むもの

- 同梱 `docs/omura/spec_omura.md`（仕様書＝採用/却下シグナルの正本。§4 スコア表・§5 買い目フォーム・§6 技術メモ）
- 同梱 `docs/omura/memo_tables.md`（5表の意味）・`docs/omura/memo_motor.md`（モーターは採点禁止の根拠）
- リポジトリ内の既存会場実装（**heiwajima が兄弟実装**：`scripts/heiwajima/daily_build_hw.py` と同じ骨格）。
- `docs/SCHEDULE.md`（cron の枠取り）。

## 2. してはいけないこと（重要・先に読む）

1. **採点に使ってよいのは spec §4 の表に列挙したものだけ**。以下は採点禁止：
   - 風向・風速・季節・潮位（棄却／ヌル確定。spec §3）
   - **モーター**（旧・現行両世代でWF不一致＝却下。参考表示のみ。memo_motor.md）
   - **レース番号単独**（「1〜6Rは穴」は却下。崩れは**初日**の1〜6Rだけ。spec §3 一行目）
   - 「特選」の部分一致（**一般特選は中立**。拾うのは「予選特選」「特別選抜」「準優」だけ）
2. **進入固定はレース番号（7R）でなくBファイル見出し行の「進入固定」文字列で判定**する。全日固定の節（RS戦等）では1〜12R全部が進入固定になる。
3. **最終日は「本日のBファイルに『優勝戦』（準優を除く）がある」で判定**する。日目や節の長さで判定しない（4日制・5日制・6日制・7日制が混在）。
4. オッズ収集を新規に作らない。`scripts/odds.py` の `VENUES` に "24" を足すだけ。
5. 既存会場のワークフロー cron と同時刻にしない（20:05 を使う。docs/SCHEDULE.md の表に追記）。
6. 表の閾値（壁弱≤−12.5・スロー遅れ>0.18 等）を勝手に再計算・変更しない。数値は同梱CSVの値をそのまま使う。
7. `data/odds/`・他場の `scripts/`・他場の `.github/workflows/*.yml` は触らない。

## 3. 成果物の構成（同梱zipをリポジトリのルートに展開すればこの形になる）

```
marugame/
├─ omura/
│   └─ index.html                 ← 生成物（2026-09-19 生成済み。Actionsが毎朝上書き）
├─ scripts/omura/
│   ├─ daily_build_om.py          ← 日次ビルド本体（heiwajima版と同じ骨格）
│   ├─ judge_omura.py             ← 判定モジュール（spec §4 の判定順序・回帰テスト18本）
│   ├─ test_daily_build_om.py     ← 回帰テスト（ネット不要。Actionsの build 前に実行）
│   └─ tables/                    ← 表の月次更新用（README.md 参照。Actionsでは使わない）
│        extract_omura.py / parse_b.py / build_tables_om.py / fetch_one.sh / README.md
├─ data/omura/
│   ├─ om_st.csv  om_wall.csv  om_zanshi.csv  om_shibori.csv      ← 選手表（採点に使う）
│   ├─ om_motor_current.csv  om_motor_oldgen.csv                  ← モーター（参考表示のみ）
│   ├─ om_race_resid.csv                                          ← 残差付きアーカイブ（基礎率表示に使う）
│   ├─ nat_1c.csv  nat_names.csv                                  ← 全国地力（参考表示）・氏名
│   └─ om_races_archive.csv  om_entries_archive.csv  om_b_archive.csv   ← 検証用アーカイブ（アプリは読まない）
├─ docs/omura/
│   ├─ spec_omura.md  memo_tables.md  memo_motor.md  HANDOVER.md（本書）
└─ .github/workflows/omura.yml
```

## 4. 作業手順

### 4-1. 展開と動作確認（ネット不要）
```bash
cd marugame
unzip -o ~/Downloads/omura_app_package.zip -d .     # 上の構成でファイルが置かれる
pip install lhafile
python scripts/omura/test_daily_build_om.py         # 最後に ALL OK と出ること（47項目）
```
テストが落ちたら**コードを直さず**、展開先のパスが合っているか（`data/omura/*.csv` が読めているか）を確認する。

### 4-2. 実ビルド（ネット必要・mbraceは遅い）
```bash
python scripts/omura/daily_build_om.py              # omura/index.html を上書き
```
- `開催あり: <節名> 第N日 ／ 12 レース` と出れば成功。非開催日は `本日非開催` で開催なしページを作る。
- 手元のBファイルで確認したいとき：`OM_BFILE=/path/to/b260919.txt DATE_OVERRIDE=2026-09-19 python scripts/omura/daily_build_om.py`

### 4-3. 会場ナビに大村を追加（`venues.js`）
`VENUES` 配列の **津（09）と鳴門（14）の間ではなく、場コード順で末尾の福岡（22）の後・「実戦成績」の前**に1行足す：
```js
  { name: '福岡',   path: 'fukuoka'   },  // 22
  { name: '大村',   path: 'omura'     },  // 24   ← 追加
  { name: '実戦成績', path: 'track'   }
```
これだけで全ページのナビに反映される（各ページの `<nav class="venues">` は venues.js が埋める）。`omura/index.html` には `data-venue="omura"` が入っている。

### 4-4. オッズ収集に大村を追加（`scripts/odds.py`）
```python
VENUES = ["15", "03", "22", "02", "14", "17", "09", "04", "24"]   # …津・平和島・大村
```
コメントの場名列にも「大村」を足す。ほかは触らない。翌朝から `data/odds/24/YYYY-MM-DD.csv` が増え始める。

### 4-5. スケジュール表に追記（`docs/SCHEDULE.md`）
「現在の枠」の表に1行追加：`| 20:05 ／ 5:05 | omura.yml | 大村 |`

### 4-6. コミット＆プッシュ
```bash
git add omura scripts/omura data/omura docs/omura .github/workflows/omura.yml venues.js scripts/odds.py docs/SCHEDULE.md
git commit -m "大村(24): 穴党ツール追加（初日前半・相対地力・進入固定・最終日A級／表5種／odds 24）"
git pull --rebase origin main
git push
```
pushが弾かれたら `git pull --rebase origin main` してから再push（朝5〜6時台は自動ビルドと競合しうる）。

### 4-7. 公開確認
1. GitHub → Actions → `omura-daily` → **Run workflow** で手動実行 → 緑になること（test → build → push）。
2. `https://072204nakamura-dotcom.github.io/marugame/omura/` … ヘッダー「大村 夜 穴党ツール」・地形図・当日カードが出る。
3. 丸亀・平和島など他ページのナビに「大村」タブが出てタップで遷移できる。
4. 翌朝、`data/odds/24/` にCSVが1つ増えている。

## 5. 受け入れ基準（アプリの振る舞い）

- 初日（第1日）の1〜6Rに **「初日前半」チップ** と崩れ度+2以上が付く。7R以降には付かない。
- 見出しに「進入固定」があるレースは **「鉄板・見送り」** ラベル（点数に関係なく）。
- 「優勝戦」がある日は、1〜8RでA級が1号艇のレースに **「最終日A級」チップ**（堅さ−1）。
- 1号艇の勝率が出走表内4位以下なら **「勝率N位」バッジが赤**・崩れ度+1。1位のA級なら「1号艇勝率1位A級」チップ。
- 「一般特選」は中立（チップなし）。「予選特選」「準優勝戦」は鉄板寄り。
- 風・モーターの文字は**参考表示のみ**で、崩れ度の数字を動かさない（1号艇の「M○○ 二連率」は表示のみ）。
- ページ下部の注記（NOTES）に「初日の1〜6R」「進入固定」「中穴フォーム」「51番人気」の説明がある。

## 6. 運用メモ

- スコア構成：初日×1〜6R +2／2日目×1〜6R×B級 +0.5（暫定）／1号艇勝率4位以下 +1／1位A級 −1／最終日×1〜8R×A級 −1／1号艇スロー遅れ● +1／巧者● −1／2号艇壁弱● +1／壁強● −1／3・4号艇絞りまくり● +0.5（暫定）
- ラベル：≥3 穴の巣／≥2 崩れゾーン／≥1 要注意／≤−1 鉄板寄り／進入固定・準優・予選特選は鉄板側
- 表の更新は月1回（`scripts/omura/tables/README.md`）。**モーター現行世代の起点は2026-05-24。次回交換 2027年5月中旬**（`build_tables_om.py` の `GEN_CUT`）。
- EV検証はオッズ100R蓄積後（spec §7）。`scripts/ev_backtest.py` への大村追加はその時に別タスク。
- 大村はほぼ毎日開催（年206日）。非開催日は「本日、大村の開催はありません」ページになる。
- 作業が終わったら、作業ログ（ももやんnote\店\アプリ開発\作業ログ.md）に「## 2026-MM-DD 大村 穴党ツール公開」を追記し、ダッシュボードのやりかけ「大村」カードを完了にする。
