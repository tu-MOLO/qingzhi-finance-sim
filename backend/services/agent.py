"""智能体用例：输入清洗、上下文装配与结果序列化。

来自浏览器的推演摘要不被直接信任，所有字段逐项重建后再交给运行时，
畸形结构一律丢弃而不是透传。输出里的免责提示单独返回，不混在正文中。
"""

from __future__ import annotations

import sqlite3

from ..agents import registry, runtime
from ..agents.protocol import AgentContext
from ..common.errors import ConfigurationError, ExplainError, NotFoundError
from ..db.repository import term as term_repo
from .configuration import Catalog

# 摘要中数组类字段的长度上限，与推演时长的上限保持一致
_MAX_SERIES = 120
_MAX_ITEMS = 24


def catalogue(conn: sqlite3.Connection) -> dict:
    return registry.payload(conn)


def detail(conn: sqlite3.Connection, code: str) -> dict:
    item = registry.detail_of(conn, code)
    if item is None:
        raise NotFoundError("C-02-02", "指定的智能体不存在", field="agent_code")
    return item


def self_check(conn: sqlite3.Connection) -> list[str]:
    """检出声明了却没有实现处理器的工具，以及没有绑定工具的智能体。"""
    return registry.problems(conn)


def invoke(conn: sqlite3.Connection, code: str, payload: dict, catalog: Catalog) -> dict:
    agent = registry.get_agent(conn, code)
    if agent is None:
        raise NotFoundError("C-02-02", "指定的智能体不存在", field="agent_code")
    tools = registry.bound_tools(conn, code)
    if not tools:
        raise ConfigurationError(f"智能体 {code} 尚未绑定任何工具", field="agent_code")

    ctx = AgentContext()
    query = _text(payload.get("term"))
    if "corpus_lookup" in {item["code"] for item in tools}:
        term = term_repo.find_by_name_or_alias(conn, query)
        if term is None:
            raise ExplainError("E-02-01", "暂时没有收录这个说法，可以换一个词试试",
                               http_status=404)
        term["source_documents"] = term_repo.source_documents(conn, term["term_code"])
        ctx.term = term
        ctx.query = term.get("name") or query
    else:
        ctx.query = query
    ctx.snapshot = clean_snapshot(payload.get("snapshot"))
    ctx.messages = catalog.messages

    result = runtime.run(agent, tools, ctx, catalog.settings)
    visible = result.to_dict(include_steps=_as_bool(catalog.settings.get("agent.trace_enabled")))

    title = result.output.get("disclaimerTitle") or catalog.message_title("disclaimer.term")
    body = result.output.get("disclaimer") or catalog.message("disclaimer.term")
    visible["disclaimer"] = {"title": title, "body": body}
    # 免责提示已经单独返回，输出体中不再重复出现
    visible["output"].pop("disclaimer", None)
    visible["output"].pop("disclaimerTitle", None)
    return visible


# ---------------------------------------------------------------- 摘要清洗


def clean_snapshot(raw) -> dict:
    """逐字段重建推演摘要。任何结构不符的字段都直接丢弃。"""
    if not isinstance(raw, dict):
        return {}
    cleaned: dict = {}
    goals = _clean_goals(raw.get("goals"))
    if goals:
        cleaned["goals"] = goals
    goal = _clean_goal(raw.get("primaryGoal"))
    # 只给了清单时，排在最前的那个就是主目标
    if not goal and goals:
        goal = goals[0]
    if goal:
        cleaned["primaryGoal"] = goal
    capacity = _clean_capacity(raw.get("capacity"))
    if capacity:
        cleaned["capacity"] = capacity
    scenarios = _clean_scenarios(raw.get("scenarios"))
    if scenarios:
        cleaned["scenarios"] = scenarios
    allocation = _clean_allocation(raw.get("allocation"))
    if allocation:
        cleaned["allocation"] = allocation
    return cleaned


def _clean_goal(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    goal_id = _text(raw.get("goalId"))
    name = _text(raw.get("name"))
    if not goal_id or not name:
        return None
    return {
        "goalId": goal_id[:64],
        "name": name[:64],
        "amount": _number(raw.get("amount")),
        "dueMonth": _number(raw.get("dueMonth")),
        "priority": _clean_priority(raw.get("priority"), 1),
        "hitProbability": _number(raw.get("hitProbability")),
        "hitMonthP50": _nullable_number(raw.get("hitMonthP50")),
        "reachedRate": _number(raw.get("reachedRate")),
        "gapAmount": _number(raw.get("gapAmount")),
    }


def _clean_goals(raw) -> list[dict]:
    """目标清单逐项重建。任何一项结构不符就整项丢弃，不影响其余目标。"""
    if not isinstance(raw, list):
        return []
    goals: list[dict] = []
    for index, item in enumerate(raw[:_MAX_ITEMS]):
        goal = _clean_goal(item)
        if goal is None:
            continue
        goal["priority"] = _clean_priority(item.get("priority"), index + 1)
        goals.append(goal)
    return goals


def _clean_priority(value, fallback: int) -> int:
    """顺序只认不小于 1 的整数，其余按所在行次序补上。"""
    number = int(_number(value))
    return number if number >= 1 else fallback


def _clean_capacity(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    level = _text(raw.get("level"))
    if not level:
        return None
    return {
        "level": level[:32],
        "finalCap": _number(raw.get("finalCap")),
        "cushionMonths": _number(raw.get("cushionMonths")),
        "dipMonths": [int(value) for value in _numbers(raw.get("dipMonths"))][:_MAX_ITEMS],
    }


def _clean_scenarios(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    result: dict[str, dict] = {}
    for label in ("pessimistic", "base", "optimistic"):
        bucket = raw.get(label)
        if not isinstance(bucket, dict):
            continue
        result[label] = {_text(key)[:64]: _number(value)
                         for key, value in list(bucket.items())[:_MAX_ITEMS]
                         if _text(key)}
    return result or None


def _clean_allocation(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    entries = raw.get("accounts")
    if not isinstance(entries, list) or not entries:
        return None
    accounts: list[dict] = []
    for entry in entries[:_MAX_ITEMS]:
        if not isinstance(entry, dict):
            continue
        code = _text(entry.get("code"))
        if not code:
            continue
        accounts.append({"code": code[:32], "name": _text(entry.get("name"))[:32]})
    if not accounts:
        return None

    order = [_text(value)[:32] for value in (raw.get("order") or []) if _text(value)][:_MAX_ITEMS]
    series: dict[str, list[float]] = {}
    raw_series = raw.get("series")
    if isinstance(raw_series, dict):
        for code in (order or [item["code"] for item in accounts]):
            values = raw_series.get(code)
            if isinstance(values, list):
                series[code] = [_number(value) for value in values[:_MAX_SERIES]]

    return {
        "accounts": accounts,
        "order": order or [item["code"] for item in accounts],
        "series": series,
        "emergencyTarget": _number(raw.get("emergencyTarget")),
        "conservationOk": _as_bool(raw.get("conservationOk", True)),
        "priorityOk": _as_bool(raw.get("priorityOk", True)),
    }


# ---------------------------------------------------------------- 取值助手


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if result != result or result in (float("inf"), float("-inf")):
        return 0.0
    return result


def _nullable_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _numbers(value) -> list[float]:
    if not isinstance(value, list):
        return []
    return [number for number in (_nullable_number(item) for item in value) if number is not None]


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return False
