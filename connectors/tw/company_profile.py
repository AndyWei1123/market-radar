"""MOPS t05st03 公司基本資料抓取。

Endpoint：https://mopsov.twse.com.tw/mops/web/ajax_t05st03
HTML 結構：<th>標籤</th><td>值</td> 的 key-value pair 表格。

解析策略：
  1. 取所有 <table> 內 <th>/<td>，建一個 dict（label → value）
  2. 用 label 關鍵字 mapping 到 schema 欄位
  3. 民國年 yyy/mm/dd → ISO yyyy-mm-dd
  4. 金額（"259,325,245,210元"）→ float
  5. 股數（"25,932,524,521股 (含私募 0股)"）→ (shares_outstanding, shares_private)
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

ENDPOINT = "https://mopsov.twse.com.tw/mops/web/ajax_t05st03"


@dataclass
class CompanyProfile:
    stock_id: str
    market: str = "TW"
    full_name: str | None = None
    short_name_en: str | None = None
    full_name_en: str | None = None
    industry: str | None = None
    foreign_country: str | None = None
    address: str | None = None
    address_en: str | None = None
    phone: str | None = None
    fax: str | None = None
    email: str | None = None
    website: str | None = None
    main_business: str | None = None
    established: str | None = None          # ISO date string
    listing_date: str | None = None
    otc_listing_date: str | None = None
    emerging_date: str | None = None
    public_offering_date: str | None = None
    tax_id: str | None = None
    par_value: float | None = None
    capital: float | None = None
    shares_outstanding: int | None = None
    shares_private: int | None = None
    preferred_shares: int | None = None
    has_preferred: int = 0
    has_corporate_bonds: int = 0
    dividend_frequency: str | None = None
    dividend_decision_lv: str | None = None
    chairman: str | None = None
    ceo: str | None = None
    spokesperson: str | None = None
    spokesperson_title: str | None = None
    spokesperson_phone: str | None = None
    deputy_spokesperson: str | None = None
    ir_contact: str | None = None
    ir_title: str | None = None
    ir_phone: str | None = None
    ir_email: str | None = None
    stakeholder_url: str | None = None
    governance_url: str | None = None
    transfer_agent: str | None = None
    transfer_agent_phone: str | None = None
    transfer_agent_addr: str | None = None
    audit_firm: str | None = None
    auditor_1: str | None = None
    auditor_2: str | None = None
    former_name: str | None = None
    former_short_name: str | None = None
    fiscal_year_month: str | None = None
    report_type: str | None = None
    raw_html: str | None = None


# ───────── helpers ─────────
def _roc_to_iso(s: str) -> str | None:
    """民國年 yyy/mm/dd → ISO yyyy-mm-dd。空字串回 None。"""
    if not s or not s.strip() or s.strip() in ("－", "-"):
        return None
    s = s.strip()
    m = re.match(r"^(\d{2,3})/(\d{1,2})/(\d{1,2})$", s)
    if not m:
        return None
    y = int(m.group(1)) + 1911
    return f"{y:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _parse_money(s: str) -> float | None:
    """'259,325,245,210元' → 259325245210.0"""
    if not s:
        return None
    s = s.replace(",", "").replace("元", "").replace("新台幣", "").strip()
    m = re.search(r"[\d.]+", s)
    return float(m.group()) if m else None


def _parse_shares(s: str) -> tuple[int | None, int | None]:
    """'25,932,524,521股 (含私募 0股)' → (25932524521, 0)"""
    if not s:
        return None, None
    s = s.replace(",", "")
    main = re.search(r"(\d+)\s*股", s)
    priv = re.search(r"私募\s*(\d+)\s*股", s)
    return (
        int(main.group(1)) if main else None,
        int(priv.group(1)) if priv else 0,
    )


def _yn(s: str) -> int:
    """'有' → 1, '無' → 0"""
    if not s:
        return 0
    return 1 if "有" in s else 0


def _clean(s: str | None) -> str | None:
    if s is None:
        return None
    # 移除 &nbsp; 與多餘空白；保留換行（給多行欄位）
    s = s.replace("\xa0", " ").replace("　", " ").strip()
    return s if s and s not in ("－", "-") else None


# ───────── label → setter mapping ─────────
def _kv_to_profile(profile: CompanyProfile, label: str, value: str) -> None:
    L = label.strip()
    V = _clean(value)
    if V is None:
        return
    # 用 if/elif 鏈條手動 mapping（最可靠，每個欄位獨立轉型）
    if L == "公司名稱":
        profile.full_name = V
    elif L == "產業類別":
        profile.industry = V
    elif L == "外國企業註冊地國":
        profile.foreign_country = V
    elif L == "總機":
        profile.phone = V
    elif L == "地址":
        profile.address = V
    elif L == "董事長":
        profile.chairman = V
    elif L == "總經理":
        profile.ceo = V
    elif L == "發言人":
        profile.spokesperson = V
    elif L == "發言人職稱":
        profile.spokesperson_title = V
    elif L == "發言人電話":
        profile.spokesperson_phone = V
    elif L == "代理發言人":
        profile.deputy_spokesperson = V
    elif L == "主要經營業務":
        # 保留換行
        profile.main_business = value.replace("\xa0", " ").strip()
    elif L == "公司成立日期":
        profile.established = _roc_to_iso(V)
    elif L == "營利事業統一編號":
        profile.tax_id = V
    elif L == "實收資本額":
        profile.capital = _parse_money(V)
    elif L == "上市日期":
        profile.listing_date = _roc_to_iso(V)
    elif L == "上櫃日期":
        profile.otc_listing_date = _roc_to_iso(V)
    elif L == "興櫃日期":
        profile.emerging_date = _roc_to_iso(V)
    elif L == "公開發行日期":
        profile.public_offering_date = _roc_to_iso(V)
    elif L == "普通股每股面額":
        m = re.search(r"([\d.]+)", V)
        profile.par_value = float(m.group()) if m else None
    elif "發行普通股數" in L:
        s_out, s_priv = _parse_shares(V)
        profile.shares_outstanding = s_out
        profile.shares_private = s_priv
    elif L == "特別股":
        m = re.search(r"(\d[\d,]*)", V.replace(",", ""))
        profile.preferred_shares = int(re.sub(r"\D", "", V) or 0) or None
    # 特別股 / 公司債發行的 row 結構特殊，由 _post_process_special_rows 處理
    elif "現金股息" in L or "決議層級" in L:
        profile.dividend_decision_lv = V
    elif "分派" in L and "頻率" in L:
        profile.dividend_frequency = V
    elif L == "股票過戶機構":
        profile.transfer_agent = V
    elif L == "電話" and not profile.transfer_agent_phone and profile.transfer_agent:
        profile.transfer_agent_phone = V
    elif L == "過戶地址":
        profile.transfer_agent_addr = V
    elif L == "簽證會計師事務所":
        profile.audit_firm = V
    elif L == "簽證會計師1":
        profile.auditor_1 = V
    elif L == "簽證會計師2":
        profile.auditor_2 = V
    elif L == "英文簡稱":
        profile.short_name_en = V
    elif L == "英文全名":
        profile.full_name_en = V
    elif "英文通訊地址" in L:
        # 拆兩欄合併
        profile.address_en = (profile.address_en or "") + (" " if profile.address_en else "") + V
    elif L == "傳真機號碼":
        profile.fax = V
    elif L == "電子郵件信箱":
        profile.email = V
    elif L == "公司網址":
        profile.website = V
    elif L == "投資人關係聯絡人":
        profile.ir_contact = V
    elif L == "投資人關係聯絡人職稱":
        profile.ir_title = V
    elif L == "投資人關係聯絡電話":
        profile.ir_phone = V
    elif L == "投資人關係電子郵件":
        profile.ir_email = V
    elif "利害" in L and "關係人" in L:
        profile.stakeholder_url = V
    elif "公司治理" in L and "資訊" in L:
        profile.governance_url = V
    elif L == "變更前名稱":
        profile.former_name = V
    elif L == "變更前簡稱":
        profile.former_short_name = V
    elif "月制會計年度" in L:
        profile.fiscal_year_month = V
    elif "編製財務報告" in L:
        profile.report_type = V


# ───────── fetch ─────────
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=10))
def fetch_one(stock_id: str) -> CompanyProfile | None:
    r = requests.post(
        ENDPOINT,
        data={
            "step": "1",
            "firstin": "true",
            "TYPEK": "all",
            "co_id": stock_id,
        },
        timeout=20,
        headers={
            "User-Agent": "Mozilla/5.0 (MarketRadar)",
            "Referer": "https://mopsov.twse.com.tw/",
        },
    )
    if r.status_code != 200 or len(r.text) < 500:
        return None
    if "查無資料" in r.text or "錯誤" in r.text[:1000]:
        return None

    html = r.text
    soup = BeautifulSoup(html, "lxml")
    profile = CompanyProfile(stock_id=stock_id, market="TW", raw_html=html)

    # 走訪所有 <table> 的 row，逐 cell 收集 <th>=label / <td>=value
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            # 走訪 cell 對，每遇到 <th>，下一個非 th cell 視為 value
            i = 0
            while i < len(cells):
                cell = cells[i]
                if cell.name == "th":
                    label = cell.get_text(strip=True)
                    # 找下一個 td
                    j = i + 1
                    while j < len(cells) and cells[j].name == "th":
                        j += 1
                    if j < len(cells):
                        # 對於 main_business 等多行欄位，要保留 <br>
                        if "主要經營業務" in label:
                            # 把 <BR> / <br> 轉成換行
                            for br in cells[j].find_all("br"):
                                br.replace_with("\n")
                            value = cells[j].get_text(strip=True)
                        else:
                            value = cells[j].get_text(strip=True)
                        if label:
                            _kv_to_profile(profile, label, value)
                        i = j + 1
                    else:
                        i = j
                else:
                    i += 1

    # 特殊 row：「本公司 X 特別股發行 / 本公司 Y 公司債發行」
    # 用整段純文字 regex 補抓
    plain = soup.get_text(" ", strip=True)
    plain = re.sub(r"\s+", " ", plain)
    m1 = re.search(r"本公司\s*([有無])\s*特別股發行", plain)
    if m1:
        profile.has_preferred = 1 if m1.group(1) == "有" else 0
    m2 = re.search(r"本公司\s*([有無])\s*公司債發行", plain)
    if m2:
        profile.has_corporate_bonds = 1 if m2.group(1) == "有" else 0

    return profile if profile.full_name else None


if __name__ == "__main__":
    p = fetch_one("2330")
    if p:
        d = asdict(p)
        d.pop("raw_html", None)
        for k, v in d.items():
            if v not in (None, "", 0):
                print(f"  {k}: {v}")
    else:
        print("fetch failed")
