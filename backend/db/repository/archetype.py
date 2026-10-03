"""典型画像的数据访问，含增删改查。

画像由三张表组成：主体、收入来源、人生目标。写入时在同一事务内完成。
"""

from __future__ import annotations

import sqlite3

from ...common.errors import NotFoundError
from . import base

MAIN_COLUMNS = ("archetype_id", "kind", "name", "summary", "highlights", "city", "grade",
                "living_cost", "living_growth", "initial_balance", "risk_appetite",
                "months", "paths", "seed", "growth_budget", "treat_budget",
                "enabled", "sort_order")

SOURCE_COLUMNS = ("source_type", "enabled", "probability", "amount_low", "amount_mid",
                  "amount_high", "start_month", "end_month", "interrupt_prob")

GOAL_COLUMNS = ("goal_id", "name", "amount", "due_month", "priority")

EXPENSE_COLUMNS = ("category", "amount", "essential", "growth_rate", "enabled")


def list_archetypes(conn: sqlite3.Connection, only_enabled: bool = True) -> list[dict]:
    where = "WHERE enabled = 1" if only_enabled else ""
    rows = conn.execute(
        f"SELECT {', '.join(MAIN_COLUMNS)} FROM archetypes {where} ORDER BY sort_order, archetype_id"
    ).fetchall()
    return base.decode_all(rows)


def income_sources(conn: sqlite3.Connection, archetype_id: str) -> list[dict]:
    rows = conn.execute(
        f"SELECT {', '.join(SOURCE_COLUMNS)} FROM archetype_income_sources "
        f"WHERE archetype_id = ? ORDER BY id", (archetype_id,)).fetchall()
    return [dict(row) for row in rows]


def goals(conn: sqlite3.Connection, archetype_id: str) -> list[dict]:
    rows = conn.execute(
        f"SELECT {', '.join(GOAL_COLUMNS)} FROM archetype_goals "
        f"WHERE archetype_id = ? ORDER BY priority, id", (archetype_id,)).fetchall()
    return [dict(row) for row in rows]


def expenses(conn: sqlite3.Connection, archetype_id: str) -> list[dict]:
    rows = conn.execute(
        f"SELECT {', '.join(EXPENSE_COLUMNS)} FROM archetype_expenses "
        "WHERE archetype_id = ? ORDER BY id", (archetype_id,)).fetchall()
    return [dict(row) for row in rows]


def get_archetype(conn: sqlite3.Connection, archetype_id: str) -> dict | None:
    row = conn.execute(
        f"SELECT {', '.join(MAIN_COLUMNS)} FROM archetypes WHERE archetype_id = ?",
        (archetype_id,)).fetchone()
    if row is None:
        return None
    data = base.decode(row)
    data["income_sources"] = income_sources(conn, archetype_id)
    data["goals"] = goals(conn, archetype_id)
    data["expenses"] = expenses(conn, archetype_id)
    return data


def to_profile(archetype: dict) -> dict:
    """转换为推演使用的画像结构。

    内置财务画像不绑定年级，grade 留空；用户档案保存时记录了年级，
    这里一并带出，供前端恢复用户保存时的状态。
    """
    grade = archetype.get("grade") or None
    return {
        "profile_id": archetype["archetype_id"],
        "name": archetype["name"],
        "grade": grade,
        "living_cost": archetype["living_cost"],
        "living_growth": archetype["living_growth"],
        "initial_balance": archetype.get("initial_balance", 0.0),
        "risk_appetite": archetype["risk_appetite"],
        "months": archetype["months"],
        "paths": archetype["paths"],
        "seed": archetype["seed"],
        "income_sources": archetype["income_sources"],
        "goals": archetype["goals"],
        "expenses": archetype["expenses"],
        "budget": {
            "growth_monthly": archetype.get("growth_budget", 0.0),
            "treat_monthly": archetype.get("treat_budget", 0.0),
        },
    }


def _replace_children(conn: sqlite3.Connection, archetype_id: str,
                      sources: list[dict] | None, goal_rows: list[dict] | None,
                      expense_rows: list[dict] | None = None) -> None:
    """子表整体替换，保证与主体一致。"""
    if sources is not None:
        conn.execute("DELETE FROM archetype_income_sources WHERE archetype_id = ?", (archetype_id,))
        for source in sources:
            payload = {key: source.get(key) for key in SOURCE_COLUMNS}
            payload["archetype_id"] = archetype_id
            base.upsert(conn, "archetype_income_sources", payload)
    if goal_rows is not None:
        conn.execute("DELETE FROM archetype_goals WHERE archetype_id = ?", (archetype_id,))
        for goal in goal_rows:
            payload = {key: goal.get(key) for key in GOAL_COLUMNS}
            payload["archetype_id"] = archetype_id
            conn.execute(
                "INSERT INTO archetype_goals (archetype_id, goal_id, name, amount, due_month, priority) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (archetype_id, payload["goal_id"], payload["name"], payload["amount"],
                 payload["due_month"], payload["priority"]))

    if expense_rows is not None:
        conn.execute("DELETE FROM archetype_expenses WHERE archetype_id = ?", (archetype_id,))
        for expense in expense_rows:
            conn.execute(
                "INSERT INTO archetype_expenses (archetype_id, category, amount, essential, "
                "growth_rate, enabled) VALUES (?, ?, ?, ?, ?, ?)",
                (archetype_id, expense.get("category"), expense.get("amount", 0),
                 1 if expense.get("essential") else 0, expense.get("growth_rate", 0),
                 1 if expense.get("enabled", True) else 0))


def _main_row(payload: dict) -> dict:
    """只保留有值的字段，并为非空列补默认值。"""
    row = {key: payload[key] for key in MAIN_COLUMNS if payload.get(key) is not None}
    row.setdefault("kind", "user")
    row.setdefault("grade", "")
    row.setdefault("initial_balance", 0.0)
    row.setdefault("growth_budget", 0.0)
    row.setdefault("treat_budget", 0.0)
    row.setdefault("enabled", 1)
    row.setdefault("sort_order", 0)
    # city 列随城市变量一并移除，仅为兼容旧库结构保留，写入时统一补空串
    row.setdefault("city", "")
    return row


def create_archetype(conn: sqlite3.Connection, payload: dict) -> dict:
    archetype_id = payload["archetype_id"]
    row = _main_row(payload)
    base.upsert(conn, "archetypes", row)
    _replace_children(conn, archetype_id, payload.get("income_sources"),
                      payload.get("goals"), payload.get("expenses"))
    base.record_change(conn, "archetypes", archetype_id, "create")
    return get_archetype(conn, archetype_id)


def update_archetype(conn: sqlite3.Connection, archetype_id: str, payload: dict) -> dict:
    if get_archetype(conn, archetype_id) is None:
        raise NotFoundError("C-02-02", "指定的画像不存在", field="archetype_id")
    changes = {key: payload[key] for key in MAIN_COLUMNS if key in payload}
    if changes:
        base.update(conn, "archetypes", "archetype_id", archetype_id, changes)
    _replace_children(conn, archetype_id, payload.get("income_sources"),
                      payload.get("goals"), payload.get("expenses"))
    base.record_change(conn, "archetypes", archetype_id, "update")
    return get_archetype(conn, archetype_id)


def delete_archetype(conn: sqlite3.Connection, archetype_id: str) -> None:
    base.delete(conn, "archetypes", "archetype_id", archetype_id)
    base.record_change(conn, "archetypes", archetype_id, "delete")
