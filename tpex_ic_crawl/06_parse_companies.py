"""Parse company-level data into structured JSON keyed by stk_code."""
import json, re
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
meta = json.load(open(ROOT / "stocks_meta.json"))

def read(p):
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""

def parse_jsonp(txt):
    if not txt:
        return None
    m = re.search(r"\((.*)\)\s*;?\s*$", txt, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None

def parse_contact_static(stk):
    """Parse contact data inlined in static company_contact.php page."""
    p = ROOT / "html" / "company" / f"{stk}_company_contact.html"
    txt = read(p)
    if not txt:
        return None
    s = BeautifulSoup(txt, "html.parser")
    for sc in s(["script", "style"]):
        sc.decompose()
    out = {}
    # Pairs are labeled rows in the form
    body = s.body
    if not body:
        return None
    # Look for table-like or dt/dd structure
    for label in ["聯絡人", "公務電話", "電子郵件", "公司網址", "公司電話", "公司傳真", "公司地址"]:
        # find the text node and grab the next sibling text
        found = body.find(string=re.compile(r"^\s*" + re.escape(label) + r"\s*$"))
        if found:
            # the value usually sits in the following td or div
            parent = found.parent
            sib = parent.find_next_sibling()
            if sib:
                v = sib.get_text(" ", strip=True)
                if v and v != label:
                    out[label] = v
    return out or None

def parse_iframe_html(p):
    """Generic parser for company_data.php / company_list.php iframe HTML."""
    txt = read(p)
    if not txt:
        return None
    s = BeautifulSoup(txt, "html.parser")
    for sc in s(["script", "style"]):
        sc.decompose()
    t = s.get_text("\n", strip=True)
    return t or None

stocks = {}
for stk, m in meta.items():
    rec = {
        "stk_code": stk,
        "name": m["name"],
        "industry_code": m["ic"],
        "market_code": m["m"],
    }
    # basic JSONP
    rec["basic"] = parse_jsonp(read(ROOT / "html" / "data" / f"{stk}_basic.jsonp"))
    rec["finance"] = parse_jsonp(read(ROOT / "html" / "data" / f"{stk}_finance.jsonp"))
    rec["contact"] = parse_contact_static(stk)
    rec["vision_text"] = parse_iframe_html(ROOT / "html" / "data" / f"{stk}_vision_text.html")
    rec["vision_story"] = parse_iframe_html(ROOT / "html" / "data" / f"{stk}_vision_story.html")
    rec["csr"] = parse_iframe_html(ROOT / "html" / "data" / f"{stk}_company_csr.html")
    rec["events"] = parse_iframe_html(ROOT / "html" / "data" / f"{stk}_company_event.html")
    rec["products"] = parse_iframe_html(ROOT / "html" / "data" / f"{stk}_company_product.html")
    rec["rewards"] = parse_iframe_html(ROOT / "html" / "data" / f"{stk}_company_reward.html")
    stocks[stk] = rec

out_p = ROOT / "output" / "companies.json"
out_p.write_text(json.dumps(stocks, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Wrote {len(stocks)} companies → {out_p}")
print(f"Size: {out_p.stat().st_size / 1024 / 1024:.1f} MB")
