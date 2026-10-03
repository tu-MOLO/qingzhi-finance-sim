"""智能体的工具集。

每个工具是一个纯函数：接收上下文，产出一个 ToolOutcome，并把结构化结果写入
上下文共享区供生成器取用。工具只读取传入的上下文，不访问数据库、不发网络请求。

工具按类别分为两类：
  · guard 类在文本生成之后执行，用于合规校验；
  · 其余在生成之前执行，为生成准备素材。
"""

from __future__ import annotations

import re
from collections.abc import Callable

from .protocol import (
    STEP_FAILED,
    STEP_OK,
    STEP_REPLACED,
    STEP_SKIPPED,
    AgentContext,
    ToolOutcome,
)

# 任何阿拉伯数字都视为量化输出，用于无目标时的合规判定
_NUMBER_PATTERN = re.compile(r"[0-9]")

# 一次解读最多纳入的目标数。录入侧上限是五个，这里留出余量
_MAX_GOALS = 12

# 分句用的标点。合规判定以「句」为单位，否定词只在同句内才生效
_CLAUSE_SPLIT = re.compile(r"[，。；：！？、,.;:!?\n（）()]")

TOOL_HANDLERS: dict[str, Callable[[AgentContext], ToolOutcome]] = {}


def _forbidden_phrases(settings: dict) -> tuple[str, ...]:
    """收益承诺类措辞的清单。来源是配置项，由应用层注入 settings。

    匹配方式是整句内的子串包含，不做分词也不要求词边界，
    因此像「保证收益」这样的短语只要出现就进入判定。
    """
    raw = settings.get("agent.forbidden_phrases")
    if not isinstance(raw, str) or not raw.strip():
        return ()
    return tuple(phrase.strip() for phrase in raw.split(",") if phrase.strip())


def _exemption_marks(settings: dict) -> tuple[str, ...]:
    """否定语境的标记词。命中措辞所在的句子里出现这些词，说明原意是否定而不是承诺。"""
    raw = settings.get("agent.compliance_exemptions")
    if not isinstance(raw, str) or not raw.strip():
        return ()
    return tuple(mark.strip() for mark in raw.split(",") if mark.strip())


def first_violation(text: str, phrases: tuple[str, ...],
                    exemptions: tuple[str, ...]) -> str | None:
    """按句找出第一个真正构成承诺的措辞。

    逐句判定而不是整段判定：「不是你能拿到的保证收益」这类风险提示
    用的是同一个短语，语义却完全相反，整段扫描会把它当成违规。
    """
    for clause in _CLAUSE_SPLIT.split(text or ""):
        for phrase in phrases:
            if phrase not in clause:
                continue
            if any(mark in clause for mark in exemptions):
                continue
            return phrase
    return None


def register(code: str):
    def wrapper(func: Callable[[AgentContext], ToolOutcome]):
        TOOL_HANDLERS[code] = func
        return func
    return wrapper


def available_tools() -> frozenset[str]:
    return frozenset(TOOL_HANDLERS)


# ---------------------------------------------------------------- 格式化助手


def format_amount(value: float | None) -> str:
    """金额的中文呈现。满一万元换算为万元并保留一位小数，否则保留元。"""
    if value is None:
        return "—"
    amount = float(value)
    if abs(amount) >= 10000:
        return f"{amount / 10000:.1f} 万元"
    return f"{round(amount):,} 元"


def format_months(value: float | None) -> str:
    if value is None:
        return "尚未达成"
    return f"第 {round(float(value))} 个月"


def clause_of_delay(median: float | None, due: float | None) -> str:
    """把达成月与到期月的差写成一句中文，未达成时不伪造数字。"""
    if median is None:
        return "该目标在推演期内已有多数路径未能达成"
    if due is None:
        return f"中位达成时刻为第 {round(median)} 个月"
    delay = round(float(median) - float(due))
    if delay > 0:
        return f"预计推迟约 {delay} 个月"
    return f"按期达成，中位达成时刻为第 {round(median)} 个月"


# ---------------------------------------------------------------- 检索类


