"""画像的归一化、校验与转换。

取值区间的上下界来自数据库配置，收入来源的类型与必填字段来自字典表，
因此新增一类收入来源只需要往字典里加一条记录，不需要改代码。
"""

from __future__ import annotations

from typing import Any

from ..common.errors import ValidationError
from ..domain.models import Expense, Goal, IncomeSource, Profile
from .configuration import Catalog


def _number(value: Any, default: float, field: str, label: str) -> float:
    if value is None or value == "":
        return float(default)
    if isinstance(value, bool):
        raise ValidationError(field, f"{label}需要填写数字", code="P-01-04")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        text = str(value)[:20]
        raise ValidationError(field, f"{label}需要填写数字，当前填写为「{text}」", code="P-01-04") from exc
    if result != result or result in (float("inf"), float("-inf")):
        raise ValidationError(field, f"{label}的取值无效", code="P-01-04")
    return result


def _integer(value: Any, default: int, field: str, label: str) -> int:
    number = _number(value, default, field, label)
    if number != int(number):
        # 静默截断会让使用者以为自己填的数字生效了，这里明确要求整数
        raise ValidationError(field, f"{label}需要填写整数", code="P-01-04")
    return int(number)


def normalize(raw: dict, catalog: Catalog) -> dict:
    """把外部传入的松散结构整理成内部结构。枚举一律使用字典编码。"""
    raw = raw or {}
    bounds = catalog.domain.bounds
    months = _integer(raw.get("months"), bounds.default_months, "months", "推演时长")

    provided = {item.get("source_type"): item for item in (raw.get("income_sources") or [])
                if isinstance(item, dict)}
    sources: list[dict] = []
    for definition in catalog.dict_items("income_source"):
        code = definition["code"]
        attributes = definition.get("attributes") or {}
        item = provided.get(code, {})
        deterministic = attributes.get("distribution") == "fixed"
        prefix = f"sources.{code}.amount_low"
        low = _number(item.get("amount_low"), 0.0, prefix, f"{definition['name']}金额下限")
        high = _number(item.get("amount_high"), low, f"sources.{code}.amount_high",
                       f"{definition['name']}金额上限")
        sources.append({
            "source_type": code,
            "enabled": True if deterministic else bool(item.get("enabled", False)),
            "probability": 1.0 if deterministic else _number(
                item.get("probability"), 0.0, f"sources.{code}.probability",
                f"{definition['name']}参与概率"),
            "amount_low": low,
            "amount_mid": _number(item.get("amount_mid"), (low + high) / 2,
                                  f"sources.{code}.amount_mid", f"{definition['name']}金额中值"),
            "amount_high": high,
            "start_month": _integer(item.get("start_month"), 1,
                                    f"sources.{code}.start_month", f"{definition['name']}起始月份"),
            "end_month": _integer(item.get("end_month"), months,
                                  f"sources.{code}.end_month", f"{definition['name']}结束月份"),
            "interrupt_prob": 0.0 if not attributes.get("has_interrupt") else _number(
                item.get("interrupt_prob"), 0.0, f"sources.{code}.interrupt_prob",
                f"{definition['name']}中断概率"),
        })

    goals: list[dict] = []
    for index, item in enumerate(raw.get("goals") or []):
        if not isinstance(item, dict):
            raise ValidationError("goals", "目标内容格式不正确", code="P-01-06")
        prefix = f"goals[{index}]"
        goals.append({
            "goal_id": str(item.get("goal_id") or f"g{index + 1}")[:64],
            "name": str(item.get("name") or "").strip()[:64],
            "amount": _number(item.get("amount"), 0.0, prefix + ".amount", "目标金额"),
            "due_month": _integer(item.get("due_month"), months, prefix + ".due_month", "到期月份"),
            "priority": _integer(item.get("priority"), index + 1, prefix + ".priority", "优先级"),
        })

    provided_expenses = {item.get("category"): item for item in (raw.get("expenses") or [])
                         if isinstance(item, dict)}
    expenses: list[dict] = []
    for definition in catalog.dict_items("expense_category"):
        code = definition["code"]
        attributes = definition.get("attributes") or {}
        item = provided_expenses.get(code, {})
        expenses.append({
            "category": code,
            "amount": _number(item.get("amount"), float(attributes.get("default_amount", 0)),
                             f"expenses.{code}.amount", f"{definition['name']}金额"),
            "essential": bool(attributes.get("essential", False)),
            "growth_rate": _number(item.get("growth_rate"),
                                   float(attributes.get("default_growth", 0)),
                                   f"expenses.{code}.growth_rate", f"{definition['name']}年增长率"),
            "enabled": bool(item.get("enabled", True)),
        })

    budget = raw.get("budget") or {}
    return {
        "profile_id": str(raw.get("profile_id") or "custom")[:64],
        "name": str(raw.get("name") or "").strip()[:64],
        "grade": str(raw.get("grade") or ""),
        "living_cost": _number(raw.get("living_cost"), 0.0, "living_cost", "家庭支持"),
        "living_growth": _number(raw.get("living_growth"), 0.0, "living_growth", "家庭支持年增长率"),
        "initial_balance": _number(raw.get("initial_balance"), 0.0, "initial_balance", "现有积蓄"),
        "risk_appetite": str(raw.get("risk_appetite") or ""),
        "months": months,
        "paths": _integer(raw.get("paths"), bounds.default_paths, "paths", "仿真次数"),
        "seed": _integer(raw.get("seed"), bounds.default_seed, "seed", "随机种子"),
        "income_sources": sources,
        "goals": goals,
        "expenses": expenses,
        "budget": {
            "growth_monthly": _number(budget.get("growth_monthly"), 0.0,
                                      "budget.growth_monthly", "成长悦己月度上限"),
            "treat_monthly": _number(budget.get("treat_monthly"), 0.0,
                                     "budget.treat_monthly", "体验悦己月度上限"),
        },
    }


