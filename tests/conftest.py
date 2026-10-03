"""共用夹具。数据库在会话开始时确保就绪。"""

from __future__ import annotations

import copy
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.api.app import create_app  # noqa: E402
from backend.db import connection  # noqa: E402
from backend.db.repository import archetype as archetype_repo  # noqa: E402
from backend.services import configuration  # noqa: E402
from backend.services.configuration import get_catalog, invalidate  # noqa: E402

# 测试环境强制走本地规则路径的那几项智能体配置
OFFLINE_AGENT_SETTINGS = {
    "agent.allow_network": False,
    "agent.provider": "rule",
    "agent.base_url": "",
    "agent.model": "",
}


@pytest.fixture(scope="session", autouse=True)
def offline_agents():
    """把智能体钉在本地规则路径上，会话期间不发出任何外部请求。

    运行结果不应该被本机运维配置左右：同一份测试在接入外部模型的机器上与在离线机器上
    必须给出同样的结论。这里包一层装配函数，比逐个测试传参更不容易漏。
    """
    original = configuration.load_catalog

    def patched(conn=None):
        catalog = original(conn)
        settings = dict(catalog.settings)
        settings.update(OFFLINE_AGENT_SETTINGS)
        return replace(catalog, settings=settings)

    shim = pytest.MonkeyPatch()
    shim.setattr(configuration, "load_catalog", patched)
    yield
    shim.undo()


@pytest.fixture(scope="session", autouse=True)
def ensure_database():
    connection.initialize()
    yield


@pytest.fixture(scope="session")
def app():
    application = create_app()
    application.config.update(TESTING=True)
    return application


@pytest.fixture(scope="session")
def client(app):
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture()
def catalog():
    invalidate()
    return get_catalog()


@pytest.fixture()
def profile_payload() -> dict:
    """默认画像，来自数据库中的典型画像记录。"""
    with connection.session() as conn:
        item = archetype_repo.get_archetype(conn, "intern_junior")
        return copy.deepcopy(archetype_repo.to_profile(item))


@pytest.fixture()
def domain_profile(profile_payload, catalog):
    from backend.services import profile as profile_service
    return profile_service.normalize_and_validate(profile_payload, catalog)


@pytest.fixture()
def api():
    """接口调用助手，返回 (状态码, 响应体)。"""
    def call(client_, method, path, payload=None):
        fn = getattr(client_, method)
        response = fn(path, json=payload) if payload is not None else fn(path)
        return response.status_code, (response.get_json() if response.is_json else None)
    return call
