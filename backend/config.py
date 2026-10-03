"""运行期配置。

本文件只存放部署与运行相关的设置：目录位置、监听地址、请求体上限、日志级别。
任何业务数据（参数、阈值、权重、字典、文案、画像、语料）一律不在此处，
它们的唯一来源是数据库。
"""

from __future__ import annotations

import sys
from pathlib import Path


def _is_frozen() -> bool:
    """是否运行在打包出来的可执行文件里。"""
    return bool(getattr(sys, "frozen", False))


def _bundle_dir() -> Path:
    """只读资源所在目录。

    PyInstaller 把随包附带的数据文件解到 sys._MEIPASS（单文件模式是临时目录，
    单目录模式是 _internal）。开发态下资源就在仓库里，直接用模块位置推算。
    """
    if _is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def _root_dir() -> Path:
    """可写目录：数据库、凭据与使用者的业务数据都落在这里。

    打包后取可执行文件所在目录，随包走而不是落在解包临时目录里——
    单文件模式每次启动换一个临时目录，数据放那儿等于每次都丢。
    """
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


# 可写目录。开发态与仓库根一致，打包后是可执行文件所在目录
ROOT_DIR = _root_dir()

# 只读资源目录。开发态与可写目录重合，打包后指向随包解出的资源
BUNDLE_DIR = _bundle_dir()

# ---------------------------------------------------------------- 目录
# 结构文件、种子与前端属于代码资产，随包只读；
# 数据库与使用者的凭据属于使用者的数据，必须落在可写目录
SCHEMA_DIR = BUNDLE_DIR / "database" / "schema"
SEED_DIR = BUNDLE_DIR / "database" / "seeds"
FRONTEND_DIR = BUNDLE_DIR / "frontend"
RUNTIME_DIR = ROOT_DIR / "database" / "var"

DATABASE_DIR = RUNTIME_DIR
DATABASE_FILE = RUNTIME_DIR / "qingzhi.db"

# ---------------------------------------------------------------- 服务
HOST = "127.0.0.1"
PORT = 8000
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "::1")

# 请求体上限。超过即拒绝，防止恶意构造超大载荷
MAX_BODY_BYTES = 256 * 1024
# 单个文本字段的长度上限
MAX_TEXT_LENGTH = 64
# 重计算接口的并发上限。本地单用户场景下取一，避免并发推演把内存打满
COMPUTE_CONCURRENCY = 1

# ---------------------------------------------------------------- 日志
LOG_LEVEL = "WARNING"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
