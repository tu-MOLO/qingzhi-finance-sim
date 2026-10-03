"""术语与语料接口：检索、三层解释、增删改查。"""

from __future__ import annotations

from flask import Blueprint, jsonify

from ...common.errors import AppError
from ...db import connection
from ...services import term as service
from ...services.configuration import get_catalog
from ..security import body, sanitize_text

bp = Blueprint("term", __name__)


# ---------------------------------------------------------------- 读取与解释


@bp.get("/terms")
def list_terms():
    with connection.session() as conn:
        rows = service.list_terms(conn, only_enabled=False)
    return jsonify({"ok": True, "data": {"terms": rows}})


@bp.get("/terms/<term_code>")
def get_term(term_code: str):
    from ...db.repository import term as repo
    with connection.session() as conn:
        item = repo.get_term(conn, term_code)
    if item is None:
        raise AppError("E-02-01", "指定的术语不存在", field="term_code", http_status=404)
    return jsonify({"ok": True, "data": item})


@bp.get("/corpus-documents")
def list_documents():
    with connection.session() as conn:
        rows = service.documents(conn)
    return jsonify({"ok": True, "data": {"documents": rows}})


@bp.post("/terms/explain")
def explain():
    payload = body()
    term = payload.get("term")
    if not isinstance(term, str) or not term.strip():
        raise AppError("E-02-03", "字段 term 不能为空", field="term", http_status=400)
    snapshot = payload.get("snapshot")
    if snapshot is not None and not isinstance(snapshot, dict):
        raise AppError("E-02-03", "字段 snapshot 必须是 JSON 对象", field="snapshot", http_status=400)
    catalog = get_catalog()
    with connection.session() as conn:
        result = service.explain(conn, term.strip()[:64], snapshot, catalog)
    return jsonify({"ok": True, "data": result})


# ---------------------------------------------------------------- 写入


@bp.post("/terms")
def create_term():
    payload = body()
    payload["term_code"] = sanitize_text(payload.get("term_code"), "term_code", required=True)
    with connection.session() as conn:
        item = service.create(conn, payload)
    return jsonify({"ok": True, "data": item}), 201


@bp.put("/terms/<term_code>")
def update_term(term_code: str):
    with connection.session() as conn:
        item = service.update(conn, term_code, body())
    return jsonify({"ok": True, "data": item})


@bp.delete("/terms/<term_code>")
def delete_term(term_code: str):
    with connection.session() as conn:
        service.remove(conn, term_code)
    return jsonify({"ok": True, "data": {"termCode": term_code}})


@bp.post("/corpus-documents")
def create_document():
    payload = body()
    payload["doc_code"] = sanitize_text(payload.get("doc_code"), "doc_code", required=True)
    with connection.session() as conn:
        item = service.create_document(conn, payload)
    return jsonify({"ok": True, "data": item}), 201


@bp.put("/corpus-documents/<doc_code>")
def update_document(doc_code: str):
    with connection.session() as conn:
        item = service.update_document(conn, doc_code, body())
    return jsonify({"ok": True, "data": item})


@bp.delete("/corpus-documents/<doc_code>")
def delete_document(doc_code: str):
    with connection.session() as conn:
        service.remove_document(conn, doc_code)
    return jsonify({"ok": True, "data": {"docCode": doc_code}})
