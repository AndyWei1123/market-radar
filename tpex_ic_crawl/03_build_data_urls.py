"""From the static company_basic.php pages, extract market code (m) and Chinese
abbreviation for each stock, then build the AJAX/iframe URL list."""
import re, json, glob
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
codes = json.load(open(ROOT / "codes.json"))

stocks_meta = {}  # stk -> {"m": "22", "name": "台泥", "ic": "1000"}
for stk, ic in codes["stocks"].items():
    p = ROOT / "html" / "company" / f"{stk}_company_basic.html"
    if not p.exists():
        continue
    txt = p.read_text(encoding="utf-8", errors="replace")
    m_match = re.search(r"company_basic\.php\?s=" + re.escape(stk) + r"&m=(\d+)", txt)
    if not m_match:
        continue
    m = m_match.group(1)
    # extract stkName from company_list iframe -- check other files
    name = None
    for sub in ["company_csr", "company_event", "company_production", "company_reward"]:
        sp = ROOT / "html" / "company" / f"{stk}_{sub}.html"
        if sp.exists():
            t2 = sp.read_text(encoding="utf-8", errors="replace")
            nm = re.search(r'stkName=([^"&]+)', t2)
            if nm:
                name = nm.group(1)
                break
    # fallback: parse <title> or h2 in basic page
    if not name:
        s = BeautifulSoup(txt, "html.parser")
        h2 = s.find("h2") or s.find("h3")
        if h2:
            t = h2.get_text(strip=True)
            t = t.replace("基本資料", "").strip()
            if t:
                name = t
    stocks_meta[stk] = {"m": m, "name": name or stk, "ic": ic}

(ROOT / "stocks_meta.json").write_text(
    json.dumps(stocks_meta, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"stocks with m code: {len(stocks_meta)}")

# Build URL files for the data layer
DATA_DIR = ROOT / "html" / "data"
DATA_DIR.mkdir(exist_ok=True)
import urllib.parse

with open("/tmp/urls_data.txt", "w") as f:
    for stk, meta in stocks_meta.items():
        m = meta["m"]
        name_enc = urllib.parse.quote(meta["name"])
        # basic (JSONP)
        f.write(f"https://dsp.tpex.org.tw/storage/company_basic/company_basic.php?s={stk}&m={m} html/data/{stk}_basic.jsonp\n")
        # finance report
        f.write(f"https://dsp.tpex.org.tw/storage/finance_report/company_finance_report.php?s={stk}&m={m} html/data/{stk}_finance.jsonp\n")
        # vision (2 columns)
        f.write(f"https://ic.tpex.org.tw/company_data.php?table=company_vision&column=vision_text&userId={stk} html/data/{stk}_vision_text.html\n")
        f.write(f"https://ic.tpex.org.tw/company_data.php?table=company_vision&column=vision_story&userId={stk} html/data/{stk}_vision_story.html\n")
        # list pages
        for t in ["company_csr", "company_event", "company_product", "company_reward"]:
            f.write(f"https://ic.tpex.org.tw/company_list.php?t={t}&stk={stk}&stkName={name_enc} html/data/{stk}_{t}.html\n")

import subprocess
n = subprocess.check_output(["wc", "-l", "/tmp/urls_data.txt"]).decode().split()[0]
print(f"data URLs to fetch: {n}")
