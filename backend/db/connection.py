"""数据库连接、结构与初始化。

数据库是全部业务数据的唯一来源。应用启动时若发现数据库不存在或缺少必要数据，
会从 database/seeds 下的种子文件重建，而不是回落到代码中的默认值。
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .. import config as C
from ..common.errors import ConfigurationError

# 初始化完成后必须存在数据的表，缺一张就重新初始化
REQUIRED_TABLES = (
    "dict_types", "dict_items", "app_settings", "risk_levels", "accounts",
    "model_params", "data_sources", "messages", "ui_texts",
    "corpus_documents", "terms", "term_aliases", "term_sources",
    "archetypes", "archetype_income_sources", "archetype_goals",
    "agents", "agent_tools", "agent_bindings",
)

# 种子文件与目标表、字段的映射。archetypes 与 terms 需要展开为多张表
SEED_PLAN: tuple[tuple[str, str], ...] = (
    ("dict_types.json", "dict_types"),
    ("dict_items.json", "dict_items"),
    ("app_settings.json", "app_settings"),
    ("risk_levels.json", "risk_levels"),
    ("accounts.json", "accounts"),
    ("model_params.json", "model_params"),
    ("data_sources.json", "data_sources"),
    ("messages.json", "messages"),
    ("ui_texts.json", "ui_texts"),
    ("corpus_documents.json", "corpus_documents"),
    ("terms.json", "terms"),
    ("archetypes.json", "archetypes"),
    ("agent_tools.json", "agent_tools"),
    ("agents.json", "agents"),
    ("agent_bindings.json", "agent_bindings"),
)


def connect(path: Any = None) -> sqlite3.Connection:
    """建立连接。行以字典方式访问，启用外键约束。"""
    target = C.DATABASE_FILE if path is None else path
    C.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def session(path: Any = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return conn.execute(sql, params).fetchall()


def query_one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return None if row is None else {key: row[key] for key in row.keys()}  # noqa: SIM118


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [{key: row[key] for key in row.keys()} for row in rows]  # noqa: SIM118


# ---------------------------------------------------------------- 初始化


def schema_files() -> list[Path]:
    """结构文件按文件名顺序执行，支持按序号增量演进。"""
    if not C.SCHEMA_DIR.exists():
        raise ConfigurationError("数据库结构目录缺失，请检查 database/schema 目录")
    files = sorted(C.SCHEMA_DIR.glob("*.sql"))
    if not files:
        raise ConfigurationError("数据库结构目录中没有结构文件，请检查 database/schema 目录")
    return files


def apply_schema(conn: sqlite3.Connection) -> None:
    for path in schema_files():
        conn.executescript(path.read_text(encoding="utf-8"))


def drop_all(conn: sqlite3.Connection) -> None:
    tables = [row["name"] for row in query(
        conn, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    conn.execute("PRAGMA foreign_keys = OFF")
    for name in tables:
        conn.execute(f'DROP TABLE IF EXISTS "{name}"')
    conn.execute("PRAGMA foreign_keys = ON")


def _insert(conn: sqlite3.Connection, table: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    columns = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in columns)
    quoted = ", ".join(f'"{column}"' for column in columns)
    sql = f'INSERT OR REPLACE INTO "{table}" ({quoted}) VALUES ({placeholders})'
    conn.executemany(sql, [tuple(_coerce(row.get(column)) for column in columns) for row in rows])
    return len(rows)


def _coerce(value: Any) -> Any:
    """复合类型以 JSON 文本落库，布尔转为整数。"""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def load_seeds(conn: sqlite3.Connection) -> dict[str, int]:
    """把种子文件导入数据库。archetypes 需要展开为三张表。"""
    counts: dict[str, int] = {}
    for filename, table in SEED_PLAN:
        path = C.SEED_DIR / filename
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get(table, [])

        if table == "terms":
            counts["terms"] = _insert(conn, "terms", [
                {key: value for key, value in row.items() if key not in ("aliases", "sources")}
                for row in rows])
            _insert(conn, "term_aliases", [
                {"term_code": row["term_code"], "alias": alias}
                for row in rows for alias in row.get("aliases", [])])
            _insert(conn, "term_sources", [
                {"term_code": row["term_code"], "doc_code": doc, "sort_order": index * 10}
                for row in rows for index, doc in enumerate(row.get("sources", []))])
            continue

        if table == "archetypes":
            counts["archetypes"] = _insert(conn, "archetypes", [
                {key: value for key, value in row.items()
                 if key not in ("income_sources", "goals", "expenses")}
                for row in rows])
            _insert(conn, "archetype_income_sources", [
                dict(source, archetype_id=row["archetype_id"])
                for row in rows for source in row.get("income_sources", [])])
            _insert(conn, "archetype_goals", [
                dict(goal, archetype_id=row["archetype_id"])
                for row in rows for goal in row.get("goals", [])])
            _insert(conn, "archetype_expenses", [
                dict(expense, archetype_id=row["archetype_id"])
                for row in rows for expense in row.get("expenses", [])])
            continue

        counts[table] = _insert(conn, table, rows)
    return counts


# 每次启动都以种子为准的配置类表。app_settings 刻意不在其中：
# 使用者在设置页填写的生成方式、模型地址与凭据落在那里，回灌会把它们冲掉。
SYNC_TABLES = (
    "ui_texts", "messages", "dict_types", "dict_items", "risk_levels", "accounts",
    "model_params", "data_sources", "agents", "agent_tools", "agent_bindings",
)


def sync_seeds(conn: sqlite3.Connection) -> dict[str, int]:
    """按主键回灌配置类种子，缺的补上、改过的跟随种子更新。

    业务数据与 app_settings 不在回灌范围内：画像、术语、语料由使用者录入维护，
    凭据与生成方式由使用者在设置页填写。只有字典、文案与智能体定义属于代码资产，
    应当随版本一起落到库里，否则改了文案还得手工重建数据库。
    """
    counts: dict[str, int] = {}
    for filename, table in SEED_PLAN:
        if table not in SYNC_TABLES:
            continue
        path = C.SEED_DIR / filename
        if not path.exists():
            continue
        rows = json.loads(path.read_text(encoding="utf-8")).get(table, [])
        counts[table] = _insert(conn, table, rows)
    return counts


def is_ready(conn: sqlite3.Connection) -> bool:
    """数据库是否已具备运行所需的全部数据。

    这里捕获的是 DatabaseError 而不是它的子类 OperationalError：
    文件存在但内容损坏时，SQLite 抛出的正是不属于 OperationalError 的 DatabaseError。
    """
    for table in REQUIRED_TABLES:
        try:
            row = query_one(conn, f'SELECT COUNT(*) AS n FROM "{table}"')
        except sqlite3.DatabaseError:
            return False
        if row is None or row["n"] == 0:
            return False
    return True


def initialize(force: bool = False) -> dict[str, int]:
    """建立结构并导入种子数据。已在位且数据完整时不做任何事。"""
    with session() as conn:
        if not force and is_ready(conn):
            return {"status": "ready"}
        if force:
            drop_all(conn)
        apply_schema(conn)
        counts = load_seeds(conn)
    with session() as conn:
        if not is_ready(conn):
            raise ConfigurationError("数据库初始化后仍缺少必要数据，请检查 database/seeds 目录")
    return counts


def quarantine() -> str:
    """把不可用的数据库文件改名留存，返回改名后的标记。

    数据库文件损坏时不能直接覆盖，先留一份现场，再重建，
    这样既不丢排查线索，也不会让程序在启动阶段崩溃。
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(C.DATABASE_FILE) + suffix)
        if path.exists():
            path.replace(path.with_name(path.name + f".broken-{stamp}"))
    return stamp


def ensure_ready() -> dict[str, str]:
    """供应用启动时调用。覆盖文件缺失、文件损坏与数据不全三种情形。"""
    if not C.DATABASE_FILE.exists():
        initialize()
        return {"status": "created"}

    try:
        with session() as conn:
            ready = is_ready(conn)
    except sqlite3.DatabaseError:
        # 文件在，但读不出来：留档后重建，而不是让异常穿透到启动流程
        stamp = quarantine()
        initialize(force=True)
        return {"status": "rebuilt", "backup": stamp}

    if not ready:
        initialize()
        return {"status": "filled"}
    # 数据齐全的库也要回灌一次：新增或修改过的文案、字典、智能体定义随版本生效
    with session() as conn:
        synced = sync_seeds(conn)
    return {"status": "ready", "tables": ",".join(sorted(synced))}
