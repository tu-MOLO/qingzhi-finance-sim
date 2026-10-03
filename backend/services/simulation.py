"""推演用例：把画像变成完整结果。

随机路径按画像指纹缓存，同一份输入重复推演时直接复用，
既保证结果可复现，也避免反复生成路径。
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict

from ..common.errors import AppError
from ..domain import allocation as allocation_domain
from ..domain import capacity as capacity_domain
from ..domain import planner as planner_domain
from ..domain import simulation as simulation_domain
from ..domain.models import PathSet, Profile, ReportConfig
from .configuration import Catalog

_PATH_CACHE: OrderedDict[str, PathSet] = OrderedDict()
_CACHE_LIMIT = 8


def _fingerprint(profile: Profile, catalog: Catalog) -> str:
    """缓存键必须覆盖一切会改变路径或固定支出的输入。"""
    model = catalog.domain.model
    payload = {
        "seed": profile.seed,
        "months": profile.months,
        "paths": profile.paths,
        "living_cost": profile.living_cost,
        "living_growth": profile.living_growth,
        "growth_budget": profile.growth_budget,
        "sources": [(item.source_type, item.enabled, item.probability, item.amount_low,
                     item.amount_high, item.start_month, item.end_month, item.interrupt_prob,
                     item.distribution)
                    for item in profile.income_sources],
        "expenses": [(item.category, item.enabled, item.amount, item.essential,
                      item.growth_rate)
                     for item in profile.expenses],
        "sudden_freq_per_year": model.sudden_freq_per_year,
        "sudden_low": model.sudden_low,
        "sudden_high": model.sudden_high,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def get_paths(profile: Profile, catalog: Catalog) -> tuple[PathSet, bool]:
    key = _fingerprint(profile, catalog)
    cached = _PATH_CACHE.get(key)
    if cached is not None:
        _PATH_CACHE.move_to_end(key)
        return cached, True
    paths = simulation_domain.build_paths(profile, catalog.domain)
    _PATH_CACHE[key] = paths
    while len(_PATH_CACHE) > _CACHE_LIMIT:
        _PATH_CACHE.popitem(last=False)
    return paths, False


def report_config(catalog: Catalog) -> ReportConfig:
    """逐路径明细的采样口径。缺失时回落默认值，不阻断推演。"""
    return ReportConfig(
        path_samples=int(_optional_setting(catalog, "report.path_samples", 24)),
        histogram_bins=int(_optional_setting(catalog, "report.histogram_bins", 20)),
    )


def _optional_setting(catalog: Catalog, key: str, default: float) -> float:
    try:
        value = float(catalog.settings.get(key))
    except (TypeError, ValueError):
        return default
    return default if value <= 0 else value


def clear_cache() -> None:
    _PATH_CACHE.clear()


def _serialize_simulation(sim) -> dict:
    return {
        "seed": sim.seed,
        "months": sim.months,
        "paths": sim.paths,
        "treatMonthly": sim.treat_monthly,
        "balancePercentiles": {"p10": sim.balance_p10, "p50": sim.balance_p50, "p90": sim.balance_p90},
        "pathSamples": sim.path_samples,
        "endBalanceHistogram": sim.end_balance_histogram,
        "endBalancePercentiles": sim.end_balance_percentiles,
        "reachCurves": sim.reach_curves,
        "goalResults": [{
            "goalId": goal.goal_id, "name": goal.name, "amount": goal.amount,
            "dueMonth": goal.due_month, "priority": goal.priority,
            "hitProbability": goal.hit_probability, "reachedRate": goal.reached_rate,
            "hitMonthP10": goal.hit_month_p10, "hitMonthP50": goal.hit_month_p50,
            "hitMonthP90": goal.hit_month_p90, "gapAmount": goal.gap_amount,
            "shortfallPaths": goal.shortfall_paths,
        } for goal in sim.goal_results],
        "deficitMonthsP10": sim.deficit_months_p10,
        "deficitMonthsP50": sim.deficit_months_p50,
        "deficitPeakMonths": [
            {"month": month, "paths": count} for month, count in sim.deficit_peak_months],
        "deficitTotal": sim.deficit_total,
        "deficitPaths": sim.deficit_paths,
        "medianEndBalance": sim.median_end_balance,
        "needMonthly": sim.need_monthly,
        "incomeCv": sim.income_cv,
        "emergencyTarget": sim.emergency_target,
    }


def _serialize_allocation(allocation, catalog: Catalog) -> dict:
    colors = catalog.domain.account_colors
    names = catalog.domain.account_names
    return {
        "monthly": allocation.monthly,
        "series": allocation.series,
        "totals": allocation.totals,
        "accounts": [{"code": code, "name": names.get(code, code), "color": colors.get(code, "")}
                     for code in allocation.order],
        "conservationOk": allocation.conservation_ok,
        "priorityOk": allocation.priority_ok,
        "emergencyTarget": allocation.emergency_target,
        "order": allocation.order,
    }


def _serialize_capacity(capacity) -> dict:
    current = capacity.current
    return {
        "current": {
            "month": current["month"],
            "cushionMonths": current["cushion_months"],
            "rigidity": current["rigidity"],
            "incomeCv": current["income_cv"],
            "rawScore": current["raw_score"],
            "levelCode": current["level_code"],
            "level": current["level"],
            "levelCap": current["level_cap"],
            "appetiteCap": current["appetite_cap"],
            "finalCap": current["final_cap"],
        },
        "calendar": [{
            "month": item["month"],
            "cushionMonths": item["cushion_months"],
            "pendingAmount": item["pending_amount"],
            "rigidity": item["rigidity"],
            "levelCode": item["level_code"],
            "level": item["level"],
            "levelCap": item["level_cap"],
            "appetiteCap": item["appetite_cap"],
            "finalCap": item["final_cap"],
        } for item in capacity.calendar],
        "dipMonths": capacity.dip_months,
        "cushionMin": capacity.cushion_min,
        "cushionMax": capacity.cushion_max,
        "levels": [{
            "code": item["code"], "name": item["name"],
            "minCushionMonths": item["min_cushion_months"], "equityCap": item["equity_cap"],
        } for item in capacity.levels],
    }


# 方案语义状态到文案键的映射。领域层只返回状态，文案由这里从文案表取，
# 保证方案标题与说明不会散落在代码里。
_PLAN_COPY = {
    "compress_keep": ("plan.title.compress_keep", "plan.message.compress_keep"),
    "compress_feasible": ("plan.title.compress_feasible", "plan.message.compress_feasible"),
    "compress_infeasible": ("plan.title.compress_infeasible", "plan.message.compress_infeasible"),
    "compress_zero": ("plan.title.compress_infeasible", "plan.message.compress_zero"),
    "postpone": ("plan.title.postpone", None),
}


def _serialize_plan(plan: dict, catalog: Catalog) -> dict:
    """方案结果统一转为接口使用的驼峰命名，标题与说明取自文案表。"""
    def pack(item: dict) -> dict:
        variant = item.get("variant") or item["plan_type"]
        title_key, message_key = _PLAN_COPY.get(variant, (None, None))
        return {
            "planId": item["plan_id"],
            "planType": item["plan_type"],
            "title": catalog.text(title_key) if title_key else "",
            "feasible": item["feasible"],
            "keepCurrent": item.get("keep_current", False),
            "treatMonthly": item["treat_monthly"],
            "deltaAmount": item["delta_amount"],
            "achievedProbability": item["achieved_probability"],
            "bestProbability": item.get("best_probability"),
            "delayMonths": item["delay_months"],
            "medianHitMonth": item.get("median_hit_month"),
            "beyondHorizon": bool(item.get("beyond_horizon", False)),
            "iterations": item["iterations"],
            "message": catalog.text(message_key) if message_key else "",
        }

    return {
        "goalId": plan["goal_id"],
        "goal": {
            "goalId": plan["goal"]["goal_id"],
            "name": plan["goal"]["name"],
            "dueMonth": plan["goal"]["due_month"],
            "priority": plan["goal"]["priority"],
            "amount": plan["goal"]["amount"],
        },
        "targetProbability": plan["target_probability"],
        "baseProbability": plan["base_probability"],
        "feasible": plan["feasible"],
        "plans": [pack(item) for item in plan["plans"]],
        "pathsReused": plan["paths_reused"],
        "disclaimer": catalog.messages.get("disclaimer.simulation", {}),
    }


def _serialize_gaps(gaps: list[dict]) -> list[dict]:
    """目标缺口统一转为接口使用的驼峰命名。"""
    return [{
        "goalId": item["goal_id"],
        "name": item["name"],
        "priority": item["priority"],
        "gapAmount": item["gap_amount"],
    } for item in gaps]


def _snapshot_goal(goal, index: int) -> dict:
    """单个目标的摘要。priority 缺失时用行次序补上，保证顺序始终可排。"""
    return {
        "goalId": goal.goal_id, "name": goal.name, "amount": goal.amount,
        "dueMonth": goal.due_month, "priority": goal.priority or index + 1,
        "hitProbability": goal.hit_probability, "hitMonthP50": goal.hit_month_p50,
        "reachedRate": goal.reached_rate, "gapAmount": goal.gap_amount,
    }


def snapshot_of(profile: Profile, sim, capacity) -> dict:
    """供术语解释与结论解读使用的推演摘要。

    主目标单独列出，供只关心首要目标的老链路取用；全部目标按优先级附在 goals 里，
    这样解读能逐个讲到，而不是只讲排在最前面的那个。
    """
    primary = planner_domain.primary_goal(profile)
    ordered = sorted(sim.goal_results, key=lambda item: item.priority)
    goal = next((item for item in ordered if item.goal_id == primary.goal_id), None)
    return {
        "primaryGoal": None if goal is None else _snapshot_goal(goal, 0),
        "goals": [_snapshot_goal(item, index) for index, item in enumerate(ordered)],
        # 容量结论按清洗层认得的形状放在 capacity 下，术语解释才读得到等级与上限
        "capacity": {
            "level": capacity.current["level"],
            "finalCap": capacity.current["final_cap"],
            "cushionMonths": capacity.current["cushion_months"],
            "dipMonths": list(capacity.dip_months or []),
        },
    }


def run(profile: Profile, catalog: Catalog) -> dict:
    """完成一次从录入到方案的完整推演。"""
    paths, reused = get_paths(profile, catalog)
    sim = simulation_domain.simulate(profile, paths, config=catalog.domain,
                                     report=report_config(catalog))
    allocation = allocation_domain.allocate(profile, sim, catalog.domain)
    capacity = capacity_domain.assess(profile, sim, allocation, catalog.domain)
    primary = planner_domain.primary_goal(profile)
    plan = planner_domain.solve(profile, paths, primary.goal_id, catalog.domain)

    return {
        "profile": {
            "profileId": profile.profile_id, "name": profile.name,
            "grade": profile.grade, "gradeName": catalog.dict_name("grade", profile.grade),
            "livingCost": profile.living_cost, "livingGrowth": profile.living_growth,
            "initialBalance": profile.initial_balance,
            "riskAppetite": profile.risk_appetite,
            "riskAppetiteName": catalog.dict_name("risk_appetite", profile.risk_appetite),
            "months": profile.months, "paths": profile.paths,
            "budget": {"growthMonthly": profile.growth_budget, "treatMonthly": profile.treat_budget},
        },
        "simulation": _serialize_simulation(sim),
        "allocation": _serialize_allocation(allocation, catalog),
        "capacity": _serialize_capacity(capacity),
        "plan": _serialize_plan(plan, catalog),
        "gaps": _serialize_gaps(planner_domain.compute_gaps(profile, sim)),
        "scenarios": simulation_domain.scenario_comparison(profile, paths, catalog.domain),
        "snapshot": snapshot_of(profile, sim, capacity),
        "pathsReused": reused,
        "disclaimer": catalog.messages.get("disclaimer.simulation", {}),
    }


def plan_for(profile: Profile, goal_id: str, catalog: Catalog) -> dict:
    paths, reused = get_paths(profile, catalog)
    plan = planner_domain.solve(profile, paths, goal_id, catalog.domain)
    plan["cacheHit"] = reused
    payload = _serialize_plan(plan, catalog)
    # 单独求解方案时也要带免责：这里会输出新的金额与月数
    payload["disclaimer"] = catalog.messages.get("disclaimer.simulation", {})
    return payload


def require_goal(profile: Profile, goal_id: str) -> None:
    if not any(item.goal_id == goal_id for item in profile.goals):
        raise AppError("D-03-02", "指定的目标不存在于当前画像中", field="goal_id", http_status=404)
