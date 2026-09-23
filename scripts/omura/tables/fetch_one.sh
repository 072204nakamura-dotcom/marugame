#!/bin/bash
# 引数: K|B YYYYMM YYMMDD
T=$1; YM=$2; YMD=$3
L=$(echo $T | tr KB kb)
OUT="lzh_${L}/${L}${YMD}.lzh"
if [ -s "$OUT" ]; then exit 0; fi
curl -sL -A "Mozilla/5.0" --max-time 90 -o "$OUT" "https://www1.mbrace.or.jp/od2/${T}/${YM}/${L}${YMD}.lzh"
if [ ! -s "$OUT" ] || ! head -c 64 "$OUT" | grep -q -- '-lh'; then rm -f "$OUT"; fi
