-- Market Radar SQLite schema (v0.1)
-- 多市場通用設計：所有表都以 market 欄位區分國家

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────
-- 股票主檔
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS stocks (
    stock_id      TEXT NOT NULL,
    market        TEXT NOT NULL,            -- 'TW' / 'US' / 'JP' / 'HK'
    name          TEXT,
    sector        TEXT,                     -- 官方產業
    industry      TEXT,                     -- 細分行業（保留）
    listing_date  DATE,
    market_cap    REAL,
    is_active     INTEGER DEFAULT 1,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_id, market)
);
CREATE INDEX IF NOT EXISTS idx_stocks_market   ON stocks(market);
CREATE INDEX IF NOT EXISTS idx_stocks_sector   ON stocks(sector);

-- ─────────────────────────────────────────────────────────
-- 日線
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_prices (
    stock_id   TEXT NOT NULL,
    market     TEXT NOT NULL,
    date       DATE NOT NULL,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    volume     INTEGER,
    adj_close  REAL,
    PRIMARY KEY (stock_id, market, date)
);
CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_prices(date);

-- ─────────────────────────────────────────────────────────
-- 族群分類（四軸統一：sector / segment / theme / chain）
--   sector  : 大產業（TPEx 47 個 或 TWSE listing）
--   segment : 上中下游細項（屬於某個 sector）
--   theme   : 概念股（手動維護）
--   chain   : 跨市場供應鏈（手動維護，可錨定外國錨股）
-- 統一稱為 "theme" 是歷史命名，實際是 taxonomy 通用表。
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS themes (
    theme_id            TEXT PRIMARY KEY,
    theme_name          TEXT NOT NULL,
    classification_type TEXT NOT NULL,      -- 'sector' / 'segment' / 'theme' / 'chain'
    market_scope        TEXT NOT NULL,      -- 'TW' / 'US' / 'GLOBAL'
    description         TEXT,
    source              TEXT,               -- 'official' / 'manual' / 'moneydj'
    taxonomy_source     TEXT,               -- 'tpex_sector' / 'tpex_segment' / 'twse_listing' / 'manual_theme' / 'manual_chain'
    parent_theme_id     TEXT,               -- segment 對應的 sector_id（其他類型可為 NULL）
    segment_stage       TEXT,               -- '上游' / '中游' / '下游' / NULL
    external_code       TEXT,               -- 來源系統的官方代碼（TPEx ic 碼、GICS code、TOPIX code 等）
    display_order       INTEGER DEFAULT 0,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_themes_type   ON themes(classification_type);
CREATE INDEX IF NOT EXISTS idx_themes_scope  ON themes(market_scope);
-- 新欄位 (parent_theme_id, taxonomy_source) 的索引由 db/init_db.py migrations 建立

CREATE TABLE IF NOT EXISTS theme_membership (
    theme_id   TEXT NOT NULL,
    stock_id   TEXT NOT NULL,
    market     TEXT NOT NULL,
    weight     REAL DEFAULT 1.0,
    PRIMARY KEY (theme_id, stock_id, market),
    FOREIGN KEY (theme_id) REFERENCES themes(theme_id)
);
CREATE INDEX IF NOT EXISTS idx_membership_stock ON theme_membership(stock_id, market);

-- ─────────────────────────────────────────────────────────
-- 族群每日指標（compute_metrics 寫入，儀表板直接讀）
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS theme_daily_metrics (
    theme_id        TEXT NOT NULL,
    date            DATE NOT NULL,
    index_value     REAL,
    pct_change_1d   REAL,
    pct_change_5d   REAL,
    pct_change_20d  REAL,
    ma20            REAL,
    ma60            REAL,
    ma20_slope      REAL,
    rs_score        REAL,                   -- 相對大盤 RS
    rs_momentum     REAL,                   -- RS 的近 4 週變化（給輪動圖用）
    pct_above_ma20  REAL,                   -- 成分股站上 20MA 比例
    rising_day_n    INTEGER DEFAULT 0,
    status          TEXT,                   -- 'rising' / 'candidate' / 'idle' / 'falling'
    PRIMARY KEY (theme_id, date)
);
CREATE INDEX IF NOT EXISTS idx_theme_metrics_date ON theme_daily_metrics(date);
CREATE INDEX IF NOT EXISTS idx_theme_metrics_status ON theme_daily_metrics(status);

-- ─────────────────────────────────────────────────────────
-- 法人 / 融資融券
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS institutional_flow (
    date         DATE NOT NULL,
    stock_id     TEXT NOT NULL,
    market       TEXT NOT NULL,
    foreign_net  INTEGER,
    trust_net    INTEGER,
    dealer_net   INTEGER,
    PRIMARY KEY (date, stock_id, market)
);

CREATE TABLE IF NOT EXISTS margin_balance (
    date          DATE NOT NULL,
    stock_id      TEXT NOT NULL,
    market        TEXT NOT NULL,
    margin_buy    INTEGER,
    margin_sell   INTEGER,
    margin_bal    INTEGER,
    short_sell    INTEGER,
    short_cover   INTEGER,
    short_bal     INTEGER,
    PRIMARY KEY (date, stock_id, market)
);

-- ─────────────────────────────────────────────────────────
-- 新聞（標題層級，AI 摘要欄位預留）
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS news (
    news_id      TEXT PRIMARY KEY,
    source       TEXT,
    url          TEXT,
    title        TEXT NOT NULL,
    published_at DATETIME,
    ai_summary   TEXT,                       -- Phase 2 填
    topics_json  TEXT,                       -- Phase 2 填，JSON array of tags
    fetched_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at);

CREATE TABLE IF NOT EXISTS news_stock_link (
    news_id  TEXT NOT NULL,
    stock_id TEXT NOT NULL,
    market   TEXT NOT NULL,
    PRIMARY KEY (news_id, stock_id, market)
);

-- ─────────────────────────────────────────────────────────
-- 自選股
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS watchlist (
    user_id    TEXT NOT NULL DEFAULT 'default',
    stock_id   TEXT NOT NULL,
    market     TEXT NOT NULL,
    group_name TEXT DEFAULT 'default',
    note       TEXT,
    added_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, stock_id, market)
);

