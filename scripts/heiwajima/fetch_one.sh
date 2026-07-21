#!/bin/bash
# 引数: YYYYMM YYMMDD
YM=$1; YMD=$2
OUT="lzh_k/k${YMD}.lzh"
# 既に存在し非ゼロならスキップ
if [ -s "$OUT" ]; then exit 0; fi
URL="https://www1.mbrace.or.jp/od2/K/${YM}/k${YMD}.lzh"
curl -sL -A "Mozilla/5.0" -o "$OUT" "$URL"
# サイズゼロや失敗ページは削除（次回再取得）
if [ ! -s "$OUT" ]; then rm -f "$OUT"; fi
