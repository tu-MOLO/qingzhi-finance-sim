"""数据一致性检查。

这组测试是「业务数据只来自数据库」这条约束的守门人：
扫描后端与前端代码，确认没有硬编码的业务常量、没有赛事字样、
没有引用不存在的文案键、字典类型、配置键或参数键。
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
SEEDS = ROOT / "database" / "seeds"
DATABASE = ROOT / "database" / "var" / "qingzhi.db"

# 不允许出现在产品代码、界面文案与目录命名中的字样
BANNED_WORDS = ("工行杯", "大赛", "参赛")

# 只有交付说明可以记录赛事背景
COMPETITION_DOC = "交付说明.md"


def _backend_sources() -> list[Path]:
    return [p for p in BACKEND.rglob("*.py") if "__pycache__" not in p.parts]


def _frontend_sources() -> list[Path]:
    return [p for p in FRONTEND.rglob("*") if p.suffix in (".js", ".css", ".html")]


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DATABASE)


# ---------------------------------------------------------------- 赛事字样


def test_no_competition_wording_in_code():
    for path in _backend_sources() + _frontend_sources():
        text = path.read_text(encoding="utf-8")
        for word in BANNED_WORDS:
            assert word not in text, f"{path} 含有赛事字样：{word}"


def test_no_competition_wording_in_seeds():
    for path in SEEDS.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        for word in BANNED_WORDS:
            assert word not in text, f"{path} 含有赛事字样：{word}"


def test_no_competition_wording_in_docs():
    for path in (ROOT / "docs").glob("*.md"):
        if path.name == COMPETITION_DOC:
            continue
        text = path.read_text(encoding="utf-8")
        for word in BANNED_WORDS:
            assert word not in text, f"{path} 含有赛事字样：{word}"


def test_competition_doc_exists():
    assert (ROOT / "docs" / COMPETITION_DOC).exists()


def test_directory_names_clean():
    for path in ROOT.rglob("*"):
        if not path.is_dir() or ".git" in path.parts or ".workbuddy" in path.parts:
            continue
        for word in BANNED_WORDS:
            assert word not in path.name, f"目录名含有赛事字样：{path}"


# ---------------------------------------------------------------- 硬编码业务常量


# 具有辨识度的业务取值。单位换算常量不属于业务参数，单独放行：
# 10000 为元到万元的换算，1000 为秒到毫秒、以及千分位的换算
UNIT_CONSTANTS = {"10000", "1000"}


def _seeded_numbers() -> set[str]:
    """从种子文件中收集有辨识度的数值。"""
    values: set[str] = set()
    for path in SEEDS.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        stacked = [payload]
        while stacked:
            node = stacked.pop()
            if isinstance(node, dict):
                stacked.extend(node.values())
            elif isinstance(node, list):
                stacked.extend(node)
            elif isinstance(node, (int, float)) and not isinstance(node, bool):
                text = f"{node:g}"
                if abs(node) >= 1000 or (0 < abs(node) < 1 and len(text) >= 5):
                    values.add(text)
    return values - UNIT_CONSTANTS


# 部署层只放目录、地址、上限与日志级别，按设计不含任何业务数据，
# 因此不参与业务取值的扫描
DEPLOYMENT_FILES = {"config.py", "main.py"}


def _source_files() -> list[Path]:
    files = [p for p in BACKEND.rglob("*.py")
             if "__pycache__" not in p.parts and p.name not in DEPLOYMENT_FILES]
    files += list((FRONTEND / "assets").rglob("*.js"))
    files += list((FRONTEND / "assets").rglob("*.css"))
    files += [FRONTEND / "index.html"]
    return files


def test_no_seeded_value_hardcoded():
    """业务取值只能来自数据库，不得作为字面量写进代码。

    检查方式：把种子文件里的辨识度取值逐个拿去搜代码，
    任何一处出现都说明该值被写死了。
    """
    numbers = _seeded_numbers()
    assert numbers, "未能从种子文件读到业务取值"
    offenders: list[str] = []
    pattern = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])")
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        stripped_lines = []
        for number, line in enumerate(text.splitlines(), 1):
            if line.strip().startswith(("#", "//", "*")):
                continue
            stripped_lines.append((number, line))
        for number, line in stripped_lines:
            for match in pattern.finditer(line):
                if match.group(1) in numbers:
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{number} 出现业务取值 {match.group(1)} | {line.strip()[:70]}")
    assert not offenders, "代码中出现硬编码的业务取值：" + "\n".join(offenders[:20])


def test_domain_reads_no_files_or_database():
    """领域层不得接触数据库、文件或网络。"""
    for path in (BACKEND / "domain").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("sqlite3", "open(", "Path(", "requests", "urllib", "socket"):
            assert forbidden not in text, f"{path.name} 出现了 {forbidden}"


def test_api_layer_has_no_business_rules():
    """接口层不得直接连接数据库。"""
    for path in (BACKEND / "api").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "sqlite3" not in text, f"{path.name} 直接引用了 sqlite3"
        assert "INSERT INTO" not in text, f"{path.name} 出现了写库语句"


def test_frontend_has_no_visible_copy():
    """页面结构与样式不写可见文案，文案一律来自接口。"""
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    body = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    visible = re.findall(r">\s*([一-龥][^<>{}]*?)\s*<", body)
    leftovers = [item.strip() for item in visible if item.strip()]
    assert not leftovers, f"页面仍含固定文案：{leftovers}"


# ---------------------------------------------------------------- 引用完整性


def _all_frontend_js() -> str:
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in (FRONTEND / "assets" / "js").rglob("*.js"))


def test_ui_text_keys_exist():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    js = _all_frontend_js()
    keys = set(re.findall(r'Catalog\.text\("([^"]+)"', js)) | \
           set(re.findall(r'data-text="([^"]+)"', html))
    with _connect() as conn:
        available = {row[0] for row in conn.execute("SELECT key FROM ui_texts")}
    missing = sorted(keys - available)
    assert not missing, f"引用了不存在的文案键：{missing}"


def test_message_codes_exist():
    js = _all_frontend_js()
    codes = set(re.findall(r'Catalog\.message\w*\("([^"]+)"', js))
    with _connect() as conn:
        available = {row[0] for row in conn.execute("SELECT code FROM messages")}
    missing = sorted(codes - available)
    assert not missing, f"引用了不存在的提示码：{missing}"


def test_dictionary_types_exist():
    js = _all_frontend_js()
    types = set(re.findall(r'Catalog\.(?:items|nameOf|attributes)\("([^"]+)"', js))
    with _connect() as conn:
        available = {row[0] for row in conn.execute("SELECT code FROM dict_types")}
    missing = sorted(types - available)
    assert not missing, f"引用了不存在的字典类型：{missing}"


def test_setting_and_parameter_keys_exist():
    js = _all_frontend_js()
    settings = set(re.findall(r'settings\["([^"]+)"\]', js))
    parameters = set(re.findall(r'parameters\["([^"]+)"\]', js))
    with _connect() as conn:
        available_settings = {row[0] for row in conn.execute("SELECT key FROM app_settings")}
        available_params = {row[0] for row in
                            conn.execute("SELECT key FROM model_params WHERE key IS NOT NULL")}
    assert not (settings - available_settings), f"不存在的配置键：{sorted(settings - available_settings)}"
    assert not (parameters - available_params), f"不存在的参数键：{sorted(parameters - available_params)}"


def test_frontend_element_ids_exist():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([^"]+)"', html))
    js = _all_frontend_js()
    referenced = {a or b for a, b in re.findall(r'el\("([^"]+)"\)|getElementById\("([^"]+)"\)', js)}
    missing = sorted(referenced - ids)
    assert not missing, f"脚本引用了页面上不存在的元素：{missing}"


# ---------------------------------------------------------------- 种子完整性


REQUIRED_SEED_FILES = (
    "dict_types.json", "dict_items.json", "app_settings.json", "risk_levels.json",
    "accounts.json", "model_params.json", "data_sources.json", "messages.json",
    "ui_texts.json", "corpus_documents.json", "terms.json", "archetypes.json",
)


@pytest.mark.parametrize("filename", REQUIRED_SEED_FILES)
def test_seed_file_present(filename):
    assert (SEEDS / filename).exists(), f"缺少种子文件：{filename}"


def test_database_has_data():
    with _connect() as conn:
        for table in ("dict_items", "app_settings", "risk_levels", "accounts",
                      "model_params", "messages", "ui_texts", "terms", "archetypes"):
            count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            assert count > 0, f"表 {table} 没有数据"


def test_every_setting_key_consumed():
    """配置项要么被后端引用，要么被前端引用，不留无人使用的配置。"""
    js = _all_frontend_js()
    backend_text = "\n".join(p.read_text(encoding="utf-8") for p in _backend_sources())
    with _connect() as conn:
        keys = [row[0] for row in conn.execute("SELECT key FROM app_settings")]
    unused = []
    for key in keys:
        frontend_key = key.split(".")[-1]
        if key in backend_text:
            continue
        if key in js or frontend_key in js:
            continue
        unused.append(key)
    assert not unused, f"存在无人使用的配置项：{unused}"

# ---------------------------------------------------------------- 文案闭环


def _frontend_blob() -> str:
    parts = [FRONTEND / "index.html"]
    parts += sorted((FRONTEND / "assets" / "js").glob("*.js"))
    parts += sorted((FRONTEND / "assets" / "js" / "views").glob("*.js"))
    return chr(10).join(path.read_text(encoding="utf-8") for path in parts)


def _backend_blob() -> str:
    return chr(10).join(
        path.read_text(encoding="utf-8")
        for path in BACKEND.rglob("*.py") if "__pycache__" not in path.parts)


def _unused(keys: set[str], blob: str) -> list[str]:
    # 文案键本身具备唯一性，直接做子串匹配比按调用形式匹配更不易漏判
    return sorted(key for key in keys if key not in blob)


def test_every_ui_text_is_referenced():
    """界面文案表里不允许躺着没人使用的条目。

    加入新文案时必须同时接上引用点，否则这里就会失败。
    """
    blob = _frontend_blob() + _backend_blob()
    with sqlite3.connect(DATABASE) as conn:
        keys = {row[0] for row in conn.execute("SELECT key FROM ui_texts")}
    assert keys
    assert not _unused(keys, blob), "以下界面文案没有被任何地方引用：" + ", ".join(
        _unused(keys, blob))


def test_every_message_is_referenced():
    blob = _frontend_blob() + _backend_blob()
    with sqlite3.connect(DATABASE) as conn:
        keys = {row[0] for row in conn.execute("SELECT code FROM messages")}
    assert keys
    assert not _unused(keys, blob), "以下提示文案没有被任何地方引用：" + ", ".join(
        _unused(keys, blob))

def test_domain_layer_has_no_user_copy():
    """领域层是纯计算层，除文档字符串与错误消息外不得出现面向用户的中文文案。

    这一条是在把方案标题硬编码迁回文案表之后补上的，防止同类问题回流。
    """
    import ast

    cjk = re.compile(r"[一-鿿]")

    def build_parents(tree):
        mapping = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                mapping[id(child)] = node
        return mapping

    def ancestors(node, mapping):
        chain = []
        current = mapping.get(id(node))
        while current is not None:
            chain.append(current)
            current = mapping.get(id(current))
        return chain

    offenders: list[str] = []
    for path in sorted((BACKEND / "domain").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        mapping = build_parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if not cjk.search(node.value):
                continue
            chain = ancestors(node, mapping)
            # 错误消息随异常抛出，属于错误语义，不是文案
            if any(isinstance(item, ast.Raise) for item in chain):
                continue
            # 模块、类、函数的 docstring 与字段说明
            parent = mapping.get(id(node))
            if isinstance(parent, ast.Expr):
                grand = mapping.get(id(parent))
                if isinstance(grand, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
            offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, "领域层出现了面向用户的中文文案：" + ", ".join(offenders[:10])

def test_grade_windows_reference_valid_sources():
    """每个年级的收入窗口都指向真实存在的收入来源类别。"""
    import json as _json
    with sqlite3.connect(DATABASE) as conn:
        source_codes = {row[0] for row in conn.execute(
            "SELECT code FROM dict_items WHERE type_code='income_source'")}
        grade_rows = conn.execute(
            "SELECT code, attributes FROM dict_items WHERE type_code='grade'").fetchall()
    for code, attributes in grade_rows:
        windows = (_json.loads(attributes) or {}).get("income_windows", {})
        for source_code in windows:
            assert source_code in source_codes, (
                f"年级 {code} 引用了不存在的收入来源 {source_code}")


def test_catalog_includes_parameter_rows():
    """配置目录必须带出参数的完整行，供界面展示解释与来源。"""
    import sys
    sys.path.insert(0, str(ROOT))
    from backend.services.configuration import catalog_payload
    payload = catalog_payload()
    assert payload["parameterRows"]
    for row in payload["parameterRows"]:
        if row.get("key"):
            assert row["property_name"], f"参数 {row['key']} 缺少性质说明"


def test_archetype_expenses_are_seeded():
    """典型画像必须自带支出项，不能依赖代码里的兜底。"""
    with sqlite3.connect(DATABASE) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM archetype_expenses WHERE archetype_id = 'intern_junior'"
        ).fetchone()[0]
    assert rows >= 6, "实习成长型画像的支出项不足"

def test_city_variable_removed():
    """城市变量已移除：字典里不应再出现城市条目或生活成本系数。"""
    with sqlite3.connect(DATABASE) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM dict_items WHERE type_code='city'").fetchone()[0]
        types = conn.execute(
            "SELECT COUNT(*) FROM dict_types WHERE code='city'").fetchone()[0]
    assert rows == 0, "城市字典仍有残留条目"
    assert types == 0, "城市字典类型仍有残留"


def test_living_baselines_present():
    """家庭支持基准与支出基准必须存在，默认画像才能生成完整收支。"""
    with sqlite3.connect(DATABASE) as conn:
        living = conn.execute(
            "SELECT value_base FROM model_params WHERE key='national_living_cost'").fetchone()
        expense_base = conn.execute(
            "SELECT COUNT(*) FROM dict_items WHERE type_code='expense_category' "
            "AND json_extract(attributes, '$.default_amount') > 0").fetchone()[0]
    assert living and living[0] and living[0] > 0, "缺少家庭支持基准参数 national_living_cost"
    assert expense_base >= 6, "带基准金额的支出类别不足"
