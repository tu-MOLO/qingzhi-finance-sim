-- 青智方舟 · 智能体结构
-- 约定：
--   1. 智能体的定义、提示词、输出结构、工具绑定与运行参数全部入库，
--      代码中只保留执行引擎与各工具、渲染器的实现。
--   2. 新增一个智能体或调整其可用工具，只需要改数据，不需要改代码。
--   3. 外部模型的服务地址、模型名与凭据来源同样入库；凭据本体从环境变量读取，
--      不写入数据库，也不进版本控制。

PRAGMA foreign_keys = ON;

-- ============================================================ 智能体

-- 智能体定义。objective 与 system_prompt 用于外部模型路径；
-- provider 为 inherit 时沿用全局配置，可单独指定 rule 强制走本地规则路径
CREATE TABLE IF NOT EXISTS agents (
    code            TEXT PRIMARY KEY,
    name            TEXT    NOT NULL,
    category        TEXT    NOT NULL,
    description     TEXT    NOT NULL,
    objective       TEXT    NOT NULL,
    system_prompt   TEXT    NOT NULL,
    output_schema   TEXT    NOT NULL DEFAULT '{}',
    provider        TEXT    NOT NULL DEFAULT 'inherit',
    timeout_seconds INTEGER NOT NULL DEFAULT 20,
    enabled         INTEGER NOT NULL DEFAULT 1,
    sort_order      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_agents_category ON agents (category, sort_order);

-- ============================================================ 工具

-- 工具定义。handler 指向 backend/agents/handlers 中已注册的处理器名，
-- 未注册的处理器在运行期被识别为不可用并记入步骤轨迹
CREATE TABLE IF NOT EXISTS agent_tools (
    code        TEXT PRIMARY KEY,
    name        TEXT    NOT NULL,
    kind        TEXT    NOT NULL,
    description TEXT    NOT NULL,
    handler     TEXT    NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_agent_tools_kind ON agent_tools (kind, sort_order);

-- 智能体与工具的绑定关系。required 为假时该工具失败不阻断整个流程
CREATE TABLE IF NOT EXISTS agent_bindings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_code TEXT    NOT NULL REFERENCES agents (code) ON DELETE CASCADE,
    tool_code  TEXT    NOT NULL REFERENCES agent_tools (code) ON DELETE CASCADE,
    required   INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE (agent_code, tool_code)
);

CREATE INDEX IF NOT EXISTS idx_agent_bindings_agent ON agent_bindings (agent_code, sort_order);
