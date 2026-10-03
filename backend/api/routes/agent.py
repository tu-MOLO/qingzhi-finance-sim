"""智能体接口：目录、定义与调用。

调用接口是智能体能力的唯一入口。术语解释接口内部同样走这条链路，
因此两条路径共用同一套工具、生成器与合规校验。
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from ...agents import registry
from ...common.errors import AppError
from ...db import connection
from ...services import agent as service
from ...services.configuration import get_catalog
from ..security import body, sanitize_text

bp = Blueprint("agent", __name__)


@bp.get("/agents")
def list_agents():
    with connection.session() as conn:
        payload = service.catalogue(conn)
    return jsonify({"ok": True, "data": payload})


@bp.get("/agents/<agent_code>")
def get_agent(agent_code: str):
    with connection.session() as conn:
        item = service.detail(conn, agent_code)
    return jsonify({"ok": True, "data": item})


@bp.get("/agent-tools")
def list_tools():
    with connection.session() as conn:
        rows = registry.list_tools(conn)
    return jsonify({"ok": True, "data": {"tools": rows}})


@bp.post("/agents/<agent_code>/run")
def run_agent(agent_code: str):
    payload = body()
    term = payload.get("term")
    if term is not None and not isinstance(term, str):
        raise AppError("E-02-03", "字段 term 必须是文本", field="term", http_status=400)
    snapshot = payload.get("snapshot")
    if snapshot is not None and not isinstance(snapshot, dict):
        raise AppError("E-02-03", "字段 snapshot 必须是 JSON 对象", field="snapshot",
                       http_status=400)

    code = sanitize_text(agent_code, "agent_code", required=True)
    catalog = get_catalog()
    with connection.session() as conn:
        result = service.invoke(conn, code, {"term": term, "snapshot": snapshot}, catalog)
    return jsonify({"ok": True, "data": result})
