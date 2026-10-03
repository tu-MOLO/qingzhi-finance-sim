"""画像接口：校验与结余预览。二者都不落盘。"""

from __future__ import annotations

from flask import Blueprint, jsonify

from ...services import profile as service
from ...services.configuration import get_catalog
from ..security import body

bp = Blueprint("profile", __name__)


def _payload() -> dict:
    payload = body()
    profile = payload.get("profile", payload)
    if not isinstance(profile, dict):
        from ...common.errors import AppError
        raise AppError("V-01-03", "画像内容必须是 JSON 对象", field="profile", http_status=400)
    return profile


@bp.post("/profile/validate")
def validate_profile():
    profile = service.normalize_and_validate(_payload(), get_catalog())
    return jsonify({"ok": True, "data": {
        "valid": True,
        "goals": len(profile.goals),
        "months": profile.months,
        "paths": profile.paths,
    }})


@bp.post("/profile/preview")
def preview_profile():
    """结余预览。期望收入的口径属于业务逻辑，由服务端计算后返回。"""
    return jsonify({"ok": True, "data": service.preview(_payload(), get_catalog())})
