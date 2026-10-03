"""HTTP 接口层：应用装配、请求防护与错误处理。

本层只做三件事：解析与校验请求、调用服务层、序列化响应。
不包含任何业务规则，也不直接访问数据库。
"""

from __future__ import annotations

import logging

from flask import Flask, jsonify, send_from_directory

from .. import config as C
from ..common.errors import AppError
from ..db import connection
from ..services.configuration import invalidate
from .routes import agent as agent_routes
from .routes import archetype as archetype_routes
from .routes import catalog as catalog_routes
from .routes import profile as profile_routes
from .routes import settings as settings_routes
from .routes import simulation as simulation_routes
from .routes import term as term_routes
from .routes import whatif as whatif_routes
from .security import install_security

logger = logging.getLogger("qingzhi.api")

API_PREFIX = "/api/v1"


def create_app() -> Flask:
    # 数据库是全部业务数据的来源，启动前先确保它具备运行所需的完整数据
    connection.ensure_ready()
    # 启动时的种子回灌可能刚刚改写过文案与配置，已有的目录缓存必须作废重建
    invalidate()

    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = C.MAX_BODY_BYTES
    app.config["JSON_AS_ASCII"] = False

    install_security(app)

    @app.errorhandler(AppError)
    def handle_app_error(exc: AppError):
        return jsonify({"ok": False, "error": exc.to_dict()}), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return jsonify({"ok": False, "error": {"code": "V-02-02", "message": "请求的资源不存在"}}), 404

    @app.errorhandler(413)
    def handle_too_large(_exc):
        return jsonify({"ok": False, "error": {"code": "V-01-01", "message": "请求内容过大"}}), 413

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        # 只记异常类型，不记异常消息与请求体，避免使用者填写的内容进入日志
        logger.error("服务内部异常，类型 %s", type(exc).__name__)
        return jsonify({"ok": False,
                        "error": {"code": "V-03-01", "message": "服务内部出现异常，请重试"}}), 500

    # ------------------------------------------------------------ 静态资源

    @app.get("/")
    def index():
        return send_from_directory(C.FRONTEND_DIR, "index.html")

    @app.get("/<path:filename>")
    def static_files(filename: str):
        """只允许前端目录内的文件，解析之后仍须落在该目录之内。"""
        root = C.FRONTEND_DIR.resolve()
        try:
            target = (root / filename).resolve()
        except (OSError, ValueError):
            return jsonify({"ok": False, "error": {"code": "V-02-01",
                                                   "message": "请求的路径不合法"}}), 404
        if not target.is_relative_to(root) or not target.is_file():
            return jsonify({"ok": False, "error": {"code": "V-02-02",
                                                   "message": "请求的资源不存在"}}), 404
        return send_from_directory(C.FRONTEND_DIR, filename)

    # ------------------------------------------------------------ 业务接口

    for blueprint in (catalog_routes.bp, archetype_routes.bp, profile_routes.bp,
                      simulation_routes.bp, term_routes.bp, agent_routes.bp,
                      whatif_routes.bp, settings_routes.bp):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.get(API_PREFIX + "/health")
    def health():
        return jsonify({"ok": True, "data": {"status": "up", "localOnly": True}})

    return app
