-- 青智方舟 · 数据库结构
-- 约定：
--   1. 所有业务数据存放在本库，代码中不得出现业务常量。
--   2. 枚举与字典统一走 dict_types / dict_items 两张表。
--   3. 可调参数统一走 app_settings，按 group_code 分组。
--   4. 本文件只建结构，业务数据由 database/seeds/ 下的种子文件导入。

PRAGMA foreign_keys = ON;

-- ============================================================ 字典

-- 字典类型：收入来源类别、年级、风险偏好、账户、方案类型、语料类别、参数性质、情景档位等
CREATE TABLE IF NOT EXISTS dict_types (
    code        TEXT PRIMARY KEY,
    name        TEXT    NOT NULL,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

-- 字典项。attributes 存放该项的附加信息（如颜色、系数、上限），以 JSON 文本保存
CREATE TABLE IF NOT EXISTS dict_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type_code  TEXT    NOT NULL REFERENCES dict_types (code) ON DELETE CASCADE,
    code       TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    short_name TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled    INTEGER NOT NULL DEFAULT 1,
    attributes TEXT    NOT NULL DEFAULT '{}',
    UNIQUE (type_code, code)
);

CREATE INDEX IF NOT EXISTS idx_dict_items_type ON dict_items (type_code, sort_order);

-- ============================================================ 配置

-- 应用配置：仿真默认值与边界、求解器参数、容量评估参数、评分权重、模型系数、情景系数
CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    group_code  TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    value       TEXT    NOT NULL,
    value_type  TEXT    NOT NULL,
    unit        TEXT,
    description TEXT,
    editable    INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_app_settings_group ON app_settings (group_code);

-- 风险容量分级：安全垫厚度门槛与对应的权益类建议上限
CREATE TABLE IF NOT EXISTS risk_levels (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    code               TEXT    NOT NULL UNIQUE,
    name               TEXT    NOT NULL,
    min_cushion_months REAL    NOT NULL,
    equity_cap         REAL    NOT NULL,
    sort_order         INTEGER NOT NULL
);

-- 价值分层账户定义
CREATE TABLE IF NOT EXISTS accounts (
    code        TEXT PRIMARY KEY,
    name        TEXT    NOT NULL,
    description TEXT,
    color       TEXT    NOT NULL,
    priority    INTEGER NOT NULL,
    sort_order  INTEGER NOT NULL
);

-- ============================================================ 参数

