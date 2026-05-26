"""從 tpex_ic_crawl/ 自動產生 TW 官方產業分類 YAML。

來源：櫃買中心「產業價值鏈資訊平台」(ic.tpex.org.tw) 47 個產業
產出：
  config/taxonomy/tw/sectors.yaml    — 47 個大產業（每個含 TW 上市/上櫃成員）
  config/taxonomy/tw/segments.yaml   — 上中下游細項（含 parent_sector + stage）

Parser 規則（v0.3.1）：
  1. Segment 名稱來源：`<div id="companyList_XXXX" title="名稱">` 的 title 屬性
     ── 這是 TPEx 官方提供的權威名稱，每個 segment 都有。
  2. Segment stage 來源：往上 traverse HTML 樹找最近的
     `<div class="chain-title-panel">XX</div>`（上游 / 中游 / 下游 / 其他）
     ── 若該大產業沒有 chain 結構（例：Y000 文創、U000 金融），標 stage=""。
  3. Segment members：companyList div 內表格的公司名 → 透過 stocks_meta 反查 stock_id
     ── 對不到 stock_id 的（外國公司、新興櫃）會被略過。
  4. 同代碼合併：若 HTML 有兩份 companyList_XXXX（內外層），members 取聯集。

用法：
    python scripts/build_tw_taxonomy.py
    python scripts/build_tw_taxonomy.py --crawl-root /path/to/tpex_ic_crawl

未來新增市場（美股 GICS、日本 TOPIX）請另寫對應 build_xx_taxonomy.py。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CRAWL = ROOT / "tpex_ic_crawl"
OUT_DIR = ROOT / "config" / "taxonomy" / "tw"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


# ─────────────────────────── data loaders ───────────────────────────

def _load_meta(crawl_root: Path) -> tuple[dict, dict, dict]:
    """讀 codes.json、stocks_meta.json、industries.json。"""
    base = crawl_root / "產業鏈網站素材" / "結構化資料"
    if not base.exists():
        base = crawl_root / "output"
    codes = json.loads((base / "codes.json").read_text(encoding="utf-8"))
    meta = json.loads((base / "stocks_meta.json").read_text(encoding="utf-8"))
    inds = json.loads((base / "industries.json").read_text(encoding="utf-8"))
    return codes, meta, inds


# ─────────────────────────── parser ───────────────────────────

def _find_stage_for_element(el) -> str:
    """往上 traverse 找最近的 chain-title-panel（上游/中游/下游）。

    若不在任何 chain 區塊內 → 回傳空字串。
    """
    # 在同層或祖先層找 <div class="chain"> 包住的 chain-title-panel
    cur = el
    while cur is not None and cur.name is not None:
        # 該節點或其前面 sibling 有 chain-title-panel
        prev = cur
        while prev is not None:
            if hasattr(prev, "attrs"):
                cls = prev.attrs.get("class", []) if prev.attrs else []
                if isinstance(cls, list) and "chain-title-panel" in cls:
                    text = prev.get_text(strip=True)
                    if text:
                        return text
            prev = prev.find_previous_sibling() if hasattr(prev, "find_previous_sibling") else None
        cur = cur.parent
    return ""


def parse_industry_html(html: str, name_to_id: dict[str, str]
                        ) -> list[dict]:
    """從單一產業 HTML 抽出所有 segment。

    回傳：[{code, name, stage, members:set[stock_id]}, ...]
    同代碼合併。
    """
    s = BeautifulSoup(html, "html.parser")
    center = s.find("div", class_="content-panel-center") or s
    out: dict[str, dict] = {}

    for cl in center.find_all("div", id=lambda x: x and x.startswith("companyList_")):
        code = cl["id"].replace("companyList_", "")
        # 1. 名稱：title 屬性（權威來源）
        name = (cl.attrs.get("title") or "").strip()
        if not name:
            # 沒 title 就跳過（v0.3.1 起不再 fallback 用代碼當名稱）
            continue

        # 2. Stage：往上找 chain-title-panel；找對應的 ic_link_<code> 元素再 traverse
        ic_link = center.find(id=f"ic_link_{code}")
        stage = _find_stage_for_element(ic_link) if ic_link else ""

        # 3. Members：companyList 內表格的公司名 → 反查 stock_id
        members: set[str] = set()
        for tr in cl.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            # 第一格通常是 label（"本國上市公司(N家)"），其餘是公司名
            for c in cells[1:]:
                sid = name_to_id.get(c)
                if sid:
                    members.add(sid)

        if code in out:
            # 同代碼合併（HTML 內外層各一份）
            out[code]["members"] |= members
            # 若之前沒拿到 stage 而這次有，補上
            if not out[code]["stage"] and stage:
                out[code]["stage"] = stage
        else:
            out[code] = {
                "code": code,
                "name": name,
                "stage": stage,
                "members": members,
            }

    return list(out.values())


# ─────────────────────────── sector / segment builders ───────────────────────────

def build_sectors(codes: dict, meta: dict, inds: dict) -> list[dict]:
    """47 大產業 → sector-level YAML records。

    成員：codes.stocks 裡 industry_code == ic 的所有 stock_id。
    """
    by_ic: dict[str, list[str]] = {}
    for stk, ic in codes["stocks"].items():
        by_ic.setdefault(ic, []).append(stk)

    out: list[dict] = []
    for ic in codes["industry_codes"]:
        rec = inds.get(ic, {})
        intro = rec.get("intro") or {}
        policy = rec.get("policy") or {}
        title = (intro.get("title") or "").replace("產業鏈簡介", "").strip()
        if not title:
            title = ic
        members = sorted(by_ic.get(ic, []), key=lambda x: (len(x), x))
        out.append({
            "code": ic,
            "name": title,
            "members": members,
            "policy_title": policy.get("title", ""),
            "policy_summary": (policy.get("text") or "")[:280].replace("\n", " "),
        })
    return out


def build_segments(crawl_root: Path, codes: dict, meta: dict) -> list[dict]:
    """從 industry HTML 解析上中下游細項（v0.3.1）。

    每個 segment 帶 parent_sector + stage + members。
    過濾規則：
      - 無 title 的 segment 略過（不再 fallback 用代碼當名稱）
      - 無 members（TW 股全部對不到）的略過
    """
    name_to_id = {v["name"]: k for k, v in meta.items()}
    html_dir = crawl_root / "html" / "industry"

    out: list[dict] = []
    seen: dict[str, dict] = {}
    skipped_no_name = 0
    skipped_empty = 0

    for ic in codes["industry_codes"]:
        html_path = html_dir / f"{ic}.html"
        if not html_path.exists():
            log.warning(f"[segments] missing HTML: {html_path.name}")
            continue
        html = html_path.read_text(encoding="utf-8", errors="replace")
        for seg in parse_industry_html(html, name_to_id):
            # 跨產業同代碼合併（罕見但會發生）
            if seg["code"] in seen:
                prev = seen[seg["code"]]
                prev["members"] |= seg["members"]
                if not prev["stage"] and seg["stage"]:
                    prev["stage"] = seg["stage"]
                continue
            seg["parent_sector"] = ic
            seen[seg["code"]] = seg

    for code, seg in seen.items():
        if not seg["members"]:
            skipped_empty += 1
            continue
        out.append({
            "code": seg["code"],
            "name": seg["name"],
            "stage": seg["stage"] or "",
            "parent_sector": seg["parent_sector"],
            "members": sorted(seg["members"], key=lambda x: (len(x), x)),
        })

    log.info(f"[segments] 略過：無名稱 {skipped_no_name}、無成員 {skipped_empty}")
    return out


# ─────────────────────────── writers ───────────────────────────

def write_yaml(records: list[dict], path: Path, header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_generated_from": "tpex_ic_crawl",
        "_warning": "本檔由 scripts/build_tw_taxonomy.py 自動產生，請勿手動編輯。",
        "items": records,
    }
    text = (
        f"# {header}\n"
        f"# 來源：櫃買中心產業價值鏈資訊平台 ic.tpex.org.tw\n"
        f"# 重新產生：python scripts/build_tw_taxonomy.py\n"
        + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=120)
    )
    path.write_text(text, encoding="utf-8")
    log.info(f"  → {path.relative_to(ROOT)} ({len(records)} items)")


def _stage_summary(records: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in records:
        out[r["stage"] or "(空)"] = out.get(r["stage"] or "(空)", 0) + 1
    return out


def main(crawl_root: Path) -> None:
    if not crawl_root.exists():
        log.error(f"[error] 找不到爬蟲資料夾：{crawl_root}")
        sys.exit(1)

    log.info(f"[build] 讀取 {crawl_root.name}/...")
    codes, meta, inds = _load_meta(crawl_root)

    log.info(f"[build] 47 大產業 sectors.yaml ...")
    sectors = build_sectors(codes, meta, inds)
    write_yaml(sectors, OUT_DIR / "sectors.yaml", "TW 官方產業分類（TPEx 47 大產業）")

    log.info(f"[build] 上中下游 segments.yaml ...")
    segments = build_segments(crawl_root, codes, meta)
    write_yaml(segments, OUT_DIR / "segments.yaml", "TW 產業鏈細項（上中下游 segment）")
    log.info(f"[build] segment stage 分布：{_stage_summary(segments)}")

    log.info(f"[build] ✅ 完成")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--crawl-root", type=Path, default=DEFAULT_CRAWL)
    args = p.parse_args()
    main(args.crawl_root)
