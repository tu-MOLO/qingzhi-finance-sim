-- 青智方舟 · 支出项结构
-- 收支分离：收入流来自收入来源，支出项独立成表。每一项都有自己的金额、
-- 是否刚需、年增长率，用户可增删改，而不是用一个固定的「刚需占比」写死。

PRAGMA foreign_keys = ON;

-- 画像的支出项。category 对应 dict_items 中 type_code=expense_category 的条目
CREATE TABLE IF NOT EXISTS archetype_expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    archetype_id TEXT    NOT NULL REFERENCES archetypes (archetype_id) ON DELETE CASCADE,
    category     TEXT    NOT NULL,
    amount       REAL    NOT NULL DEFAULT 0,
    essential    INTEGER NOT NULL DEFAULT 0,
    growth_rate  REAL    NOT NULL DEFAULT 0,
    enabled      INTEGER NOT NULL DEFAULT 1,
    UNIQUE (archetype_id, category)
);

CREATE INDEX IF NOT EXISTS idx_arch_expenses ON archetype_expenses (archetype_id, category);
