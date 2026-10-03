"""智能体运行配置接口：读取当前状态、保存使用者自行填写的参数与凭据。

凭据走环境变量这一层用意明确：交付之后由使用者自己配模型，
我们既不该预置任何密钥，也不该让密钥落进数据库随导出发走。
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from ...common.errors import AppError
from ...db import connection
from ...services import settings as service
from ...services.configuration import get_catalog
from ..security import body

bp = Blueprint("settings", __name__)


@bp.get("/agent-settings")
def read_agent_settings():
    catalog = get_catalog()
    with connection.session() as conn:
        status = service.agent_status(conn, catalog)
    return jsonify({"ok": True, "data": status})


@bp.put("/agent-settings")
def write_agent_settings():
    payload = body()
    if not isinstance(payload, dict):
        raise AppError("V-01-02", "请求体必须是 JSON 对象", field="body", http_status=400)
    catalog = get_catalog()
    with connection.session() as conn:
        service.save_agent(conn, payload, catalog)
    # 状态回读放在事务提交之后，界面看到的才是刚写进去的值
    return jsonify({"ok": True, "data": service.read_status()})


@bp.post("/agent-settings/test")
def test_agent_settings():
    """用当前配置生成一段短文本，用来验证接口地址、模型与凭据是否可用。

    只返回是否连通与错误类型，不返回模型输出——这一步的目的是连通性诊断，
    不是要一条解释，也不该让外部输出绕过后面的合规链路。
    """
    catalog = get_catalog()
    from ...agents import runtime
    outcome = runtime.probe(catalog)
    with connection.session() as conn:
        status = service.agent_status(conn, catalog)
    return jsonify({"ok": True, "data": {"probe": outcome, "settings": status}})
