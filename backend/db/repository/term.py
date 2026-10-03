"""术语与语料的数据访问，含增删改查。"""

from __future__ import annotations

import sqlite3

from ...common.errors import NotFoundError
from . import base

TERM_COLUMNS = ("term_code", "name", "layer1", "layer2", "layer3_template", "enabled", "sort_order")
DOC_COLUMNS = ("doc_code", "doc_type", "title", "source_url", "fetched_at", "content")


def list_terms(conn: sqlite3.Connection, only_enabled: bool = True) -> list[dict]:
    where = "WHERE enabled = 1" if only_enabled else ""
    rows = conn.execute(
        f"SELECT {', '.join(TERM_COLUMNS)} FROM terms {where} ORDER BY sort_order, term_code").fetchall()
    return [dict(row) for row in rows]


def aliases(conn: sqlite3.Connection, term_code: str) -> list[str]:
    rows = conn.execute(
        "SELECT alias FROM term_aliases WHERE term_code = ? ORDER BY alias", (term_code,)).fetchall()
    return [row["alias"] for row in rows]


def sources(conn: sqlite3.Connection, term_code: str) -> list[dict]:
    rows = conn.execute(
        "SELECT d.doc_code, d.doc_type, d.title, d.source_url, d.fetched_at "
        "FROM term_sources s JOIN corpus_documents d ON d.doc_code = s.doc_code "
        "WHERE s.term_code = ? ORDER BY s.sort_order", (term_code,)).fetchall()
    return [dict(row) for row in rows]


def source_documents(conn: sqlite3.Connection, term_code: str) -> list[dict]:
    """关联语料的完整内容，供智能体提取摘录使用。列表接口不使用它。"""
    columns = ", ".join(f"d.{column}" for column in DOC_COLUMNS)
    rows = conn.execute(
        f"SELECT {columns} FROM term_sources s "  # noqa: S608  列名来自模块级白名单
        "JOIN corpus_documents d ON d.doc_code = s.doc_code "
        "WHERE s.term_code = ? ORDER BY s.sort_order", (term_code,)).fetchall()
    return [dict(row) for row in rows]


def get_term(conn: sqlite3.Connection, term_code: str) -> dict | None:
    row = conn.execute(
        f"SELECT {', '.join(TERM_COLUMNS)} FROM terms WHERE term_code = ?", (term_code,)).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["aliases"] = aliases(conn, term_code)
    data["sources"] = sources(conn, term_code)
    return data


def find_by_name_or_alias(conn: sqlite3.Connection, query: str) -> dict | None:
    """先按编码、名称与别名精确匹配，再做包含匹配。匹配逻辑放在数据访问层，避免业务层散落 SQL。

    界面上可点开的词带的是词条编码，检索入口里出现的是名称或别名，
    三种写法都要命中，否则同一个词在一个入口能查到、在另一个入口查不到。
    """
    query = (query or "").strip()
    if not query:
        return None

    row = conn.execute(
        "SELECT term_code FROM terms WHERE enabled = 1 AND term_code = ?", (query,)).fetchone()
    if row:
        return get_term(conn, row["term_code"])

    row = conn.execute(
        "SELECT term_code FROM terms WHERE enabled = 1 AND name = ?", (query,)).fetchone()
    if row:
        return get_term(conn, row["term_code"])

    row = conn.execute(
        "SELECT t.term_code FROM term_aliases a JOIN terms t ON t.term_code = a.term_code "
        "WHERE t.enabled = 1 AND a.alias = ?", (query,)).fetchone()
    if row:
        return get_term(conn, row["term_code"])

    row = conn.execute(
        "SELECT t.term_code FROM terms t LEFT JOIN term_aliases a ON a.term_code = t.term_code "
        "WHERE t.enabled = 1 AND (t.name LIKE ? OR a.alias LIKE ?) "
        "ORDER BY t.sort_order LIMIT 1",
        (f"%{query}%", f"%{query}%")).fetchone()
    if row:
        return get_term(conn, row["term_code"])
    return None


def _replace_children(conn: sqlite3.Connection, term_code: str,
                      alias_list: list[str] | None, source_list: list[str] | None) -> None:
    if alias_list is not None:
        conn.execute("DELETE FROM term_aliases WHERE term_code = ?", (term_code,))
        for alias in alias_list:
            value = str(alias).strip()
            if value:
                conn.execute("INSERT OR IGNORE INTO term_aliases (term_code, alias) VALUES (?, ?)",
                             (term_code, value))
    if source_list is not None:
        conn.execute("DELETE FROM term_sources WHERE term_code = ?", (term_code,))
        for index, doc_code in enumerate(source_list):
            conn.execute(
                "INSERT OR IGNORE INTO term_sources (term_code, doc_code, sort_order) VALUES (?, ?, ?)",
                (term_code, doc_code, index * 10))


def create_term(conn: sqlite3.Connection, payload: dict) -> dict:
    term_code = payload["term_code"]
    row = {key: payload[key] for key in TERM_COLUMNS if payload.get(key) is not None}
    row.setdefault("enabled", 1)
    row.setdefault("sort_order", 0)
    base.upsert(conn, "terms", row)
    _replace_children(conn, term_code, payload.get("aliases"), payload.get("sources"))
    base.record_change(conn, "terms", term_code, "create")
    return get_term(conn, term_code)


def update_term(conn: sqlite3.Connection, term_code: str, payload: dict) -> dict:
    if get_term(conn, term_code) is None:
        raise NotFoundError("C-02-02", "指定的术语不存在", field="term_code")
    changes = {key: payload[key] for key in TERM_COLUMNS if key in payload}
    if changes:
        base.update(conn, "terms", "term_code", term_code, changes)
    _replace_children(conn, term_code, payload.get("aliases"), payload.get("sources"))
    base.record_change(conn, "terms", term_code, "update")
    return get_term(conn, term_code)


def delete_term(conn: sqlite3.Connection, term_code: str) -> None:
    base.delete(conn, "terms", "term_code", term_code)
    base.record_change(conn, "terms", term_code, "delete")


# ---------------------------------------------------------------- 语料


def list_documents(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        f"SELECT {', '.join(DOC_COLUMNS)} FROM corpus_documents ORDER BY doc_code").fetchall()
    return [dict(row) for row in rows]


def get_document(conn: sqlite3.Connection, doc_code: str) -> dict | None:
    row = conn.execute(
        f"SELECT {', '.join(DOC_COLUMNS)} FROM corpus_documents WHERE doc_code = ?",
        (doc_code,)).fetchone()
    return None if row is None else dict(row)


def create_document(conn: sqlite3.Connection, payload: dict) -> dict:
    row = {key: payload[key] for key in DOC_COLUMNS if payload.get(key) is not None}
    base.upsert(conn, "corpus_documents", row)
    base.record_change(conn, "corpus_documents", row["doc_code"], "create")
    return get_document(conn, row["doc_code"])


def update_document(conn: sqlite3.Connection, doc_code: str, payload: dict) -> dict:
    if get_document(conn, doc_code) is None:
        raise NotFoundError("C-02-02", "指定的语料文档不存在", field="doc_code")
    changes = {key: payload[key] for key in DOC_COLUMNS if key in payload}
    if changes:
        base.update(conn, "corpus_documents", "doc_code", doc_code, changes)
    base.record_change(conn, "corpus_documents", doc_code, "update")
    return get_document(conn, doc_code)


def delete_document(conn: sqlite3.Connection, doc_code: str) -> None:
    base.delete(conn, "corpus_documents", "doc_code", doc_code)
    base.record_change(conn, "corpus_documents", doc_code, "delete")