@register("corpus_lookup")
def corpus_lookup(ctx: AgentContext) -> ToolOutcome:
    """取出该术语关联的语料文档，按需截取正文摘录。"""
    term = ctx.term or {}
    docs = term.get("source_documents") or []
    items: list[dict] = []
    for doc in docs:
        content = (doc.get("content") or "").strip()
        excerpt = content if len(content) <= 240 else content[:240] + "……"
        items.append({
            "docCode": doc.get("doc_code"),
            "docType": doc.get("doc_type"),
            "docTypeName": doc.get("doc_type_name") or doc.get("doc_type"),
            "title": doc.get("title"),
            "sourceUrl": doc.get("source_url"),
            "fetchedAt": doc.get("fetched_at"),
            "excerpt": excerpt,
        })
    ctx.shared["corpus"] = items
    if not items:
        return ToolOutcome(True, "该说法暂未关联语料", status=STEP_SKIPPED,
                           data={"count": 0})
    kinds = len({item["docType"] for item in items})
    return ToolOutcome(True, f"命中 {len(items)} 份语料，覆盖 {kinds} 类文档",
                       data={"count": len(items), "kinds": kinds})


# ---------------------------------------------------------------- 上下文类


def _goal_entry(goal: dict, index: int) -> dict:
    """把一个目标整理成生成器可直接引用的形状，数字先转成中文表述。"""
    amount = _as_float(goal.get("amount")) or 0.0
    due = _as_float(goal.get("dueMonth"))
    median = _as_float(goal.get("hitMonthP50"), default=None)
    probability = _as_float(goal.get("hitProbability"))
    gap = _as_float(goal.get("gapAmount")) or 0.0
    return {
        "goalId": str(goal.get("goalId"))[:64],
        "name": str(goal.get("name"))[:64],
        "priority": int(_as_float(goal.get("priority")) or index + 1),
        "amount": amount,
        "amountText": format_amount(amount),
        "dueMonth": None if due is None else round(due),
        "medianMonth": None if median is None else round(median),
        "probability": probability,
        "probabilityText": "—" if probability is None else f"{probability * 100:.1f}%",
        "hitTier": "偏低" if (probability or 0) < 0.5 else "尚可",
        "delayClause": clause_of_delay(median, due),
        "reachedRate": _as_float(goal.get("reachedRate")),
        "gapAmount": gap,
        "gapText": format_amount(gap) if gap > 0 else "已覆盖",
    }


@register("simulation_context")
def simulation_context(ctx: AgentContext) -> ToolOutcome:
    """从摘要中取出全部目标与风险容量结论。

    主目标仍然单独挂在 goal 上，供只关心首要目标的环节取用；
    goals 按优先级给出完整清单，解读因此能逐个讲到而不是只讲第一个。
    摘要缺失即按无目标口径处理。
    """
    snapshot = ctx.snapshot or {}
    raw_goals = snapshot.get("goals")
    if not isinstance(raw_goals, list) or not raw_goals:
        primary = snapshot.get("primaryGoal")
        raw_goals = [primary] if isinstance(primary, dict) else []

    entries = [_goal_entry(goal, index)
               for index, goal in enumerate(raw_goals[:_MAX_GOALS])
               if isinstance(goal, dict) and goal.get("name") and goal.get("goalId")]
    entries.sort(key=lambda item: item["priority"])

    ctx.shared["goals"] = entries
    ctx.shared["goal"] = entries[0] if entries else None
    if not entries:
        ctx.shared["capacity"] = None
        return ToolOutcome(True, "未带来用户目标，按无目标口径处理",
                           status=STEP_SKIPPED, data={"hasGoal": False})

    capacity = snapshot.get("capacity")
    if isinstance(capacity, dict) and capacity.get("level"):
        cap = _as_float(capacity.get("finalCap")) or 0.0
        ctx.shared["capacity"] = {
            "level": str(capacity.get("level"))[:32],
            "finalCap": cap,
            "finalCapText": f"{cap * 100:.0f}%",
            "cushionMonths": _as_float(capacity.get("cushionMonths")),
            "dipMonths": [int(item) for item in (capacity.get("dipMonths") or [])][:12],
        }
    else:
        ctx.shared["capacity"] = None

    head = entries[0]
    detail = (f"共 {len(entries)} 个目标，主目标为{head['name']}，"
              f"目标金额 {head['amountText']}，按期达成概率 {head['probabilityText']}")
    if len(entries) > 1:
        rest = "、".join(f"{item['name']}（{item['probabilityText']}）" for item in entries[1:])
        detail += f"；其余目标：{rest}"
    return ToolOutcome(True, detail, data={"hasGoal": True, "goalCount": len(entries)})