-- ─────────────────────────────────────────────────────────
-- 跨市場對應（Phase 1 只建 schema，不填資料）
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cross_market_mapping (
    source_stock_id TEXT NOT NULL,
    source_market   TEXT NOT NULL,
    target_stock_id TEXT NOT NULL,
    target_market   TEXT NOT NULL,
    mapping_type    TEXT NOT NULL,          -- 'manual' / 'supply_chain' / 'news_cooccurrence'
    confidence      REAL DEFAULT 1.0,
    evidence        TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_stock_id, source_market, target_stock_id, target_market, mapping_type)
);

-- ─────────────────────────────────────────────────────────
-- 大盤指數（加權、櫃買、SOX、Nasdaq…）作為 RS 計算基準
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market_index (
    index_id   TEXT NOT NULL,                -- 'TWII' / 'OTC' / 'SOX' / 'IXIC'
    market     TEXT NOT NULL,
    date       DATE NOT NULL,
    close      REAL,
    volume     INTEGER,
    PRIMARY KEY (index_id, date)
);

-- ─────────────────────────────────────────────────────────
-- 公司基本資料（MOPS t05st03）
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS company_profile (
    stock_id              TEXT NOT NULL,
    market                TEXT NOT NULL,
    -- 識別
    full_name             TEXT,                      -- 公司中文全名
    short_name_en         TEXT,
    full_name_en          TEXT,
    industry              TEXT,
    foreign_country       TEXT,
    -- 聯絡
    address               TEXT,
    address_en            TEXT,
    phone                 TEXT,
    fax                   TEXT,
    email                 TEXT,
    website               TEXT,
    -- 經營
    main_business         TEXT,
    -- 成立 / 上市
    established           DATE,
    listing_date          DATE,
    otc_listing_date      DATE,
    emerging_date         DATE,
    public_offering_date  DATE,
    -- 股本
    tax_id                TEXT,
    par_value             REAL,
    capital               REAL,
    shares_outstanding    INTEGER,
    shares_private        INTEGER,
    preferred_shares      INTEGER,
    has_preferred         INTEGER DEFAULT 0,
    has_corporate_bonds   INTEGER DEFAULT 0,
    -- 股利
    dividend_frequency    TEXT,
    dividend_decision_lv  TEXT,
    -- 人事
    chairman              TEXT,
    ceo                   TEXT,
    spokesperson          TEXT,
    spokesperson_title    TEXT,
    spokesperson_phone    TEXT,
    deputy_spokesperson   TEXT,
    -- IR
    ir_contact            TEXT,
    ir_title              TEXT,
    ir_phone              TEXT,
    ir_email              TEXT,
    -- 治理
    stakeholder_url       TEXT,
    governance_url        TEXT,
    -- 過戶
    transfer_agent        TEXT,
    transfer_agent_phone  TEXT,
    transfer_agent_addr   TEXT,
    -- 會計師
    audit_firm            TEXT,
    auditor_1             TEXT,
    auditor_2             TEXT,
    -- 雜項
    former_name           TEXT,
    former_short_name     TEXT,
    fiscal_year_month     TEXT,
    report_type           TEXT,
    raw_html              TEXT,
    updated_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_id, market)
);
CREATE INDEX IF NOT EXISTS idx_company_industry ON company_profile(industry);

-- ─────────────────────────────────────────────────────────
-- 資料抓取軌跡（debug / 增量更新用）
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ingestion_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name    TEXT NOT NULL,
    started_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME,
    status      TEXT,                         -- 'success' / 'failed' / 'partial'
    rows        INTEGER,
    message     TEXT
);
