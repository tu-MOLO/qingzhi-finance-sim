"""反事实与敏感性接口。"""

from __future__ import annotations

from flask import Blueprint, jsonify

from ...common.errors import AppError
from ...services import profile as profile_service
from ...services import whatif as service
from ...services.configuration import get_catalog
from ..security import body, with_compute_slot

bp = Blueprint("whatif", __name__)


def _profile(catalog):
    payload = body()
    raw = payload.get("profile", payload)
    if not isinstance(raw, dict):
        raise AppError("V-01-03", "画像内容必须是 JSON 对象", field="profile", http_status=400)
    return profile_service.normalize_and_validate(raw, catalog)


@bp.post("/simulation/whatif")
def run_whatif():
    catalog = get_catalog()
    profile = _profile(catalog)
    return with_compute_slot(lambda: jsonify({"ok": True, "data": service.analyze(profile, catalog)}))
