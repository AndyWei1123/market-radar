#!/bin/bash
set -e
cd "$(dirname "$0")"
mkdir -p html/data

fetch_one() {
  local url="$1"
  local out="$2"
  [ -s "$out" ] && return 0
  curl -s -L --max-time 30 -A "Mozilla/5.0" "$url" -o "$out" || rm -f "$out"
}
export -f fetch_one

echo "Data URLs: $(wc -l < /tmp/urls_data.txt)"
xargs -L1 -P 12 bash -c 'fetch_one "$@"' _ < /tmp/urls_data.txt
echo "Data files: $(ls html/data | wc -l)"
