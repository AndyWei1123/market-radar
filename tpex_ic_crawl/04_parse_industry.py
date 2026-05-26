"""Parse industry intro pages and policy pages into structured data."""
import json, re
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
codes = json.load(open(ROOT / "codes.json"))

def text(el):
    return el.get_text(" ", strip=True) if el else ""

def parse_industry(html):
    s = BeautifulSoup(html, "html.parser")
    for sc in s(["script", "style"]):
        sc.decompose()
    center = s.find("div", class_="content-panel-center")
    if not center:
        return None

    title_el = center.find("h3")
    title = text(title_el)

    out = {"title": title, "chain": {}, "companies_by_segment": []}

    # 1. Industry chain: 上游/中游/下游 with sub-segments
    main_panel = center.find("div", id="main_ic_panel") or center.find("div", class_="chain-panel")
    if main_panel:
        for chain in main_panel.find_all("div", class_="chain", recursive=False):
            stage_el = chain.find("div", class_="chain-title-panel")
            stage = text(stage_el) if stage_el else ""
            segments = []
            for seg in chain.find_all("div", class_="company-chain-panel"):
                seg_id = seg.get("id", "")
                seg_code = seg_id.replace("ic_link_", "") if seg_id.startswith("ic_link_") else ""
                segments.append({"code": seg_code, "name": text(seg)})
            if stage:
                out["chain"][stage] = segments

    # 2. Company tables per sub-segment
    # Tables usually grouped per sub-industry section
    for tbl in center.find_all("table"):
        rows = tbl.find_all("tr")
        if not rows:
            continue
        section = []
        for row in rows:
            cells = [text(td) for td in row.find_all(["td", "th"])]
            if not cells:
                continue
            # First cell is the label like "本國上市公司(3家)" / "知名外國企業(2家)"
            label = cells[0]
            companies = [c for c in cells[1:] if c]
            section.append({"label": label, "companies": companies})
        if section:
            out["companies_by_segment"].append(section)

    return out

def parse_policy(html):
    s = BeautifulSoup(html, "html.parser")
    for sc in s(["script", "style"]):
        sc.decompose()
    center = s.find("div", class_="content-panel-center")
    if not center:
        return None
    title = text(center.find("h3"))
    body = center.find("div", class_="content") or center
    return {"title": title, "text": body.get_text("\n", strip=True)}

industries = {}
for ic in codes["industry_codes"]:
    intro_p = ROOT / "html" / "industry" / f"{ic}.html"
    policy_p = ROOT / "html" / "policy" / f"{ic}.html"
    rec = {"ic": ic}
    if intro_p.exists():
        rec["intro"] = parse_industry(intro_p.read_text(encoding="utf-8", errors="replace"))
    if policy_p.exists():
        rec["policy"] = parse_policy(policy_p.read_text(encoding="utf-8", errors="replace"))
    industries[ic] = rec

(ROOT / "output" / "industries.json").parent.mkdir(exist_ok=True)
(ROOT / "output" / "industries.json").write_text(
    json.dumps(industries, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"Wrote {len(industries)} industries → output/industries.json")
