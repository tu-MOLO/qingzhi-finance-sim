"""反事实与敏感性分析：逐个扰动关键假设，量出它对各个目标达成概率的影响幅度。

扰动只发生在随机路径的下游。路径由 services.simulation.get_paths 按画像指纹缓存，
这里取到同一批路径之后只做确定性改写，绝不重新抽样，
因此低档与高档之间的差别全部来自参数本身，而不是蒙特卡洛噪声。

参与扰动的参数不是写死在代码里的：先从参数表挑出「性质要求三档取值」的参数，
再把参数键落到领域层数据结构的字段名上，能落位的才纳入。
参数键、三档取值、单位与名称一律由参数表下发。
"""

from __future__ import annotations

import dataclasses
from typing import Callable

import numpy as np

from ..db import connection
from ..db.repository import parameter as param_repo
from ..domain import planner as planner_domain
from ..domain import simulation as simulation_domain
from ..domain.models import DomainConfig, ModelCoefficients, PathSet, Profile
from . import simulation as simulation_service
from .configuration import Catalog

# 耗时上限：纳入扰动的参数个数，以及总的重跑次数（每个参数跑低、高两档）
_MAX_PARAMS = 8
_MAX_EVALUATIONS = 16

# 参数性质上的标记。带这个标记的性质必须给出三档取值，也就是可以被争论的假设
_TIER_MARK = "requires_tiers"

# 旋钮只能落在领域层这两个载体上：模型系数与画像字段
_KNOB_HOLDERS = (ModelCoefficients, Profile)

# 概率保留的小数位，与情景对比的口径一致
_PRECISION = 4

# 一个旋钮的改法：给定画像、路径、配置与扰动取值，返回改写后的路径与配置
Channel = Callable[[Profile, PathSet, DomainConfig, float], tuple[PathSet, DomainConfig]]


# ---------------------------------------------------------------- 参数挑选


def _tiered_properties(catalog: Catalog) -> set[str]:
    """性质表里被标记为「必须给出三档取值」的性质编码。"""
    return {item["code"] for item in catalog.dict_items("param_property")
            if (item.get("attributes") or {}).get(_TIER_MARK)}


def _perturbable(catalog: Catalog) -> list[dict]:
    """可扰动的参数：性质要求三档取值，且三档取值确实存在。"""
    marks = _tiered_properties(catalog)
    with connection.session() as conn:
        rows = param_repo.list_params(conn)
    return [row for row in rows
            if row["key"] and row["property"] in marks
            and row["value_low"] is not None and row["value_high"] is not None]


def _locate_knob(key: str) -> str | None:
    """参数键落在哪个旋钮上。

    旋钮名取自领域层数据结构的字段名：字段名与参数键相同，或字段名以「参数键 + 下划线」开头，
    例如系数字段 sudden_freq_per_year 由参数 sudden_freq 驱动。
    这样新增一个参数只要在参数表里登记，不需要回来改代码。
    """
    for holder in _KNOB_HOLDERS:
        for field in dataclasses.fields(holder):
            if field.name == key or field.name.startswith(key + "_"):
                return field.name
    return None


# ---------------------------------------------------------------- 扰动通道


