"""Discover all industry codes (ic=) by BFS from the homepage."""
import re, time, json, subprocess
from pathlib import Path

BASE = "https://ic.tpex.org.tw/"
HTML_DIR = Path(__file__).parent / "html" / "industry"
HTML_DIR.mkdir(parents=True, exist_ok=True)

def fetch(url):
    r = subprocess.run(
        ["curl", "-s", "-L", "--max-time", "30", "-A", "Mozilla/5.0", url],
        capture_output=True, check=True,
    )
    return r.stdout.decode("utf-8", errors="replace")

def extract_ic_codes(html):
    return set(re.findall(r'introduce\.php\?ic=([A-Z0-9]+)(?:&|"|\b)', html))

def extract_stk_codes(html):
    return set(re.findall(r'stk_code=(\d{4,6})', html))

seen_ic = set()
queue = ["1000"]  # seed: 水泥; will discover via homepage too
home = fetch(BASE + "index.php")
queue.extend(extract_ic_codes(home))

all_stocks = {}  # stk_code -> first industry code seen in
while queue:
    ic = queue.pop(0)
    if ic in seen_ic:
        continue
    seen_ic.add(ic)
    url = f"{BASE}introduce.php?ic={ic}"
    try:
        html = fetch(url)
    except Exception as e:
        print(f"FAIL {ic}: {e}")
        continue
    (HTML_DIR / f"{ic}.html").write_text(html, encoding="utf-8")
    new_ics = extract_ic_codes(html) - seen_ic
    queue.extend(new_ics)
    for stk in extract_stk_codes(html):
        all_stocks.setdefault(stk, ic)
    print(f"  ic={ic}  new_subs={len(new_ics)}  stocks_so_far={len(all_stocks)}")
    time.sleep(0.3)

out = {
    "industry_codes": sorted(seen_ic),
    "stocks": all_stocks,
}
Path(__file__).parent.joinpath("codes.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"\nDone. {len(seen_ic)} industries, {len(all_stocks)} stocks")
