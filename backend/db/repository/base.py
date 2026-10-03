"""数据访问层的公共工具。

只允许白名单内的表与字段参与写入，所有语句均使用参数化占位符。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from typing import Any

from ...common.errors import ConflictError, NotFoundError

# 每张表允许写入的字段。任何未列出的表或字段都无法通过接口写入
WRITABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "dict_types": ("code", "name", "description", "sort_order"),
    "dict_items": ("id", "type_code", "code", "name", "short_name", "sort_order", "enabled", "attributes"),
    "app_settings": ("key", "group_code", "name", "value", "value_type", "unit", "description", "editable"),
    "risk_levels": ("id", "code", "name", "min_cushion_months", "equity_cap", "sort_order"),
    "accounts": ("code", "name", "description", "color", "priority", "sort_order"),
    "model_params": ("id", "seq", "key", "name", "value_base", "value_low", "value_high",
                     "unit", "source", "period", "property", "note", "enabled"),
    "data_sources": ("id", "seq", "name", "period", "supports", "url"),
    "corpus_documents": ("doc_code", "doc_type", "title", "source_url", "fetched_at", "content"),
    "terms": ("term_code", "name", "layer1", "layer2", "layer3_template", "enabled", "sort_order"),
    "term_aliases": ("term_code", "alias"),
    "term_sources": ("term_code", "doc_code", "sort_order"),
    "messages": ("code", "category", "title", "body", "tone"),
    "ui_texts": ("key", "area", "text", "sort_order"),
    "archetypes": ("archetype_id", "kind", "name", "summary", "highlights", "city", "grade",
                   "living_cost", "living_growth", "initial_balance", "risk_appetite",
                   "months", "paths", "seed", "growth_budget", "treat_budget", "enabled", "sort_order"),
    "archetype_income_sources": ("id", "archetype_id", "source_type", "enabled", "probability",
                                 "amount_low", "amount_mid", "amount_high", "start_month",
                                 "end_month", "interrupt_prob"),
    "archetype_goals": ("id", "archetype_id", "goal_id", "name", "amount", "due_month", "priority"),
}

# 每张表的业务主键。写入时先按键更新，找不到才插入，
# 这样局部字段的修改不会被误当成新记录而触发非空约束。
UPSERT_KEYS: dict[str, tuple[str, ...]] = {
    "dict_types": ("code",),
    "dict_items": ("type_code", "code"),
    "app_settings": ("key",),
    "risk_levels": ("code",),
    "accounts": ("code",),
    "model_params": ("key",),
    "data_sources": ("id",),
    "corpus_documents": ("doc_code",),
    "terms": ("term_code",),
    "messages": ("code",),
    "ui_texts": ("key",),
    "archetypes": ("archetype_id",),
    "archetype_income_sources": ("id",),
    "archetype_goals": ("id",),
}

# 需要以 JSON 文本落库的字段
JSON_COLUMNS = {"attributes", "highlights"}


def encode(value: Any, column: str) -> Any:
    if column in JSON_COLUMNS and not isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def decode(row: sqlite3.Row | dict | None) -> dict | None:
    if row is None:
        return None
    data = ({key: row[key] for key in row.keys()}   # noqa: SIM118  sqlite3.Row 迭代出的是值
            if isinstance(row, sqlite3.Row) else dict(row))
    for column in JSON_COLUMNS & set(data):
        if isinstance(data[column], str):
            try:
                data[column] = json.loads(data[column])
            except json.JSONDecodeError:
                data[column] = None
    return data


def decode_all(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [decode(row) for row in rows]


def filter_columns(table: str, payload: dict) -> dict:
    """按白名单过滤入参，未知字段直接丢弃。"""
    allowed = WRITABLE_COLUMNS.get(table)
    if allowed is None:
        raise ValueError(f"表 {table} 不在可写白名单内")
    return {key: value for key, value in payload.items() if key in allowed}


def upsert(conn: sqlite3.Connection, table: str, payload: dict) -> dict:
    """按键更新，命中不到才插入。"""
    row = filter_columns(table, payload)
    if not row:
        raise ValueError(f"表 {table} 的写入内容为空")

    keys = UPSERT_KEYS.get(table, ())
    has_key = bool(keys) and all(row.get(key) is not None for key in keys)

    if has_key:
        changes = {key: value for key, value in row.items() if key not in keys}
        if changes:
            assignments = ", ".join(f'"{column}" = ?' for column in changes)
            where = " AND ".join(f'"{key}" = ?' for key in keys)
            values = [encode(value, column) for column, value in changes.items()]
            values.extend(row[key] for key in keys)
            try:
                cursor = conn.execute(f'UPDATE "{table}" SET {assignments} WHERE {where}', values)
            except sqlite3.IntegrityError as exc:
                raise ConflictError("C-01-01", f"数据写入冲突：{exc}") from exc
            if cursor.rowcount > 0:
                return row

    columns = list(row.keys())
    placeholders = ", ".join("?" for _ in columns)
    quoted = ", ".join(f'"{column}"' for column in columns)
    values = [encode(row[column], column) for column in columns]
    try:
        conn.execute(f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})', values)
    except sqlite3.IntegrityError as exc:
        raise ConflictError("C-01-01", f"数据写入失败，缺少必要字段或违反了唯一约束：{exc}") from exc
    return row


def insert_returning_id(conn: sqlite3.Connection, table: str, payload: dict) -> int:
    row = filter_columns(table, payload)
    columns = list(row.keys())
    placeholders = ", ".join("?" for _ in columns)
    quoted = ", ".join(f'"{column}"' for column in columns)
    values = [encode(row[column], column) for column in columns]
    try:
        cursor = conn.execute(f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})', values)
    except sqlite3.IntegrityError as exc:
        raise ConflictError("C-01-01", f"数据写入冲突：{exc}") from exc
    return int(cursor.lastrowid)


def update(conn: sqlite3.Connection, table: str, key_column: str, key_value: Any, payload: dict) -> None:
    row = filter_columns(table, payload)
    row.pop(key_column, None)
    if not row:
        return
    assignments = ", ".join(f'"{column}" = ?' for column in row)
    values = [encode(value, column) for column, value in row.items()]
    cursor = conn.execute(f'UPDATE "{table}" SET {assignments} WHERE "{key_column}" = ?',
                          [*values, key_value])
    if cursor.rowcount == 0:
        raise NotFoundError("C-02-02", "要修改的记录不存在", field=key_column)


def delete(conn: sqlite3.Connection, table: str, key_column: str, key_value: Any) -> None:
    if table not in WRITABLE_COLUMNS:
        raise ValueError(f"表 {table} 不在可写白名单内")
    if key_column not in WRITABLE_COLUMNS[table]:
        raise ValueError(f"字段 {key_column} 不允许作为删除条件")
    cursor = conn.execute(f'DELETE FROM "{table}" WHERE "{key_column}" = ?', (key_value,))
    if cursor.rowcount == 0:
        raise NotFoundError("C-02-02", "要删除的记录不存在", field=key_column)


def record_change(conn: sqlite3.Connection, table: str, record_key: str, action: str) -> None:
    """留痕。只记录表名与主键，不记录内容。"""
    conn.execute(
        "INSERT INTO change_log (table_name, record_key, action, changed_at) "
        "VALUES (?, ?, ?, datetime('now'))",
        (table, str(record_key), action),
    )
