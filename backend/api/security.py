"""请求防护：主机校验、响应头、请求体上限与重计算互斥。"""

from __future__ import annotations

import threading

from flask import Flask, jsonify, request

from .. import config as C
from ..common.errors import AppError

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)

_compute_lock = threading.BoundedSemaphore(max(1, C.COMPUTE_CONCURRENCY))


def install_security(app: Flask) -> None:
    @app.before_request
    def guard_host():
        host = (request.host or "").split(":")[0].strip("[]").lower()
        if host and host not in C.ALLOWED_HOSTS:
            return jsonify({"ok": False, "error": {
                "code": "V-02-03", "message": "仅允许通过本机地址访问"}}), 403
        return None

    @app.after_request
    def harden(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        return response


def with_compute_slot(handler):
    """重计算接口的互斥包装。被占用时立即返回，避免请求堆积。"""
    if not _compute_lock.acquire(blocking=False):
        raise AppError("S-04-02", "正在推演，请稍候", http_status=429)
    try:
        return handler()
    finally:
        _compute_lock.release()


def body() -> dict:
    """读取请求体并确保它是一个 JSON 对象。"""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise AppError("V-01-02", "请求内容必须是 JSON 对象", http_status=400)
    return payload


def sanitize_text(value, field: str, required: bool = False, default: str = "") -> str:
    if value is None:
        if required:
            raise AppError("V-01-03", f"字段 {field} 不能为空", field=field, http_status=400)
        return default
    if not isinstance(value, str):
        raise AppError("V-01-03", f"字段 {field} 的内容不合法", field=field, http_status=400)
    text = value.strip()
    if len(text) > C.MAX_TEXT_LENGTH:
        raise AppError("V-01-03", f"字段 {field} 的长度超出限制", field=field, http_status=400)
    if required and not text:
        raise AppError("V-01-03", f"字段 {field} 不能为空", field=field, http_status=400)
    return text
