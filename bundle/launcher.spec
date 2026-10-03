# -*- mode: python ; coding: utf-8 -*-
"""单目录模式的打包配置。

输出一个目录，里面是可执行文件与随行依赖。启动不解压，比单文件模式快得多；
数据库与凭据直接落在可执行文件旁边的 database/var 与 .env.local，
使用者把整个目录拷走就能换一台机器继续用。

构建：
    python -m PyInstaller bundle/launcher.spec --noconfirm
"""

from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(  # noqa: F821
    [str(ROOT / "bundle" / "launch.py")],
    pathex=[str(ROOT)],
    binaries=[],
    # 结构文件、种子与前端属于代码资产，随包只读；数据库不在此列，它在可写目录里现建
    datas=[
        (str(ROOT / "database" / "schema"), "database/schema"),
        (str(ROOT / "database" / "seeds"), "database/seeds"),
        (str(ROOT / "frontend"), "frontend"),
    ],
    hiddenimports=[
        "blinker",
        "click",
        "itsdangerous",
        "jinja2",
        "markupsafe",
        "werkzeug",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "ruff", "tkinter", "pydoc", "unittest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="青智方舟",
    icon=str(ROOT / "bundle" / "app.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="青智方舟",
)