def enabled_income_total(profile: dict) -> float:
    """已启用收入来源的月度金额合计，用于放宽「家庭支持必须大于零」的旧校验。"""
    total = 0.0
    for item in profile["income_sources"]:
        if item.get("enabled"):
            total += max(0.0, float(item.get("amount_mid") or 0.0))
    return total


def validate(profile: dict, catalog: Catalog) -> None:
    bounds = catalog.domain.bounds
    months = profile["months"]
    if not (bounds.min_months <= months <= bounds.max_months):
        raise ValidationError("months", f"推演时长需在 {bounds.min_months} 到 {bounds.max_months} 个月之间",
                              code="P-01-03")

    paths = profile["paths"]
    if not (bounds.min_paths <= paths <= bounds.max_paths):
        raise ValidationError("paths", f"仿真次数需在 {bounds.min_paths} 到 {bounds.max_paths} 之间",
                              code="P-01-03")
    if paths * months > bounds.max_path_months:
        raise ValidationError("paths",
                              f"仿真次数与推演时长的乘积不能超过 {bounds.max_path_months:,}，请调低其中一项",
                              code="P-01-03")

    if profile["grade"] not in catalog.dict_codes("grade"):
        raise ValidationError("grade", "年级的取值不在允许范围内", code="P-01-05")
    if profile["risk_appetite"] not in catalog.dict_codes("risk_appetite"):
        raise ValidationError("risk_appetite", "风险偏好档位的取值不在允许范围内", code="P-01-05")

    if profile["living_cost"] < 0:
        raise ValidationError("living_cost", "家庭支持不能为负，请检查该字段", code="P-01-01")
    # 不再要求家庭支持大于零：已工作、不再向家里要钱的用户靠其他收入来源即可推演
    if profile["living_cost"] <= 0 and enabled_income_total(profile) <= 0:
        raise ValidationError("income_sources",
                              "至少要有一项收入来源的金额大于零，或填写家庭支持", code="P-01-01")
    if not (0.0 <= profile["living_growth"] <= 0.1):
        raise ValidationError("living_growth", "生活费年增长率需在零到零点一之间", code="P-01-02")
    if profile["initial_balance"] < 0:
        raise ValidationError("initial_balance", "现有积蓄不能为负", code="P-01-01")

    allowed_sources = catalog.dict_codes("income_source")
    enabled_sources = [item for item in profile["income_sources"] if item["enabled"]]
    if len(enabled_sources) > bounds.max_income_sources:
        raise ValidationError("income_sources",
                              f"启用的收入来源不能超过 {bounds.max_income_sources} 类，请关闭其中一部分",
                              code="P-01-03")
    for item in profile["income_sources"]:
        code = item["source_type"]
        if code not in allowed_sources:
            raise ValidationError("income_sources", f"收入来源 {code} 不在字典定义内", code="P-01-05")
        prefix = f"sources.{code}"
        label = catalog.dict_name("income_source", code, code)
        if not (0.0 <= item["probability"] <= 1.0):
            raise ValidationError(prefix + ".probability", f"{label}的参与概率需在零到一之间", code="P-01-02")
        if not (0.0 <= item["interrupt_prob"] <= 1.0):
            raise ValidationError(prefix + ".interrupt_prob", f"{label}的中断概率需在零到一之间", code="P-01-02")
        if min(item["amount_low"], item["amount_mid"], item["amount_high"]) < 0:
            raise ValidationError(prefix + ".amount_low", f"{label}的金额不能为负", code="P-01-02")
        if not (item["amount_low"] <= item["amount_mid"] <= item["amount_high"]):
            raise ValidationError(prefix + ".amount_high",
                                  f"{label}的金额区间需满足下限不大于中值、中值不大于上限",
                                  code="P-01-02")
        if item["start_month"] < 1 or item["end_month"] > months or item["start_month"] > item["end_month"]:
            raise ValidationError(prefix + ".start_month",
                                  f"{label}的起止月份需落在推演范围内，且起始不晚于结束",
                                  code="P-01-03")

    goals = profile["goals"]
    if not (1 <= len(goals) <= bounds.max_goals):
        raise ValidationError("goals", f"人生目标数量需在 1 到 {bounds.max_goals} 个之间", code="P-01-03")
    seen: set[str] = set()
    for index, goal in enumerate(goals):
        field = f"goals[{index}]"
        if not goal["name"]:
            raise ValidationError(field + ".name", "目标名称不能为空", code="P-01-01")
        if goal["goal_id"] in seen:
            raise ValidationError(field + ".goal_id", "目标标识不能重复", code="P-01-05")
        seen.add(goal["goal_id"])
        if goal["amount"] <= 0:
            raise ValidationError(field + ".amount", "目标金额必须大于零", code="P-01-01")
        if not (1 <= goal["due_month"] <= months):
            raise ValidationError(field + ".due_month",
                                  f"目标的到期月份超出了当前的推演范围（当前 {months} 个月），"
                                  f"请调整月份或延长推演时长", code="P-01-03")
        if goal["priority"] < 1:
            raise ValidationError(field + ".priority", "优先级需为不小于一的正整数", code="P-01-01")

    for key, label in (("growth_monthly", "成长悦己"), ("treat_monthly", "体验悦己")):
        if profile["budget"][key] < 0:
            raise ValidationError("budget." + key, f"{label}的月度上限不能为负", code="P-01-02")


