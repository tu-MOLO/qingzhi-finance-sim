"""典型画像接口：增删改查，以及加载到录入界面所需的画像结构。"""

from __future__ import annotations

from flask import Blueprint, jsonify

from ...db import connection
from ...services import archetype as service
from ...services.configuration import get_catalog
from ..security import body, sanitize_text

bp = Blueprint("archetype", __name__)


@bp.get("/archetypes")
def list_archetypes():
    with connection.session() as conn:
        rows = service.list_archetypes(conn, only_enabled=False)
    return jsonify({"ok": True, "data": {"archetypes": rows}})


@bp.get("/archetypes/<archetype_id>")
def get_archetype(archetype_id: str):
    with connection.session() as conn:
        item = service.get_archetype(conn, archetype_id)
    return jsonify({"ok": True, "data": item})


@bp.get("/archetypes/<archetype_id>/profile")
def get_archetype_profile(archetype_id: str):
    """返回可直接提交给推演接口的画像结构。"""
    with connection.session() as conn:
        item = service.profile_of(conn, archetype_id)
    return jsonify({"ok": True, "data": {"profile": item}})


@bp.post("/archetypes")
def create_archetype():
    payload = body()
    payload["archetype_id"] = sanitize_text(payload.get("archetype_id"), "archetype_id", required=True)
    payload["name"] = sanitize_text(payload.get("name"), "name", required=True)
    payload.pop("city", None)
    with connection.session() as conn:
        item = service.create(conn, payload, get_catalog())
    return jsonify({"ok": True, "data": item}), 201


@bp.put("/archetypes/<archetype_id>")
def update_archetype(archetype_id: str):
    payload = body()
    if "name" in payload:
        payload["name"] = sanitize_text(payload.get("name"), "name", required=True)
    payload.pop("city", None)
    with connection.session() as conn:
        item = service.update(conn, archetype_id, payload, get_catalog())
    return jsonify({"ok": True, "data": item})


@bp.delete("/archetypes/<archetype_id>")
def delete_archetype(archetype_id: str):
    with connection.session() as conn:
        service.remove(conn, archetype_id)
    return jsonify({"ok": True, "data": {"archetypeId": archetype_id}})