def _scenario_bucket(scenarios: dict, goal_id: str) -> dict | None:
    """取某个目标在三档情景下的达成概率与高低差距。"""
    values: dict[str, float] = {}
    for label in ("pessimistic", "base", "optimistic"):
        bucket = scenarios.get(label)
        if isinstance(bucket, dict):
            value = _as_float(bucket.get(goal_id))
            if value is not None:
                values[label] = value
    if not values:
        return None

    spread = None
    if "pessimistic" in values and "optimistic" in values:
        spread = values["optimistic"] - values["pessimistic"]
    return {
        "values": {key: round(value, 4) for key, value in values.items()},
        "spread": None if spread is None else round(spread, 4),
        "spreadText": None if spread is None else f"{spread * 100:.1f} 个百分点",
        "pessimisticText": None if "pessimistic" not in values else f"{values['pessimistic'] * 100:.1f}%",
        "baseText": None if "base" not in values else f"{values['base'] * 100:.1f}%",
        "optimisticText": None if "optimistic" not in values else f"{values['optimistic'] * 100:.1f}%",
    }


@register("scenario_compare")
def scenario_compare(ctx: AgentContext) -> ToolOutcome:
    """取三档情景下各目标的达成概率。

    主目标的结果仍放在顶层，其余目标按编号挂在 byGoal 下，
    这样解读讲到第二个、第三个目标时也拿得到对应的情景区间。
    """
    snapshot = ctx.snapshot or {}
    scenarios = snapshot.get("scenarios")
    goals = ctx.shared.get("goals") or []
    if not isinstance(scenarios, dict) or not goals:
        ctx.shared["scenarios"] = None
        return ToolOutcome(True, "本次调用未带来情景对比数据", status=STEP_SKIPPED,
                           data={"hasScenarios": False})

    by_goal: dict[str, dict] = {}
    for entry in goals:
        bucket = _scenario_bucket(scenarios, entry["goalId"])
        if bucket:
            bucket["name"] = entry["name"]
            by_goal[entry["goalId"]] = bucket

    if not by_goal:
        ctx.shared["scenarios"] = None
        return ToolOutcome(True, "情景数据中未包含任何目标", status=STEP_SKIPPED,
                           data={"hasScenarios": False})

    primary = by_goal.get(goals[0]["goalId"]) or next(iter(by_goal.values()))
    primary = dict(primary)
    primary["byGoal"] = by_goal
    ctx.shared["scenarios"] = primary
    return ToolOutcome(True, f"已取得 {len(by_goal)} 个目标的三档情景概率",
                       data={"hasScenarios": True, "goalCount": len(by_goal)})


@register("allocation_profile")
def allocation_profile(ctx: AgentContext) -> ToolOutcome:
    """取四账户的期末结构与分配顺序，判断安全底座是否已填满。"""
    snapshot = ctx.snapshot or {}
    allocation = snapshot.get("allocation")
    if not isinstance(allocation, dict) or not allocation.get("accounts"):
        ctx.shared["allocation"] = None
        return ToolOutcome(True, "本次调用未带来账户分配数据", status=STEP_SKIPPED,
                           data={"hasAllocation": False})

    series = allocation.get("series") or {}
    names = {item.get("code"): item.get("name")
             for item in allocation.get("accounts", []) if isinstance(item, dict)}
    order = [str(code) for code in (allocation.get("order") or [])]
    emergency_target = _as_float(allocation.get("emergencyTarget"))

    ends: list[dict] = []
    safe_end = 0.0
    for code in order:
        values = series.get(code)
        end = _as_float(values[-1]) if isinstance(values, list) and values else 0.0
        if code == "safe":
            safe_end = end or 0.0
        ends.append({"code": code, "name": names.get(code, code),
                     "end": end or 0.0, "endText": format_amount(end)})

    ctx.shared["allocation"] = {
        "order": order,
        "ends": ends,
        "emergencyTarget": emergency_target,
        "emergencyTargetText": format_amount(emergency_target),
        "safeFilled": emergency_target is not None and safe_end >= emergency_target - 1e-6,
        "conservationOk": bool(allocation.get("conservationOk", True)),
        "priorityOk": bool(allocation.get("priorityOk", True)),
    }
    state = "已填满" if ctx.shared["allocation"]["safeFilled"] else "尚未填满"
    return ToolOutcome(True, f"安全底座{state}，账户顺序为{'、'.join(names.get(c, c) for c in order)}",
                       data={"hasAllocation": True})


# ---------------------------------------------------------------- 格式化类


