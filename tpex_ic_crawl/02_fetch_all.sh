#!/bin/bash
set -e
cd "$(dirname "$0")"
mkdir -p html/policy html/company

python3 - <<'PY' > /tmp/urls_policy.txt
import json
codes = json.load(open("codes.json"))
for ic in codes["industry_codes"]:
    print(f"https://ic.tpex.org.tw/policy.php?ic={ic} html/policy/{ic}.html")
PY

python3 - <<'PY' > /tmp/urls_company.txt
import json
codes = json.load(open("codes.json"))
PAGES = ["company_basic","company_contact","company_csr","company_event",
         "company_production","company_reward","company_vision"]
for stk in codes["stocks"]:
    for p in PAGES:
        print(f"https://ic.tpex.org.tw/{p}.php?stk_code={stk} html/company/{stk}_{p}.html")
PY

echo "Policy URLs: $(wc -l < /tmp/urls_policy.txt)"
echo "Company URLs: $(wc -l < /tmp/urls_company.txt)"

fetch_one() {
  local url="$1"
  local out="$2"
  [ -s "$out" ] && return 0
  curl -s -L --max-time 30 -A "Mozilla/5.0" "$url" -o "$out" || rm -f "$out"
}
export -f fetch_one

echo "Fetching policy pages..."
xargs -L1 -P 8 bash -c 'fetch_one "$@"' _ < /tmp/urls_policy.txt

echo "Fetching company pages..."
xargs -L1 -P 12 bash -c 'fetch_one "$@"' _ < /tmp/urls_company.txt

echo "Done."
echo "Policy files: $(ls html/policy | wc -l)"
echo "Company files: $(ls html/company | wc -l)"
