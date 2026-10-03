"""典型画像用例：增删改查。写入前复用画像校验规则。"""

from __future__ import annotations

import sqlite3

from ..common.errors import NotFoundError, ValidationError
from ..db.repository import archetype as repo
from . import profile as profile_service
from .configuration import Catalog, invalidate


def _validate(payload: dict, catalog: Catalog) -> None:
    """把画像记录转成推演使用的结构后套用同一套校验规则。"""
    probe = {
        "profile_id": payload.get("archetype_id"),
        "name": payload.get("name"),
        "grade": payload.get("grade"),
        "living_cost": payload.get("living_cost"),
        "living_growth": payload.get("living_growth"),
        "initial_balance": payload.get("initial_balance"),
        "risk_appetite": payload.get("risk_appetite"),
        "months": payload.get("months"),
        "paths": payload.get("paths"),
        "seed": payload.get("seed"),
        "income_sources": payload.get("income_sources") or [],
        "goals": payload.get("goals") or [],
        "budget": {
            "growth_monthly": payload.get("growth_budget"),
            "treat_monthly": payload.get("treat_budget"),
        },
    }
    profile_service.normalize_and_validate(probe, catalog)


def list_archetypes(conn: sqlite3.Connection, only_enabled: bool = True) -> list[dict]:
    return [_to_api(row) for row in repo.list_archetypes(conn, only_enabled=only_enabled)]


def get_archetype(conn: sqlite3.Connection, archetype_id: str) -> dict:
    item = repo.get_archetype(conn, archetype_id)
    if item is None:
        raise NotFoundError("C-02-02", "指定的画像不存在", field="archetype_id")
    return _to_api(item)


def profile_of(conn: sqlite3.Connection, archetype_id: str) -> dict:
    """返回可直接提交给推演接口的画像结构。此处读取表结构，不走接口结构。"""
    row = repo.get_archetype(conn, archetype_id)
    if row is None:
        raise NotFoundError("C-02-02", "指定的画像不存在", field="archetype_id")
    return repo.to_profile(row)


# ---------------------------------------------------------------- 结构映射

# 画像记录把悦己预算拆成两列，接口对外统一用与推演一致的 budget 结构，
# 避免同一份数据出现两种形状。
def _to_api(row: dict) -> dict:
    data = dict(row)
    data["budget"] = {
        "growth_monthly": data.pop("growth_budget", 0.0),
        "treat_monthly": data.pop("treat_budget", 0.0),
    }
    return data


def _to_row(payload: dict) -> dict:
    row = dict(payload)
    budget = row.pop("budget", None)
    if isinstance(budget, dict):
        row.setdefault("growth_budget", budget.get("growth_monthly"))
        row.setdefault("treat_budget", budget.get("treat_monthly"))
    row.pop("profile_id", None)
    return row


def create(conn: sqlite3.Connection, payload: dict, catalog: Catalog) -> dict:
    payload = _to_row(payload)
    if not payload.get("archetype_id"):
        raise ValidationError("archetype_id", "画像标识不能为空", code="C-01-01")
    if repo.get_archetype(conn, payload["archetype_id"]):
        raise ValidationError("archetype_id", "该画像标识已存在", code="C-01-01")
    _validate(payload, catalog)
    result = repo.create_archetype(conn, payload)
    invalidate()
    return _to_api(result)


def update(conn: sqlite3.Connection, archetype_id: str, payload: dict, catalog: Catalog) -> dict:
    current = _to_row(get_archetype(conn, archetype_id))
    merged = {**current, **_to_row(payload)}
    merged["archetype_id"] = archetype_id
    _validate(merged, catalog)
    result = repo.update_archetype(conn, archetype_id, merged)
    invalidate()
    return _to_api(result)


def remove(conn: sqlite3.Connection, archetype_id: str) -> None:
    item = repo.get_archetype(conn, archetype_id)
    if item is None:
        raise NotFoundError("C-02-02", "指定的画像不存在", field="archetype_id")
    if item.get("kind", "builtin") != "user":
        raise ValidationError("archetype_id", "内置画像不可删除，只能删除自己保存的档案",
                              code="C-02-03")
    repo.delete_archetype(conn, archetype_id)
    invalidate()