-- 模型参数表
CREATE TABLE IF NOT EXISTS model_params (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    seq        INTEGER NOT NULL,
    key        TEXT    UNIQUE,
    name       TEXT    NOT NULL,
    value_base REAL,
    value_low  REAL,
    value_high REAL,
    unit       TEXT,
    source     TEXT,
    period     TEXT,
    property   TEXT    NOT NULL,
    note       TEXT,
    enabled    INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_model_params_seq ON model_params (seq);

-- 数据来源索引
CREATE TABLE IF NOT EXISTS data_sources (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    seq      INTEGER,
    name     TEXT NOT NULL,
    period   TEXT,
    supports TEXT,
    url      TEXT
);

-- ============================================================ 内容

-- 术语语料文档
CREATE TABLE IF NOT EXISTS corpus_documents (
    doc_code   TEXT PRIMARY KEY,
    doc_type   TEXT NOT NULL,
    title      TEXT NOT NULL,
    source_url TEXT,
    fetched_at TEXT,
    content    TEXT
);

-- 金融术语
CREATE TABLE IF NOT EXISTS terms (
    term_code       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    layer1          TEXT NOT NULL,
    layer2          TEXT NOT NULL,
    layer3_template TEXT NOT NULL,
    enabled         INTEGER NOT NULL DEFAULT 1,
    sort_order      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS term_aliases (
    term_code TEXT NOT NULL REFERENCES terms (term_code) ON DELETE CASCADE,
    alias     TEXT NOT NULL,
    PRIMARY KEY (term_code, alias)
);

CREATE INDEX IF NOT EXISTS idx_term_alias ON term_aliases (alias);

CREATE TABLE IF NOT EXISTS term_sources (
    term_code  TEXT    NOT NULL REFERENCES terms (term_code) ON DELETE CASCADE,
    doc_code   TEXT    NOT NULL REFERENCES corpus_documents (doc_code) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (term_code, doc_code)
);

-- 提示与合规文案。无目标时的固定合规文案也在其中，对应解释模块的硬约束
CREATE TABLE IF NOT EXISTS messages (
    code     TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    title    TEXT,
    body     TEXT NOT NULL,
    tone     TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_category ON messages (category);

-- 界面文案。页面标题、区块标题、字段标签、按钮、图表标题与轴标签、图例、提示语
CREATE TABLE IF NOT EXISTS ui_texts (
    key        TEXT PRIMARY KEY,
    area       TEXT    NOT NULL,
    text       TEXT    NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ui_texts_area ON ui_texts (area, sort_order);

-- ============================================================ 典型画像

CREATE TABLE IF NOT EXISTS archetypes (
    archetype_id    TEXT PRIMARY KEY,
    kind            TEXT    NOT NULL DEFAULT 'builtin',
    name            TEXT    NOT NULL,
    summary         TEXT,
    highlights      TEXT    NOT NULL DEFAULT '[]',
    -- city 已随城市变量一并移除，列仅为兼容旧库保留，不再参与任何计算
    city            TEXT    NOT NULL DEFAULT '',
    grade           TEXT    NOT NULL DEFAULT '',
    living_cost     REAL    NOT NULL,
    living_growth   REAL    NOT NULL,
    initial_balance REAL    NOT NULL DEFAULT 0,
    risk_appetite   TEXT    NOT NULL,
    months          INTEGER NOT NULL,
    paths           INTEGER NOT NULL,
    seed            INTEGER NOT NULL,
    growth_budget   REAL    NOT NULL DEFAULT 0,
    treat_budget    REAL    NOT NULL DEFAULT 0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    sort_order      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS archetype_income_sources (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    archetype_id   TEXT    NOT NULL REFERENCES archetypes (archetype_id) ON DELETE CASCADE,
    source_type    TEXT    NOT NULL,
    enabled        INTEGER NOT NULL DEFAULT 1,
    probability    REAL    NOT NULL DEFAULT 0,
    amount_low     REAL    NOT NULL DEFAULT 0,
    amount_mid     REAL    NOT NULL DEFAULT 0,
    amount_high    REAL    NOT NULL DEFAULT 0,
    start_month    INTEGER NOT NULL DEFAULT 1,
    end_month      INTEGER NOT NULL DEFAULT 96,
    interrupt_prob REAL    NOT NULL DEFAULT 0,
    UNIQUE (archetype_id, source_type)
);

CREATE INDEX IF NOT EXISTS idx_arch_sources ON archetype_income_sources (archetype_id);

CREATE TABLE IF NOT EXISTS archetype_goals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    archetype_id TEXT    NOT NULL REFERENCES archetypes (archetype_id) ON DELETE CASCADE,
    goal_id      TEXT    NOT NULL,
    name         TEXT    NOT NULL,
    amount       REAL    NOT NULL,
    due_month    INTEGER NOT NULL,
    priority     INTEGER NOT NULL,
    UNIQUE (archetype_id, goal_id)
);

CREATE INDEX IF NOT EXISTS idx_arch_goals ON archetype_goals (archetype_id, priority);

-- ============================================================ 审计

-- 数据变更留痕）。仅记录表名与主键，不记录用户画像内容
CREATE TABLE IF NOT EXISTS change_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT    NOT NULL,
    record_key TEXT    NOT NULL,
    action     TEXT    NOT NULL,
    changed_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_change_log_table ON change_log (table_name, changed_at);
