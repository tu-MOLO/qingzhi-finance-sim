"""配置类数据的数据访问：字典、配置项、账户、分级、界面文案、提示文案。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import base

# ---------------------------------------------------------------- 字典


def list_dict_types(conn: sqlite3.Connection) -> list[dict]:
    return base.decode_all(conn.execute(
        "SELECT code, name, description, sort_order FROM dict_types ORDER BY sort_order, code").fetchall())


def list_dict_items(conn: sqlite3.Connection, type_code: str | None = None,
                    only_enabled: bool = True) -> list[dict]:
    clauses, params = [], []
    if type_code:
        clauses.append("type_code = ?")
        params.append(type_code)
    if only_enabled:
        clauses.append("enabled = 1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT id, type_code, code, name, short_name, sort_order, enabled, attributes "
        f"FROM dict_items {where} ORDER BY type_code, sort_order, code", params).fetchall()
    return base.decode_all(rows)


def dictionaries(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """按类型分组返回，供前端一次取齐全部枚举。"""
    grouped: dict[str, list[dict]] = {}
    for item in list_dict_items(conn):
        grouped.setdefault(item["type_code"], []).append(item)
    return grouped


# ---------------------------------------------------------------- 配置项


def _coerce(value: Any, value_type: str) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    try:
        if value_type == "integer":
            return int(float(text))
        if value_type == "number":
            return float(text)
        if value_type == "boolean":
            return text.lower() in ("1", "true", "yes", "on")
        if value_type == "json":
            return json.loads(text)
    except (TypeError, ValueError):
        return None
    return text


def settings(conn: sqlite3.Connection) -> dict[str, Any]:
    """读取全部配置并按其声明的类型转换。"""
    rows = conn.execute(
        "SELECT key, group_code, name, value, value_type, unit, description, editable "
        "FROM app_settings ORDER BY group_code, key").fetchall()
    result: dict[str, Any] = {}
    for row in rows:
        result[row["key"]] = _coerce(row["value"], row["value_type"])
    return result


def settings_rows(conn: sqlite3.Connection, group_code: str | None = None) -> list[dict]:
    if group_code:
        rows = conn.execute(
            "SELECT * FROM app_settings WHERE group_code = ? ORDER BY key", (group_code,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM app_settings ORDER BY group_code, key").fetchall()
    return [dict(row) for row in rows]


def setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value, value_type FROM app_settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return _coerce(row["value"], row["value_type"])


def require_setting(conn: sqlite3.Connection, key: str) -> Any:
    from ...common.errors import ConfigurationError
    value = setting(conn, key)
    if value is None:
        raise ConfigurationError(f"缺少必要配置项：{key}", field=key)
    return value


# ---------------------------------------------------------------- 账户与分级


def accounts(conn: sqlite3.Connection) -> list[dict]:
    return base.decode_all(conn.execute(
        "SELECT code, name, description, color, priority, sort_order FROM accounts "
        "ORDER BY sort_order, code").fetchall())


def risk_levels(conn: sqlite3.Connection) -> list[dict]:
    return base.decode_all(conn.execute(
        "SELECT id, code, name, min_cushion_months, equity_cap, sort_order FROM risk_levels "
        "ORDER BY min_cushion_months DESC").fetchall())


# ---------------------------------------------------------------- 文案


def ui_texts(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT key, text FROM ui_texts ORDER BY area, sort_order").fetchall()
    return {row["key"]: row["text"] for row in rows}


def ui_text_rows(conn: sqlite3.Connection) -> list[dict]:
    return base.decode_all(conn.execute(
        "SELECT key, area, text, sort_order FROM ui_texts ORDER BY area, sort_order").fetchall())


def messages(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute("SELECT code, category, title, body, tone FROM messages").fetchall()
    return {row["code"]: dict(row) for row in rows}


def message(conn: sqlite3.Connection, code: str) -> dict | None:
    row = conn.execute("SELECT code, category, title, body, tone FROM messages WHERE code = ?",
                       (code,)).fetchone()
    return None if row is None else dict(row)


def message_body(conn: sqlite3.Connection, code: str, fallback: str = "") -> str:
    row = message(conn, code)
    return fallback if row is None else row["body"]

def message_rows(conn: sqlite3.Connection) -> list[dict]:
    """提示文案的完整行，供配置目录接口直接返回。"""
    rows = conn.execute(
        "SELECT code, category, title, body, tone FROM messages "
        "ORDER BY category, code").fetchall()
    return [dict(row) for row in rows]


def change_log(conn: sqlite3.Connection, size: int) -> list[dict]:
    """最近的变更记录，按时间倒序。size 由调用方限制上限。"""
    rows = conn.execute(
        "SELECT table_name, record_key, action, changed_at FROM change_log "
        "ORDER BY id DESC LIMIT ?", (size,)).fetchall()
    return [dict(row) for row in rows]
