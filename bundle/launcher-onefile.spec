# -*- mode: python ; coding: utf-8 -*-
"""单文件模式的打包配置。

把所有依赖压进一个可执行文件，拷走一个文件就能用。
代价是每次启动都要把内容解到临时目录，冷启动比单目录模式慢；
数据库仍然落在可执行文件旁边，不随临时目录一起消失。

构建：
    python -m PyInstaller bundle/launcher-onefile.spec --noconfirm
"""

from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(  # noqa: F821
    [str(ROOT / "bundle" / "launch.py")],
    pathex=[str(ROOT)],
    binaries=[],
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="青智方舟",
    icon=str(ROOT / "bundle" / "app.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
