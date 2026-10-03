"""价值分层账户的资金分配。

分配顺序取自数据库中的账户priority字段，不使用代码内置的固定次序。
安全底座未填满时，排在安全底座之后的长期复利与体验悦己均不分配资金。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .models import AccountDefinition, DomainConfig, Profile, SimulationResult

TOLERANCE = 0.01


@dataclass
class AllocationResult:
    monthly: list[dict]
    series: dict[str, list[float]]
    totals: dict[str, float]
    available_series: list[float]
    conservation_ok: bool
    priority_ok: bool
    emergency_target: float
    order: list[str] = field(default_factory=list)


def allocate(profile: Profile, sim: SimulationResult, config: DomainConfig) -> AllocationResult:
    """按中位路径的月度净结余逐月分配。"""
    months = int(sim.months)
    p50 = np.asarray(sim.balance_p50, dtype=float)

    available = np.empty(months)
    available[0] = max(0.0, p50[0] - float(profile.initial_balance))
    available[1:] = np.maximum(0.0, np.diff(p50))

    emergency_target = float(sim.emergency_target)
    account_defs: list[AccountDefinition] = sorted(config.accounts, key=lambda item: item.priority)
    codes = [item.code for item in account_defs]
    safe_code = codes[0] if codes else "safe"

    # 各账户的月度上限。安全底座的上限是应急金目标，其余账户的上限来自画像预算
    caps: dict[str, float | None] = dict.fromkeys(codes)
    caps[safe_code] = emergency_target
    for code in codes:
        if code == "growth":
            caps[code] = float(profile.growth_budget)
        elif code == "treat":
            caps[code] = float(profile.treat_budget)

    balances = dict.fromkeys(codes, 0.0)
    balances[safe_code] = min(float(profile.initial_balance), emergency_target)

    series: dict[str, list[float]] = {code: [] for code in codes}
    monthly: list[dict] = []
    available_series: list[float] = []
    conservation_ok = True
    priority_ok = True

    for index in range(months):
        pool = float(available[index])
        total_in = pool
        allocated = dict.fromkeys(codes, 0.0)

        for code in codes:
            if pool <= 0:
                break
            cap = caps[code]
            budget_incomplete = balances[safe_code] < emergency_target - TOLERANCE
            if code == safe_code:
                if not budget_incomplete:
                    continue
                step = min(pool, emergency_target - balances[code])
            else:
                # 安全底座未填满时，排在成长悦己之后的账户不参与分配
                if budget_incomplete and code in ("treat", "compound"):
                    continue
                step = pool if cap is None else min(pool, cap)
            allocated[code] = step
            balances[code] += step
            pool -= step

        # 未被任何账户吸收的余量并入长期复利，保证分配守恒
        residual_code = "compound" if "compound" in codes else codes[-1]
        if pool > 0:
            allocated[residual_code] += pool
            balances[residual_code] += pool
            pool = 0.0

        if abs(sum(allocated.values()) - total_in) > 1e-6:
            conservation_ok = False
        if (balances[safe_code] < emergency_target - TOLERANCE
                and (allocated.get("treat", 0.0) > 0 or allocated.get("compound", 0.0) > 0)):
            priority_ok = False

        for code in codes:
            series[code].append(round(balances[code], 2))
        available_series.append(round(total_in, 2))
        monthly.append({"month": index + 1, "available": round(total_in, 2),
                        "accounts": {code: round(value, 2) for code, value in allocated.items()}})

    return AllocationResult(
        monthly=monthly, series=series,
        totals={code: round(value, 2) for code, value in balances.items()},
        available_series=available_series,
        conservation_ok=conservation_ok, priority_ok=priority_ok,
        emergency_target=round(emergency_target, 2), order=codes,
    )
