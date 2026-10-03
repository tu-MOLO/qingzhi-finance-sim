"""智能体注册表：把数据库中的智能体定义、工具与绑定关系读出来。

定义全部入库，新增一个智能体或调整它可用的工具只需要改数据。
代码里只保留工具的处理器与本地渲染器，工具编码与处理器名不一致时会在运行期被发现。
"""

from __future__ import annotations

import json
import sqlite3

from ..db import connection
from .tools import available_tools

AGENT_COLUMNS = ("code", "name", "category", "description", "objective", "system_prompt",
                 "output_schema", "provider", "timeout_seconds", "sort_order")


def _decode_agent(row: dict) -> dict:
    schema = row.get("output_schema")
    if isinstance(schema, str):
        try:
            row["output_schema"] = json.loads(schema)
        except json.JSONDecodeError:
            row["output_schema"] = {}
    return row


def list_agents(conn: sqlite3.Connection, only_enabled: bool = True) -> list[dict]:
    sql = "SELECT * FROM agents"
    if only_enabled:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY sort_order, code"
    return [_decode_agent(row) for row in connection.rows_to_dicts(connection.query(conn, sql))]


def get_agent(conn: sqlite3.Connection, code: str) -> dict | None:
    row = connection.query_one(conn, "SELECT * FROM agents WHERE code = ?", (code,))
    return None if row is None else _decode_agent(connection.row_to_dict(row))


def list_tools(conn: sqlite3.Connection) -> list[dict]:
    rows = connection.query(
        conn, "SELECT * FROM agent_tools WHERE enabled = 1 ORDER BY sort_order, code")
    return connection.rows_to_dicts(rows)


def bound_tools(conn: sqlite3.Connection, agent_code: str) -> list[dict]:
    """取某个智能体绑定的工具，带绑定顺序与是否必需。"""
    rows = connection.query(conn, """
        SELECT t.code, t.name, t.kind, t.description, t.handler,
               b.required AS required, b.sort_order AS bind_order
        FROM agent_bindings AS b
        JOIN agent_tools AS t ON t.code = b.tool_code
        WHERE b.agent_code = ? AND t.enabled = 1
        ORDER BY b.sort_order, t.code
    """, (agent_code,))
    return connection.rows_to_dicts(rows)


def detail_of(conn: sqlite3.Connection, code: str) -> dict | None:
    """智能体定义连同它绑定的工具，供接口直接返回。"""
    agent = get_agent(conn, code)
    if agent is None:
        return None
    agent["tools"] = bound_tools(conn, code)
    return agent


def problems(conn: sqlite3.Connection) -> list[str]:
    """检出声明了但代码中没有实现的工具处理器。供自查与测试使用。"""
    known = available_tools()
    issues: list[str] = []
    for tool in list_tools(conn):
        if tool["handler"] not in known:
            issues.append(f"工具 {tool['code']} 声明的处理器 {tool['handler']} 未实现")
    rows = connection.query(conn, """
        SELECT DISTINCT a.code AS agent_code, a.enabled AS enabled
        FROM agents AS a
        LEFT JOIN agent_bindings AS b ON b.agent_code = a.code
        WHERE a.enabled = 1 AND b.id IS NULL
    """)
    for row in connection.rows_to_dicts(rows):
        issues.append(f"智能体 {row['agent_code']} 没有绑定任何工具")
    return issues


def payload(conn: sqlite3.Connection) -> dict:
    """接口用的智能体目录。"""
    agents = []
    for agent in list_agents(conn):
        agent["tools"] = bound_tools(conn, agent["code"])
        agents.append(agent)
    return {"agents": agents, "tools": list_tools(conn)}
