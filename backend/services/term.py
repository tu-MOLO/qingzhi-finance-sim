"""术语用例：检索、三层解释与增删改查。

三层解释不再在本模块内拼装，而是委托给术语解释智能体。
这样术语接口与智能体接口走的是同一条链路——同一套工具、同一个生成器、
同一道合规校验，两条入口的结果不会出现分歧。
"""

from __future__ import annotations

import sqlite3

from ..common.errors import ExplainError, NotFoundError, ValidationError
from ..db.repository import term as term_repo
from . import agent as agent_service
from .configuration import Catalog


def list_terms(conn: sqlite3.Connection, only_enabled: bool = True) -> list[dict]:
    rows = term_repo.list_terms(conn, only_enabled=only_enabled)
    for row in rows:
        row["aliases"] = term_repo.aliases(conn, row["term_code"])
    return rows


def documents(conn: sqlite3.Connection) -> list[dict]:
    return term_repo.list_documents(conn)


def explain(conn: sqlite3.Connection, query: str, snapshot: dict | None,
            catalog: Catalog) -> dict:
    """三层解释。委托给术语解释智能体，并整理成术语接口对外的形状。"""
    term = term_repo.find_by_name_or_alias(conn, query)
    if term is None:
        raise ExplainError("E-02-01", "暂时没有收录这个说法，可以换一个词试试", http_status=404)

    result = agent_service.invoke(
        conn, "term_explain", {"term": query, "snapshot": snapshot}, catalog)
    output = result["output"]
    return {
        "termCode": term["term_code"],
        "term": term["name"],
        "layer1": output.get("layer1", ""),
        "layer2": output.get("layer2", ""),
        "layer3": output.get("layer3", ""),
        "linkedGoalId": output.get("linkedGoalId"),
        "linkedGoalName": output.get("linkedGoalName"),
        # 术语第三层以首要目标落数，其余目标一并纳入，界面要能交代清楚不是一个人在算
        "linkedGoalIds": output.get("linkedGoalIds") or [],
        "hasNumbers": bool(output.get("hasNumbers")),
        "generatedBy": result["provider"],
        "degraded": result["degraded"],
        "sources": output.get("sources", []),
        "disclaimer": result["disclaimer"]["body"],
        "disclaimerTitle": result["disclaimer"]["title"],
        "agent": result["agent"],
        "steps": result["steps"],
        "elapsedMs": result["elapsedMs"],
    }


def create(conn: sqlite3.Connection, payload: dict) -> dict:
    _require(payload, ("term_code", "name", "layer1", "layer2", "layer3_template"))
    if term_repo.get_term(conn, payload["term_code"]):
        raise ValidationError("term_code", "该术语编码已存在", code="C-01-01")
    return term_repo.create_term(conn, payload)


def update(conn: sqlite3.Connection, term_code: str, payload: dict) -> dict:
    if term_repo.get_term(conn, term_code) is None:
        raise NotFoundError("C-02-02", "指定的术语不存在", field="term_code")
    return term_repo.update_term(conn, term_code, payload)


def remove(conn: sqlite3.Connection, term_code: str) -> None:
    if term_repo.get_term(conn, term_code) is None:
        raise NotFoundError("C-02-02", "指定的术语不存在", field="term_code")
    term_repo.delete_term(conn, term_code)


def create_document(conn: sqlite3.Connection, payload: dict) -> dict:
    _require(payload, ("doc_code", "doc_type", "title"))
    if term_repo.get_document(conn, payload["doc_code"]):
        raise ValidationError("doc_code", "该语料编码已存在", code="C-01-01")
    return term_repo.create_document(conn, payload)


def update_document(conn: sqlite3.Connection, doc_code: str, payload: dict) -> dict:
    if term_repo.get_document(conn, doc_code) is None:
        raise NotFoundError("C-02-02", "指定的语料文档不存在", field="doc_code")
    return term_repo.update_document(conn, doc_code, payload)


def remove_document(conn: sqlite3.Connection, doc_code: str) -> None:
    if term_repo.get_document(conn, doc_code) is None:
        raise NotFoundError("C-02-02", "指定的语料文档不存在", field="doc_code")
    term_repo.delete_document(conn, doc_code)


def _require(payload: dict, keys: tuple[str, ...]) -> None:
    for key in keys:
        if not payload.get(key):
            raise ValidationError(key, f"字段 {key} 不能为空", code="C-01-01")