def _living_growth(profile: Profile, paths: PathSet, config: DomainConfig,
                   value: float) -> tuple[PathSet, DomainConfig]:
    """家庭支持的年增长率：生活费序列是确定性的，按新增长率整条重算后替换回收入矩阵。"""
    living = profile.living_cost * np.power(1.0 + float(value), np.arange(paths.months) // 12)
    income = paths.income - paths.living_monthly[None, :] + living[None, :]
    return dataclasses.replace(paths, income=income, living_monthly=living), config


def _sudden(field: str) -> Channel:
    """突发支出的频率与金额：系数先换成扰动值，再把同一批抽样按新系数重映射。

    金额上下界变化时，先由基准区间反解出每个命中格子的分位，再按新区间仿射回去，
    这一步是精确的。发生频率改变的是命中与否，命中月份无法从已有路径反解，
    因此按期望总额与频率成正比的关系缩放金额，不重新抽样。
    """
    def apply(profile: Profile, paths: PathSet, config: DomainConfig,
              value: float) -> tuple[PathSet, DomainConfig]:
        model = dataclasses.replace(config.model, **{field: float(value)})
        sudden = paths.sudden
        span = config.model.sudden_high - config.model.sudden_low
        if span > 0:
            share = np.clip((sudden - config.model.sudden_low) / span, 0.0, 1.0)
            sudden = (sudden > 0) * (model.sudden_low + (model.sudden_high - model.sudden_low) * share)
        if config.model.sudden_freq_per_year > 0:
            sudden = sudden * (model.sudden_freq_per_year / config.model.sudden_freq_per_year)
        return dataclasses.replace(paths, sudden=sudden), dataclasses.replace(config, model=model)
    return apply


def _coefficient(field: str) -> Channel:
    """只进入领域配置的系数：原样替换，随机路径不动。"""
    def apply(profile: Profile, paths: PathSet, config: DomainConfig,
              value: float) -> tuple[PathSet, DomainConfig]:
        model = dataclasses.replace(config.model, **{field: float(value)})
        return paths, dataclasses.replace(config, model=model)
    return apply


# 通道按旋钮名登记。参数键不出现在这里，参数键到旋钮名的对应由 _locate_knob 在数据上发现
_CHANNELS: dict[str, Channel] = {
    "living_growth": _living_growth,
    "sudden_freq_per_year": _sudden("sudden_freq_per_year"),
    "sudden_low": _sudden("sudden_low"),
    "sudden_high": _sudden("sudden_high"),
    "emergency_months": _coefficient("emergency_months"),
}


# ---------------------------------------------------------------- 重跑与量度


def _rerun(profile: Profile, paths: PathSet, config: DomainConfig, channel: Channel, value: float):
    perturbed_paths, perturbed_config = channel(profile, paths, config, float(value))
    return simulation_domain.simulate(profile, perturbed_paths, config=perturbed_config)


def _probabilities(outcome) -> dict[str, float]:
    """一次重跑里所有目标的达成概率。

    扰动一次就能拿到全部目标的结果，因此多目标并不会增加重跑次数，
    只是把每个目标的数都记下来，交给界面按目标切换。
    """
    return {goal.goal_id: round(float(goal.hit_probability), _PRECISION)
            for goal in outcome.goal_results}


def _goal_index(profile: Profile) -> list[dict]:
    """目标的编号与名称，按优先级排列。界面上的切换器直接用这一份。"""
    return [{"goalId": goal.goal_id, "name": goal.name, "priority": int(goal.priority)}
            for goal in sorted(profile.goals, key=lambda item: int(item.priority))]


def analyze(profile: Profile, catalog: Catalog) -> dict:
    """在基准路径上逐个扰动参数，返回每个参数对各个目标达成概率的影响幅度。

    首要目标的数值仍放在行的顶层，保持既有读法；
    每个目标自己的一组数挂在 byGoal 下，界面切换目标时不必重新请求。
    """
    paths, reused = simulation_service.get_paths(profile, catalog)
    primary = planner_domain.primary_goal(profile)
    index = _goal_index(profile)
    base_all = _probabilities(simulation_domain.simulate(profile, paths, config=catalog.domain))
    base = base_all.get(primary.goal_id, 0.0)

    by_goal = {item["goalId"]: {"base": base_all.get(item["goalId"], 0.0)}
               for item in index}

    rows: list[dict] = []
    evaluations = 0
    for row in _perturbable(catalog):
        if len(rows) >= _MAX_PARAMS or evaluations >= _MAX_EVALUATIONS:
            break
        knob = _locate_knob(row["key"])
        channel = _CHANNELS.get(knob) if knob else None
        if channel is None:
            continue
        low_all = _probabilities(_rerun(profile, paths, catalog.domain, channel,
                                        row["value_low"]))
        high_all = _probabilities(_rerun(profile, paths, catalog.domain, channel,
                                         row["value_high"]))
        evaluations += 2

        per_goal: dict[str, dict] = {}
        for item in index:
            goal_id = item["goalId"]
            low = low_all.get(goal_id, 0.0)
            high = high_all.get(goal_id, 0.0)
            per_goal[goal_id] = {
                "lowProbability": low,
                "highProbability": high,
                "swing": round(abs(high - low), _PRECISION),
            }
            by_goal[goal_id][row["key"]] = per_goal[goal_id]

        rows.append({
            "key": row["key"],
            "name": row["name"],
            "unit": row["unit"],
            "low": row["value_low"],
            "high": row["value_high"],
            "lowProbability": per_goal.get(primary.goal_id, {}).get("lowProbability", 0.0),
            "highProbability": per_goal.get(primary.goal_id, {}).get("highProbability", 0.0),
            "swing": per_goal.get(primary.goal_id, {}).get("swing", 0.0),
            "byGoal": per_goal,
        })

    # 排序按「任一目标上出现的最大影响幅度」，对哪个目标最敏感的假设排在最前
    def strongest(item: dict) -> float:
        return max((bucket["swing"] for bucket in item["byGoal"].values()), default=0.0)

    rows.sort(key=lambda item: (-strongest(item), -item["swing"], item["key"]))
    return {
        "goal": {"goalId": primary.goal_id, "name": primary.name, "baseProbability": base},
        "goals": [{**item, "baseProbability": by_goal[item["goalId"]]["base"]}
                  for item in index],
        "byGoal": by_goal,
        "rows": rows,
        "pathsReused": reused,
        # 反事实会产出新的数字，属于合规风险最高的输出，必须与推演同样附带免责提示
        "disclaimer": catalog.messages.get("disclaimer.simulation", {}),
    }
