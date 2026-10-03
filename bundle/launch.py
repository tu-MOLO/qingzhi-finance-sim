"""可执行版的启动入口。

打包后由生成的可执行文件直接跑到这里，职责与开发态的 run.py 相同，
另加三件开发态不需要、打包后却少不了的事：

  · 挑一个空闲端口。使用者可能已经开着一份，换端口比直接报错好；
  · 服务起来之后自动打开浏览器。双击即可用，不必再去地址栏敲网址；
  · 控制台改用 UTF-8 输出。中文 Windows 的控制台默认 GBK，直接打印中文会抛编码错误。

窗口关掉即停止服务，数据留在可执行文件旁边。
"""

from __future__ import annotations

import socket
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 选端口时向上试探的范围
_PORT_SPAN = 20

# 打开浏览器的等待时间。服务监听先起来，浏览器才不会扑空
_OPEN_DELAY = 1.2


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def _in_use(host: str, port: int) -> bool:
    """端口是否已被占用。

    两道判据缺一不可：只试连会漏掉恰好处于 TIME_WAIT 的端口，只试绑在 Windows 上
    会漏掉对方也设了 SO_REUSEADDR 的情况——那个选项允许两个套接字绑同一个端口，
    靠 bind 探测会得出「空闲」的错误结论，结果两份服务抢同一个端口。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        if probe.connect_ex((host, port)) == 0:
            return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return True
    return False


def pick_port(host: str, preferred: int) -> int:
    """从首选端口往上找第一个当前空闲的。

    探测与真正监听之间有一瞬间隙，两个实例同时启动仍有极小概率撞上；
    本机单用户场景下这已经足够，撞上则由使用者再点一次。
    """
    for offset in range(_PORT_SPAN):
        port = preferred + offset
        if not _in_use(host, port):
            return port
    return preferred


def open_later(url: str) -> None:
    def run():
        try:
            webbrowser.open(url)
        except Exception:
            # 打不开也不影响服务本身，使用者照着地址栏手输即可
            pass
    threading.Timer(_OPEN_DELAY, run).start()


def main() -> int:
    _utf8_console()

    from backend import config as C
    from backend.api.app import create_app
    from backend.services.settings import ensure_env_loaded

    ensure_env_loaded()
    app = create_app()

    host = C.HOST
    port = pick_port(host, C.PORT)
    url = f"http://{host}:{port}/"

    banner = (
        "\n"
        "  青智方舟\n"
        "\n"
        f"  服务地址：{url}\n"
        f"  数据目录：{C.RUNTIME_DIR}\n"
        "\n"
        "  浏览器已自动打开。用完直接关掉本窗口即可停止服务。\n"
        "  本程序只监听本机地址，画像数据不上传、不出本机。\n"
        "\n"
    )
    # 输出重定向到文件时是块缓冲，不主动冲刷的话这几行要等到进程退出才出现
    sys.stdout.write(banner)
    sys.stdout.flush()

    open_later(url)
    try:
        app.run(host=host, port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n  已停止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