def to_domain(profile: dict, catalog: Catalog) -> Profile:
    sources = []
    for item in profile["income_sources"]:
        attributes = {}
        for definition in catalog.dict_items("income_source"):
            if definition["code"] == item["source_type"]:
                attributes = definition.get("attributes") or {}
                break
        sources.append(IncomeSource(
            source_type=item["source_type"],
            name=catalog.dict_name("income_source", item["source_type"], item["source_type"]),
            enabled=bool(item["enabled"]),
            probability=float(item["probability"]),
            amount_low=float(item["amount_low"]),
            amount_mid=float(item["amount_mid"]),
            amount_high=float(item["amount_high"]),
            start_month=int(item["start_month"]),
            end_month=int(item["end_month"]),
            interrupt_prob=float(item["interrupt_prob"]),
            distribution=str(attributes.get("distribution", "fixed")),
            has_probability=bool(attributes.get("has_probability")),
            has_interrupt=bool(attributes.get("has_interrupt")),
            has_window=bool(attributes.get("has_window")),
        ))
    goals = [Goal(goal_id=item["goal_id"], name=item["name"], amount=float(item["amount"]),
                  due_month=int(item["due_month"]), priority=int(item["priority"]))
             for item in profile["goals"]]
    expenses = [Expense(category=item["category"],
                        name=catalog.dict_name("expense_category", item["category"], item["category"]),
                        amount=float(item["amount"]), essential=bool(item["essential"]),
                        growth_rate=float(item["growth_rate"]), enabled=bool(item["enabled"]))
                for item in profile["expenses"]]
    return Profile(
        profile_id=profile["profile_id"] or "custom",
        name=profile["name"] or "自定义画像",
        grade=profile["grade"],
        living_cost=float(profile["living_cost"]),
        living_growth=float(profile["living_growth"]),
        initial_balance=float(profile["initial_balance"]),
        risk_appetite=profile["risk_appetite"],
        months=int(profile["months"]),
        paths=int(profile["paths"]),
        seed=int(profile["seed"]),
        growth_budget=float(profile["budget"]["growth_monthly"]),
        treat_budget=float(profile["budget"]["treat_monthly"]),
        income_sources=tuple(sources),
        expenses=tuple(expenses),
        goals=tuple(goals),
    )


def normalize_and_validate(raw: dict, catalog: Catalog) -> Profile:
    normalized = normalize(raw, catalog)
    validate(normalized, catalog)
    return to_domain(normalized, catalog)


def preview(raw: dict, catalog: Catalog) -> dict:
    """结余预览。期望收入的口径属于业务逻辑，因此放在服务端计算。"""
    profile = normalize_and_validate(raw, catalog)
    estimated = 0.0
    for source in profile.income_sources:
        if not source.enabled:
            continue
        middle = (source.amount_low + source.amount_high) / 2
        if source.distribution == "fixed":
            estimated += middle
        elif source.distribution == "monthly_random":
            estimated += source.probability * (1 - source.interrupt_prob) * middle
        elif source.distribution == "annual_lump":
            estimated += source.probability * middle / 12
        elif source.distribution == "segmented":
            span = max(0, min(source.end_month, profile.months) - source.start_month + 1)
            estimated += (1 - source.interrupt_prob) * middle * span / profile.months

    total_expense = sum(expense.amount for expense in profile.expenses if expense.enabled)
    need = sum(expense.amount for expense in profile.expenses
               if expense.enabled and expense.essential)
    available = estimated - total_expense

    return {
        "expected_income": round(estimated, 2),
        "total_expense": round(total_expense, 2),
        "need_monthly": round(need, 2),
        "available": round(available, 2),
        "emergency_target": round(need * catalog.domain.model.emergency_months, 2),
        "within_budget": available >= 0,
    }
