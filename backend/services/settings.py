"""智能体运行配置的读写。

配置项落在数据库，凭据只落在仓库之外的一个本地文件与当前进程的环境变量里。
两者的分工是刻意的：配置可以导出与迁移，凭据不能，因此它不进库、不进版本控制、
也不随任何导出发走。
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from .. import config as C
from ..common.errors import AppError, ValidationError
from ..db import connection
from ..db.repository import base as repo_base
from .configuration import Catalog, invalidate, get_catalog

# 允许从设置页直接改写的配置项。想加项只能改这份白名单，
# 免得推演口径（路径条数、容差、求解上限）被当成随便填的输入框。
AGENT_SETTINGS = ("agent.provider", "agent.base_url", "agent.model", "agent.allow_network",
                  "agent.temperature", "agent.max_tokens", "agent.timeout_seconds")

# 只允许这两个取值：一个是本地确定性生成，一个是 OpenAI 兼容接口
PROVIDER_CHOICES = ("rule", "openai_compat")

FIELD_MESSAGES = {
    "temperature": "生成温度需是 0 到 2 之间的数值，数值越低输出越稳定",
    "maxTokens": "单次生成长度需是 1 到 32768 之间的整数",
    "timeoutSeconds": "超时秒数需是 1 到 600 之间的整数",
}

DEFAULT_KEY_ENV = "QINGZHI_AGENT_API_KEY"

ENV_FILE = C.ROOT_DIR / ".env.local"

_ENV_HEADER = (
    "# 本地凭据。文件已被 .gitignore 忽略，不要提交到仓库。\n"
    "# 也可以自行在终端执行：source .env.local 后启动服务\n"
)


# ---------------------------------------------------------------- 凭据文件


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """把本地凭据文件里的键值对补进进程环境。

    已经存在的环境变量优先：手工 export 的值不该被文件里的旧值覆盖。
    """
    file_path = path or ENV_FILE
    if not file_path.is_file():
        return {}
    try:
        raw = file_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    loaded: dict[str, str] = {}
    for line in raw.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.startswith("export "):
            entry = entry[len("export "):].strip()
        if "=" not in entry:
            continue
        name, _, value = entry.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if not name:
            continue
        loaded[name] = value
        os.environ.setdefault(name, value)
    return loaded


def ensure_env_loaded() -> dict[str, str]:
    """幂等地载入凭据文件。进程启动与任何读取之前调用都不重复写环境。"""
    return load_env_file()


def key_env_name(settings: dict) -> str:
    return str(settings.get("agent.api_key_env") or "").strip() or DEFAULT_KEY_ENV


def has_api_key(settings: dict) -> bool:
    return bool(os.environ.get(key_env_name(settings), "").strip())


def write_api_key(settings: dict, value: str) -> None:
    """凭据写进本地文件并立即在当前进程生效。

    留空表示清空：文件里的那一行会被移除，环境变量同步删掉。
    """
    name = key_env_name(settings)
    token = (value or "").strip()
    lines: list[str] = []
    if ENV_FILE.is_file():
        try:
            lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
    target = name
    kept: list[str] = []
    for line in lines:
        entry = line.strip()
        bare = entry[len("export "):].strip() if entry.startswith("export ") else entry
        key = bare.partition("=")[0].strip()
        # 去掉同名的旧行，其余原样保留（含注释与其它变量）
        if key == target:
            continue
        kept.append(line)
    # 注释头只在文件尚无注释时补写，避免每次保存都堆一行
    has_comment = any((line.strip().startswith("#") for line in kept))
    if token:
        if kept and kept[-1].strip():
            kept.append("")
        kept.append(f"export {target}={token}")
    head = "" if has_comment else _ENV_HEADER
    text = head + "\n".join(kept)
    if text and not text.endswith("\n"):
        text += "\n"
    try:
        ENV_FILE.write_text(text, encoding="utf-8")
        try:
            # 凭据文件只对当前用户可读，Windows 上权限位支持有限，失败就按系统默认
            os.chmod(ENV_FILE, 0o600)
        except OSError:
            pass
    except OSError as exc:
        raise AppError("C-03-01", "凭据文件写入失败，请检查运行目录的写入权限") from exc

    if token:
        os.environ[name] = token
    else:
        os.environ.pop(name, None)


# ---------------------------------------------------------------- 读取与写入


def agent_status(conn: sqlite3.Connection, catalog: Catalog | None = None) -> dict:
    """给界面用的智能体配置状态。任何情况下都不返回凭据本体。"""
    ensure_env_loaded()
    settings = catalog.settings if catalog is not None else _settings(conn)
    provider = str(settings.get("agent.provider") or "rule")
    base_url = str(settings.get("agent.base_url") or "").strip()
    model = str(settings.get("agent.model") or "").strip()
    allow_network = _truthy(settings.get("agent.allow_network"))
    return {
        "provider": provider if provider in PROVIDER_CHOICES else "rule",
        "allowNetwork": allow_network,
        "baseUrl": base_url,
        "model": model,
        # 这几项只做读取与回显，缺省时留空由界面显示未设置，不在代码里兜业务默认值
        "temperature": _number(settings.get("agent.temperature")),
        "maxTokens": _integer(settings.get("agent.max_tokens")),
        "timeoutSeconds": _integer(settings.get("agent.timeout_seconds")),
        "hasKey": has_api_key(settings),
        "keyEnv": key_env_name(settings),
        "keyFilePresent": ENV_FILE.is_file(),
        # 外部模型才算「已配置」：本地规则路径本来就不需要任何凭据
        "configured": (provider == "openai_compat" and allow_network and bool(base_url)
                       and bool(model) and has_api_key(settings)),
    }


def save_agent(conn: sqlite3.Connection, payload: dict, catalog: Catalog) -> None:
    """写入配置与凭据。只写不读：事务在会话退出时才提交，
    提交前用新连接读状态只会读到旧值，状态回读交给调用方在会话结束后做。"""
    payload = payload or {}
    provider = str(payload.get("provider") or "").strip()
    if provider not in PROVIDER_CHOICES:
        raise ValidationError("provider", "生成方式只能取 rule 或 openai_compat", code="C-01-01")

    base_url = str(payload.get("baseUrl") or "").strip()
    if base_url and not valid_endpoint(base_url):
        raise ValidationError("baseUrl", "模型服务地址必须是 http 或 https 开头的有效地址")

    values = {
        "agent.provider": provider,
        "agent.allow_network": "1" if _truthy(payload.get("allowNetwork")) else "0",
        "agent.base_url": base_url[:512],
        "agent.model": str(payload.get("model") or "").strip()[:128],
    }
    # 三个数值只接受范围内的有限值，越界直接拒绝而不是悄悄夹取——
    # 使用者填了 300 秒超时，他要的更可能是被告知这个数不合理
    for key, low, high, integer in (("temperature", 0.0, 2.0, False),
                                    ("maxTokens", 1.0, 32768.0, True),
                                    ("timeoutSeconds", 1.0, 600.0, True)):
        if key not in payload or payload[key] is None or payload[key] == "":
            continue
        value = _number(payload[key])
        if value is None or not (low <= value <= high):
            raise ValidationError(key, FIELD_MESSAGES[key])
        values["agent." + _snake(key)] = str(int(value) if integer else round(value, 3))

    for key, value in values.items():
        if key not in AGENT_SETTINGS:
            continue
        repo_base.update(conn, "app_settings", "key", key, {"value": value})
        repo_base.record_change(conn, "app_settings", key, "update")

    # 凭据单独走文件。payload 里没有这个字段表示不改动，空字符串表示清空
    key = payload.get("apiKey")
    if isinstance(key, str):
        write_api_key(catalog.settings, key)

    invalidate()


def read_status() -> dict:
    """会话提交之后的新连接里读一次状态，保证界面看到的就是刚写进去的。"""
    with connection.session() as conn:
        return agent_status(conn, get_catalog(refresh=True))


def _settings(conn: sqlite3.Connection) -> dict:
    from ..db.repository import configuration as config_repo
    return config_repo.settings(conn)


def _integer(value) -> int | None:
    result = _number(value)
    return None if result is None else int(result)


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def valid_endpoint(base_url: str) -> bool:
    parsed = urlparse((base_url or "").strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _number(value, minimum: float | None = None) -> float | None:
    """把读入的值转成数值。无值或不可解析时返回空，由调用方决定如何呈现。"""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    if result < 0:
        return None
    if minimum is not None and result < minimum:
        result = minimum
    return result


def _snake(camel: str) -> str:
    return "".join("_" + char.lower() if char.isupper() else char for char in camel)
