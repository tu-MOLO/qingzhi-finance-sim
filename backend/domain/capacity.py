"""动态风险容量评估。

安全垫厚度 =（安全底座余额 − 未来到期目标待备额）÷ 当月刚需支出。
待备额在目标到期前的若干个月内线性爬升，使刚性目标临期时容量自然下探。
分档阈值、归一化区间、权重与偏好上限全部来自数据库配置。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .allocation import AllocationResult
from .models import DomainConfig, Profile, SimulationResult


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass
class CapacityResult:
    current: dict
    calendar: list[dict]
    dip_months: list[int]
    cushion_min: float
    cushion_max: float
    levels: list[dict] = field(default_factory=list)


def _levels_descending(config: DomainConfig):
    return sorted(config.risk_levels, key=lambda item: item.min_cushion_months, reverse=True)


def assess(profile: Profile, sim: SimulationResult, allocation: AllocationResult,
           config: DomainConfig) -> CapacityResult:
    months = int(sim.months)
    capacity_config = config.capacity
    horizon = min(capacity_config.calendar_months, months)
    need_series = sim.need_series
    levels = _levels_descending(config)
    appetite_cap = float(config.appetite_caps.get(profile.risk_appetite, 0.0))

    p50 = np.asarray(sim.balance_p50, dtype=float)
    net_save = np.empty(months)
    net_save[0] = max(0.0, p50[0] - float(profile.initial_balance))
    net_save[1:] = np.maximum(0.0, np.diff(p50))

    safe_series = allocation.series.get("safe", [0.0] * months)
    compound_series = allocation.series.get("compound", [0.0] * months)

    calendar: list[dict] = []
    for index in range(horizon):
        month = index + 1
        need = max(1.0, float(need_series[index]))

        pending = 0.0
        for goal in profile.goals:
            if goal.due_month >= month:
                weight = max(0.0, 1.0 - (goal.due_month - month) / capacity_config.pending_ramp_months)
                pending += float(goal.amount) * weight

        safe_balance = float(safe_series[index])
        cushion = max(0.0, safe_balance - pending) / need

        level_index = 0
        for position, level in enumerate(levels):
            if cushion >= level.min_cushion_months:
                level_index = position
                break
        else:
            level_index = len(levels) - 1

        rigid_sum = sum(float(goal.amount) for goal in profile.goals
                        if month < goal.due_month <= month + 12)
        pool = safe_balance + float(compound_series[index]) + float(net_save[index]) * 12.0
        rigidity = rigid_sum / max(1.0, pool)

        if rigidity > capacity_config.rigidity_high and level_index < len(levels) - 1:
            level_index += 1
        elif rigidity < capacity_config.rigidity_low and level_index > 0:
            level_index -= 1

        level = levels[level_index]
        final_cap = min(level.equity_cap, appetite_cap)

        calendar.append({
            "month": month,
            "cushion_months": round(cushion, 3),
            "pending_amount": round(pending, 2),
            "rigidity": round(rigidity, 4),
            "level_code": level.code,
            "level": level.name,
            "level_cap": level.equity_cap,
            "appetite_cap": appetite_cap,
            "final_cap": final_cap,
        })

    first = calendar[0] if calendar else {
        "month": 1, "cushion_months": 0.0, "rigidity": 1.0, "pending_amount": 0.0,
        "level_code": levels[-1].code if levels else "", "level": levels[-1].name if levels else "",
        "level_cap": levels[-1].equity_cap if levels else 0.0,
        "appetite_cap": appetite_cap, "final_cap": min(levels[-1].equity_cap if levels else 0.0, appetite_cap),
    }

    scoring = config.scoring
    cushion_norm = _clamp((first["cushion_months"] - scoring.norm_cushion_min) /
                          max(1e-9, scoring.norm_cushion_max - scoring.norm_cushion_min))
    rigidity_norm = 1.0 - _clamp(float(first["rigidity"]))
    stability_norm = 1.0 - _clamp(float(sim.income_cv) / max(1e-9, scoring.norm_cv_max))
    raw_score = (scoring.weight_cushion * cushion_norm +
                 scoring.weight_rigidity * rigidity_norm +
                 scoring.weight_stability * stability_norm)

    cushions = [item["cushion_months"] for item in calendar]
    dips = [calendar[i]["month"] for i in range(1, len(calendar))
            if calendar[i]["cushion_months"] < calendar[i - 1]["cushion_months"] - 0.25]

    return CapacityResult(
        current={
            "month": 1,
            "cushion_months": first["cushion_months"],
            "rigidity": first["rigidity"],
            "income_cv": round(float(sim.income_cv), 4),
            "raw_score": round(raw_score, 4),
            "level_code": first["level_code"],
            "level": first["level"],
            "level_cap": first["level_cap"],
            "appetite_cap": appetite_cap,
            "final_cap": first["final_cap"],
        },
        calendar=calendar,
        dip_months=dips,
        cushion_min=min(cushions) if cushions else 0.0,
        cushion_max=max(cushions) if cushions else 0.0,
        levels=[{"code": item.code, "name": item.name,
                 "min_cushion_months": item.min_cushion_months,
                 "equity_cap": item.equity_cap} for item in levels],
    )
