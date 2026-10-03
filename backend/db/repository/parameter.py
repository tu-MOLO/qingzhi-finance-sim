"""模型参数与数据来源的数据访问。"""

from __future__ import annotations

import sqlite3

from . import base


def list_params(conn: sqlite3.Connection, only_enabled: bool = True) -> list[dict]:
    where = "WHERE enabled = 1" if only_enabled else ""
    rows = conn.execute(
        f"SELECT id, seq, key, name, value_base, value_low, value_high, unit, source, "
        f"period, property, note, enabled FROM model_params {where} ORDER BY seq").fetchall()
    return base.decode_all(rows)


def param_values(conn: sqlite3.Connection) -> dict[str, float]:
    """按键取出基准取值，供领域层注入。只返回已启用且键不为空的参数。"""
    values: dict[str, float] = {}
    for row in list_params(conn):
        if not row["key"] or row["value_base"] is None:
            continue
        values[row["key"]] = float(row["value_base"])
    return values


def get_param(conn: sqlite3.Connection, key: str) -> dict | None:
    row = conn.execute("SELECT * FROM model_params WHERE key = ?", (key,)).fetchone()
    return base.decode(row)


def list_sources(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, seq, name, period, supports, url FROM data_sources ORDER BY seq").fetchall()
    return base.decode_all(rows)
