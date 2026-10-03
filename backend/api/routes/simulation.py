"""推演接口。"""

from __future__ import annotations

from flask import Blueprint, jsonify

from ...common.errors import AppError
from ...services import profile as profile_service
from ...services import simulation as service
from ...services.configuration import get_catalog
from ..security import body, with_compute_slot

bp = Blueprint("simulation", __name__)


def _profile(catalog):
    payload = body()
    raw = payload.get("profile", payload)
    if not isinstance(raw, dict):
        raise AppError("V-01-03", "画像内容必须是 JSON 对象", field="profile", http_status=400)
    return profile_service.normalize_and_validate(raw, catalog)


@bp.post("/simulation/run")
def run_simulation():
    catalog = get_catalog()
    profile = _profile(catalog)
    return with_compute_slot(lambda: jsonify({"ok": True, "data": service.run(profile, catalog)}))


@bp.post("/simulation/plan")
def solve_plan():
    catalog = get_catalog()
    payload = body()
    raw = payload.get("profile", payload)
    if not isinstance(raw, dict):
        raise AppError("V-01-03", "画像内容必须是 JSON 对象", field="profile", http_status=400)
    goal_id = payload.get("goalId")
    if not isinstance(goal_id, str) or not goal_id:
        raise AppError("V-01-03", "字段 goalId 不能为空", field="goalId", http_status=400)
    profile = profile_service.normalize_and_validate(raw, catalog)
    service.require_goal(profile, goal_id)
    return with_compute_slot(
        lambda: jsonify({"ok": True, "data": service.plan_for(profile, goal_id, catalog)}))
