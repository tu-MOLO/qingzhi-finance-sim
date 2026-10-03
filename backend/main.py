"""启动入口。

启动后在本机端口提供服务，浏览器访问 http://127.0.0.1:8000 即可。
仅监听回环地址，从网络层面保证画像数据不出本机。
"""

from __future__ import annotations

import argparse
import logging

from backend import config as C
from backend.api.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="青智方舟本地服务")
    parser.add_argument("--port", type=int, default=C.PORT, help="监听端口")
    parser.add_argument("--verbose", action="store_true", help="输出访问日志")
    parser.add_argument("--init-db", action="store_true", help="重建数据库并导入种子数据后退出")
    parser.add_argument("--reset-db", action="store_true", help="清空并重建数据库后退出")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else getattr(logging, C.LOG_LEVEL),
                        format=C.LOG_FORMAT)

    if args.init_db or args.reset_db:
        from backend.db import connection
        counts = connection.initialize(force=args.reset_db)
        print("数据库已初始化：", counts)
        return

    # 凭据在使用者在设置页里填好之后落在 .env.local，这里先行载入，
    # 免得刚配完必须重启服务才生效
    from backend.services.settings import ensure_env_loaded
    ensure_env_loaded()

    app = create_app()
    print(f"青智方舟已在 http://{C.HOST}:{args.port} 启动，按 Ctrl+C 停止。")
    app.run(host=C.HOST, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
