"""多目标动态优化：目标缺口与二选一方案。

方案一求的是可行上界：在保证按期达成概率不低于目标线的前提下，
体验悦己预算最多还能保留多少。预算越低储蓄越多、达成概率单调上升，
因此可行域是「零到上界」的区间，求解即在该区间上做二分逼近。
求解全程复用同一批随机路径——随机路径由调用方以 PathSet 传入，
求解器不持有种子，不具备重新抽样的能力，路径复用是结构上的保证。
"""

from __future__ import annotations

import math

from ..common.errors import DecisionError
from .models import DomainConfig, PathSet, Profile
from .simulation import simulate


def primary_goal(profile: Profile):
    return min(profile.goals, key=lambda item: item.priority)


def compute_gaps(profile: Profile, sim) -> list[dict]:
    ordered = sorted(sim.goal_results, key=lambda item: item.priority)
    return [{"goal_id": goal.goal_id, "name": goal.name, "priority": goal.priority,
             "gap_amount": round(goal.gap_amount, 2)} for goal in ordered]


def _evaluate(profile: Profile, paths: PathSet, goal_id: str,
              treat_monthly: float, config: DomainConfig) -> tuple[float, float, bool]:
    outcome = simulate(profile, paths, treat_monthly, config)
    for goal in outcome.goal_results:
        if goal.goal_id == goal_id:
            median = goal.hit_month_p50
            if median is None:
                # 半数以上路径在推演期内未达成，以推演期末之后作为哨兵值，
                # 并把这一事实报出去，界面不能把它当成确定月数呈现
                return goal.hit_probability, float(outcome.months) + 1.0, True
            return goal.hit_probability, float(median), False
    raise DecisionError("D-03-02", "指定的目标不存在于当前画像中")


def solve(profile: Profile, paths: PathSet, goal_id: str, config: DomainConfig,
          target: float | None = None) -> dict:
    goal = next((item for item in profile.goals if item.goal_id == goal_id), None)
    if goal is None:
        raise DecisionError("D-03-02", "指定的目标不存在于当前画像中")

    solver = config.solver
    threshold = float(solver.target_probability if target is None else target)
    current_treat = float(profile.treat_budget)
    scoped = profile.with_treat_budget(current_treat)

    base_probability, base_median, base_beyond = _evaluate(
        scoped, paths, goal_id, current_treat, config)
    upper = max(current_treat, 0.0)
    due = int(goal.due_month)

    postpone = {
        "plan_id": "p2",
        "plan_type": "postpone",
        "variant": "postpone",
        "feasible": True,
        "keep_current": False,
        "treat_monthly": round(current_treat, 2),
        "delta_amount": 0.0,
        "achieved_probability": round(base_probability, 4),
        "delay_months": round(max(0.0, base_median - due), 1),
        "median_hit_month": round(base_median),
        "beyond_horizon": base_beyond,
        "iterations": 0,
    }

    goal_info = {"goal_id": goal.goal_id, "name": goal.name, "due_month": due,
                 "priority": int(goal.priority), "amount": float(goal.amount)}

    if base_probability >= threshold:
        compress = {
            "plan_id": "p1", "plan_type": "compress", "variant": "compress_keep",
            "feasible": True, "keep_current": True,
            "treat_monthly": round(current_treat, 2), "delta_amount": 0.0,
            "achieved_probability": round(base_probability, 4), "delay_months": 0.0,
            "median_hit_month": round(base_median), "beyond_horizon": base_beyond,
            "iterations": 1,
        }
        return _pack(compress, postpone, threshold, base_probability, True, goal_info)

    zero_probability, zero_median, zero_beyond = _evaluate(scoped, paths, goal_id, 0.0, config)
    if upper <= 0 or zero_probability < threshold:
        compress = {
            "plan_id": "p1", "plan_type": "compress",
            "variant": "compress_zero" if upper <= 0 else "compress_infeasible",
            "feasible": False, "keep_current": False, "treat_monthly": None,
            "delta_amount": round(-current_treat, 2),
            "achieved_probability": round(base_probability, 4),
            "best_probability": round(zero_probability, 4),
            "delay_months": round(max(0.0, zero_median - due), 1),
            "median_hit_month": round(zero_median), "beyond_horizon": zero_beyond,
            "iterations": 2,
        }
        return _pack(compress, postpone, threshold, base_probability, False, goal_info)

    low, high, iterations = 0.0, upper, 0
    while high - low > solver.tolerance and iterations < solver.max_iterations:
        middle = (low + high) / 2.0
        probability, _, _ = _evaluate(scoped, paths, goal_id, middle, config)
        if probability >= threshold:
            low = middle
        else:
            high = middle
        iterations += 1

    # 向下取整到十元量级，保证结果仍落在可行区间内
    value = math.floor(low / 10.0) * 10.0
    probability, median, beyond = _evaluate(scoped, paths, goal_id, value, config)
    compress = {
        "plan_id": "p1", "plan_type": "compress", "variant": "compress_feasible",
        "feasible": True, "keep_current": False,
        "treat_monthly": round(value, 2),
        "delta_amount": round(value - current_treat, 2),
        "achieved_probability": round(probability, 4),
        "delay_months": round(max(0.0, median - due), 1),
        "median_hit_month": round(median), "beyond_horizon": beyond,
        "iterations": iterations,
    }
    return _pack(compress, postpone, threshold, base_probability, True, goal_info)


def _pack(compress: dict, postpone: dict, threshold: float,
          base_probability: float, feasible: bool, goal_info: dict) -> dict:
    return {
        "goal_id": goal_info["goal_id"],
        "goal": goal_info,
        "target_probability": threshold,
        "base_probability": round(base_probability, 4),
        "feasible": feasible,
        "plans": [compress, postpone],
        "paths_reused": True,
    }
