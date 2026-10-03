"""项目入口。

用法：
    python run.py                  启动本地服务
    python run.py --reset-db       清空并重建数据库后退出
    python run.py --init-db        补建缺失的数据后退出
    python run.py --port 8080      指定端口
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.main import main  # noqa: E402

if __name__ == "__main__":
    main()