def _numeric_of(goal: dict, ratio: float, cap_text: str | None) -> dict:
    """单个目标的换算结果：金额、回撤示例、达成与到期月。"""
    amount = goal["amount"]
    return {
        "goalId": goal["goalId"],
        "name": goal["name"],
        "amount": amount,
        "amountText": goal["amountText"],
        "loss": amount * ratio,
        "lossText": format_amount(amount * ratio),
        "lossRatioText": f"{ratio * 100:.0f}%",
        "medianText": format_months(goal.get("medianMonth")),
        "dueText": format_months(goal.get("dueMonth")),
        "delayClause": goal.get("delayClause"),
        "capText": cap_text,
    }


@register("amount_formatter")
def amount_formatter(ctx: AgentContext) -> ToolOutcome:
    """把上下文中每个目标的金额与月数预先生成中文表述，供生成器直接引用。

    numeric 仍指向首要目标，供只讲一个目标的环节取用；
    numerics 按优先级给出全部目标，术语解释因此能顺带交代「同样的幅度落在其他目标上是多少」。
    """
    goals = ctx.shared.get("goals") or []
    goal = ctx.shared.get("goal")
    if not goal and goals:
        goal = goals[0]
    if not goal:
        ctx.shared["numeric"] = None
        ctx.shared["numerics"] = []
        return ToolOutcome(True, "无金额需要换算", status=STEP_SKIPPED, data={})

    drawdown_ratio = _as_float(ctx.settings.get("explain.drawdown_reference_ratio")) or 0.0
    cap_text = (ctx.shared.get("capacity") or {}).get("finalCapText")
    # goals 已按优先级排好，直接沿用同一顺序，numerics 与解读里的先后才一致
    entries = [_numeric_of(item, drawdown_ratio, cap_text) for item in goals or [goal]]
    ctx.shared["numeric"] = next((item for item in entries if item["goalId"] == goal["goalId"]),
                                 entries[0])
    ctx.shared["numerics"] = entries
    return ToolOutcome(True,
                       f"已换算 {len(entries)} 个目标的金额与风险幅度，回撤示例取 {drawdown_ratio * 100:.0f}%",
                       data={"lossRatio": drawdown_ratio, "goalCount": len(entries)})


# ---------------------------------------------------------------- 校验类


@register("compliance_guard")
def compliance_guard(ctx: AgentContext) -> ToolOutcome:
    """对已生成的文本做合规校验。

    三条硬约束：未设置目标时不得出现任何数字；不得出现收益承诺类措辞；
    任何输出都必须附带免责提示。命中前两条时以合规文案替换，
    第三条由生成器补齐，此处只判定。

    措辞判定逐句进行，并放过否定语境：词条库里「不是你能拿到的保证收益」
    这类风险提示与承诺用的是同一个短语，按整段子串匹配会被误判。
    """
    output = ctx.shared.get("output")
    if not isinstance(output, dict):
        return ToolOutcome(False, "生成结果缺失，无法校验", status=STEP_FAILED, data={})

    has_goal = bool(ctx.shared.get("goal") or ctx.shared.get("goals"))
    texts = [value for value in output.values() if isinstance(value, str)]
    texts += [item for value in output.values() if isinstance(value, list) for item in value
              if isinstance(item, str)]
    joined = "\n".join(texts)

    replaced = False
    detail = "输出通过合规校验"
    if not has_goal and _NUMBER_PATTERN.search(joined):
        # 无目标时出现数字，整段替换为固定合规文案
        safe = ctx.message("compliance.no_goal", "")
        if not safe:
            return ToolOutcome(False, "缺少无目标时的合规文案", status=STEP_FAILED, data={})
        for key in list(output.keys()):
            output[key] = safe if isinstance(output[key], str) else []
        ctx.shared["output"] = output
        replaced = True
        detail = "未设置目标却出现数字，已替换为固定合规文案"

    phrases = _forbidden_phrases(ctx.settings)
    phrase = first_violation(joined, phrases, _exemption_marks(ctx.settings))
    if phrase:
        return ToolOutcome(False, f"输出中出现不合规措辞：{phrase}",
                           status=STEP_FAILED, data={"phrase": phrase})

    if not output.get("disclaimer"):
        output["disclaimer"] = ctx.message("disclaimer.term", "")
        output["disclaimerTitle"] = ctx.message_title("disclaimer.term", "")
        ctx.shared["output"] = output

    if replaced:
        return ToolOutcome(True, detail, status=STEP_REPLACED, data={"replaced": True})
    return ToolOutcome(True, detail, status=STEP_OK, data={"replaced": False})


# ---------------------------------------------------------------- 工具函数


def _as_float(value, default: float | None = 0.0) -> float | None:
    if value is None or isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result or result in (float("inf"), float("-inf")):
        return default
    return result
