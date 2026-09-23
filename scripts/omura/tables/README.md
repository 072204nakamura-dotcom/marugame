# 大村 表の月次更新（Claude Code 用・手元で実行）

1. `mkdir -p lzh_k lzh_b` して `fetch_one.sh` で K/B を365日分取得（`days.txt` は YYYYMM YYMMDD の2列）
   `cat days.txt | xargs -P24 -L1 ./fetch_one.sh K` ／ `... B`（再実行で取りこぼしだけ再取得）
2. `python extract_omura.py`（nat_*.csv / omura_*.csv） → `python parse_b.py`（omura_b_entries.csv）
3. `python build_tables_om.py` → `data/omura/` に表一式を生成（BOM付きUTF-8）
4. 生成物をリポジトリの `data/omura/` に上書き → `python scripts/omura/test_daily_build_om.py` が通ることを確認 → コミット

注意：extract_omura.py の RE_HEADER は「進入固定」対応版（spec §6）。他場の parse_*.py を流用しないこと。
モーター世代の起点（build_tables_om.py の GEN_CUT）は交換のたびに更新する（次回 2027-05）。
