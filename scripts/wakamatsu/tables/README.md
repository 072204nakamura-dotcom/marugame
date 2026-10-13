# 若松 表の月次更新（Claude Code 用・手元で実行）

1. `mkdir -p lzh_k lzh_b` して `fetch_one.sh` で K/B を365日分取得（`days.txt` は YYYYMM YYMMDD の2列）
   `cat days.txt | xargs -P24 -L1 ./fetch_one.sh K` ／ `... B`（再実行で取りこぼしだけ再取得）
2. `python extract_wm.py`（nat_*.csv / wm_races.csv / wm_entries.csv） → `python parse_b_wm.py`（wm_b_entries.csv）
3. `python build_tables_wm.py` → `data/wakamatsu/` に表一式を生成（BOM付きUTF-8）
4. 生成物をリポジトリの `data/wakamatsu/` に上書き → `python scripts/wakamatsu/test_daily_build_wm.py` が通ることを確認 → コミット

注意：extract_wm.py の RE_HEADER は「進入固定」対応版（大村と同じ）。他場の parse_*.py を流用しないこと。
モーター世代の起点（build_tables_wm.py の GEN_CUT）は交換のたびに更新する（前回 2025-11-26。次回は2026年11月下旬見込み）。
wm_race_resid.csv の gap1 列（3R格差戦の基礎率表示に使う）は build_tables_wm.py が作る。消さないこと。
