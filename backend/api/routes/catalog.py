"""配置目录接口：字典、配置项、账户、分级、界面文案、提示文案、模型参数与数据来源。

读取集中在 /catalog，供前端一次性取齐；写入按资源分别提供增删改。
任何写入都会让配置缓存失效，下一次读取时重建。
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ... import config as C
from ...common.errors import AppError, NotFoundError, ValidationError
from ...db import connection
from ...db.repository import base as repo_base
from ...db.repository import configuration as config_repo
from ...services.configuration import catalog_payload, get_catalog, invalidate, parameters_payload
from ..security import body

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------------- 读取


@bp.get("/catalog")
def read_catalog():
    """一次返回前端启动所需的全部枚举、文案与配置。"""
    return jsonify({"ok": True, "data": catalog_payload()})


@bp.get("/catalog/dictionaries")
def read_dictionaries():
    with connection.session() as conn:
        data = config_repo.dictionaries(conn)
    return jsonify({"ok": True, "data": data})


@bp.get("/catalog/dictionary-types")
def read_dictionary_types():
    with connection.session() as conn:
        rows = config_repo.list_dict_types(conn)
    return jsonify({"ok": True, "data": {"types": rows}})


@bp.get("/catalog/settings")
def read_settings():
    with connection.session() as conn:
        rows = config_repo.settings_rows(conn)
    return jsonify({"ok": True, "data": {"settings": rows}})


@bp.get("/catalog/accounts")
def read_accounts():
    with connection.session() as conn:
        rows = config_repo.accounts(conn)
    return jsonify({"ok": True, "data": {"accounts": rows}})


@bp.get("/catalog/risk-levels")
def read_risk_levels():
    with connection.session() as conn:
        rows = config_repo.risk_levels(conn)
    return jsonify({"ok": True, "data": {"riskLevels": rows}})


@bp.get("/catalog/ui-texts")
def read_ui_texts():
    with connection.session() as conn:
        rows = config_repo.ui_text_rows(conn)
    return jsonify({"ok": True, "data": {"uiTexts": rows}})


@bp.get("/catalog/messages")
def read_messages():
    with connection.session() as conn:
        rows = config_repo.message_rows(conn)
    return jsonify({"ok": True, "data": {"messages": rows}})


@bp.get("/catalog/parameters")
def read_parameters():
    return jsonify({"ok": True, "data": parameters_payload(get_catalog())})


# ---------------------------------------------------------------- 写入

_WRITABLE = {
    "ui-texts": ("ui_texts", "key"),
    "messages": ("messages", "code"),
    "settings": ("app_settings", "key"),
    "dictionary-items": ("dict_items", "code"),
    "parameters": ("model_params", "key"),
    "data-sources": ("data_sources", "id"),
    "accounts": ("accounts", "code"),
    "risk-levels": ("risk_levels", "code"),
}


def _resolve(resource: str) -> tuple[str, str]:
    target = _WRITABLE.get(resource)
    if target is None:
        raise AppError("C-01-02", f"不支持的资源类型：{resource}", http_status=404)
    return target


def _guard_payload(payload: dict) -> dict:
    for key, value in payload.items():
        if isinstance(value, str) and len(value) > C.MAX_TEXT_LENGTH * 64:
            raise ValidationError(key, f"字段 {key} 的内容过长", code="C-01-01")
    return payload


@bp.put("/catalog/<resource>")
def upsert_resource(resource: str):
    table, key_column = _resolve(resource)
    payload = _guard_payload(body())
    if not payload.get(key_column):
        raise ValidationError(key_column, f"字段 {key_column} 不能为空", code="C-01-01")
    with connection.session() as conn:
        repo_base.upsert(conn, table, payload)
        repo_base.record_change(conn, table, payload[key_column], "upsert")
    invalidate()
    return jsonify({"ok": True, "data": {"table": table, "key": payload[key_column]}})


@bp.delete("/catalog/<resource>/<path:key>")
def delete_resource(resource: str, key: str):
    table, key_column = _resolve(resource)
    if table not in ("ui_texts", "messages", "dict_items", "app_settings"):
        raise AppError("C-01-02", "该资源不支持删除", http_status=400)
    value: object = key
    if key_column == "id":
        value = int(key)
    with connection.session() as conn:
        repo_base.delete(conn, table, key_column, value)
        repo_base.record_change(conn, table, key, "delete")
    invalidate()
    return jsonify({"ok": True, "data": {"table": table, "key": key}})


@bp.get("/catalog/change-log")
def read_change_log():
    limit = request.args.get("limit", "50")
    try:
        size = max(1, min(500, int(limit)))
    except ValueError:
        size = 50
    with connection.session() as conn:
        rows = config_repo.change_log(conn, size)
    return jsonify({"ok": True, "data": {"entries": rows}})


@bp.get("/catalog/dictionary-items/<type_code>")
def read_dictionary_items(type_code: str):
    with connection.session() as conn:
        rows = config_repo.list_dict_items(conn, type_code, only_enabled=False)
    if not rows:
        raise NotFoundError("C-02-03", "该字典类型不存在或没有条目", field="type_code")
    return jsonify({"ok": True, "data": {"type": type_code, "items": rows}})
