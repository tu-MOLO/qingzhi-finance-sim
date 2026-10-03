"""现金流仿真引擎。

收入矩阵一次生成、多次复用；悦己预算只影响支出侧，因此反向求解时无需重新抽样。
这既是性能要求，也是可复现性要求：同一份输入永远得到同一个答案。

本模块为纯计算，不接触数据库。全部系数由调用方通过 DomainConfig 注入。
"""

from __future__ import annotations

import numpy as np

from ..common.errors import SimulationError
from .models import DomainConfig, GoalResult, PathSet, Profile, ReportConfig, SimulationResult

# 收入分布形态的标识，与字典表中收入来源类别的 distribution 属性对应
DISTRIBUTION_FIXED = "fixed"
DISTRIBUTION_MONTHLY = "monthly_random"
DISTRIBUTION_ANNUAL = "annual_lump"
DISTRIBUTION_SEGMENTED = "segmented"


def _uniform(rng: np.random.Generator, low: float, high: float, size) -> np.ndarray:
    if high <= low:
        return np.full(size, low, dtype=np.float32)
    return rng.uniform(low, high, size).astype(np.float32)


def build_paths(profile: Profile, config: DomainConfig) -> PathSet:
    """生成随机路径并算出收入矩阵。结果只依赖画像与配置，与执行顺序无关。"""
    path_count = int(profile.paths)
    months = int(profile.months)
    rng = np.random.default_rng(int(profile.seed))
    model = config.model

    living = profile.living_cost * np.power(
        1.0 + profile.living_growth, np.arange(months) // 12
    )
    income = np.tile(living, (path_count, 1)).astype(np.float64)
    years = (months + 11) // 12

    for source in profile.income_sources:
        if not source.enabled:
            continue
        attributes = getattr(source, "distribution", None)
        if attributes is None:
            continue

        if attributes == DISTRIBUTION_FIXED:
            # 生活费已由基础信息确定，金额区间只作展示
            continue

        if attributes == DISTRIBUTION_MONTHLY:
            participates = (rng.random(path_count) < source.probability) if source.has_probability \
                else np.ones(path_count, dtype=bool)
            breaks = (rng.random((path_count, months)) < source.interrupt_prob) if source.has_interrupt \
                else np.zeros((path_count, months), dtype=bool)
            amount = _uniform(rng, source.amount_low, source.amount_high, (path_count, months))
            income += (participates[:, None] & ~breaks) * amount
            continue

        if attributes == DISTRIBUTION_ANNUAL:
            hits = (rng.random((path_count, years)) < source.probability) if source.has_probability \
                else np.ones((path_count, years), dtype=bool)
            amount = _uniform(rng, source.amount_low, source.amount_high, (path_count, years))
            for year in range(years):
                index = year * 12
                if index < months:
                    income[:, index] += hits[:, year] * amount[:, year]
            continue

        if attributes == DISTRIBUTION_SEGMENTED:
            start = max(1, int(source.start_month)) if source.has_window else 1
            end = min(months, int(source.end_month)) if source.has_window else months
            if end < start:
                continue
            active = (rng.random(path_count) >= source.interrupt_prob) if source.has_interrupt \
                else np.ones(path_count, dtype=bool)
            amount = _uniform(rng, source.amount_low, source.amount_high, (path_count, 1))
            window = np.zeros((1, months), dtype=bool)
            window[0, start - 1:end] = True
            income += active[:, None] * window * amount
            continue

    sudden = (rng.random((path_count, months)) < model.sudden_freq_per_year / 12.0) * _uniform(
        rng, model.sudden_low, model.sudden_high, (path_count, months))

    # 支出项逐项计算：每一项都有自己的金额、年增长率与刚需标记。
    # 刚需项合计是应急金目标的基准，全部支出项合计是每月真正花掉的钱。
    expense_series = np.zeros(months, dtype=np.float64)
    need_series = np.zeros(months, dtype=np.float64)
    for expense in profile.expenses:
        if not expense.enabled:
            continue
        series = expense.amount * np.power(1.0 + expense.growth_rate, np.arange(months) // 12)
        expense_series += series
        if expense.essential:
            need_series += series
    fixed_expense = expense_series

    if not np.all(np.isfinite(income)) or not np.all(np.isfinite(sudden)):
        raise SimulationError("S-03-02", "当前参数下推演结果异常，请检查金额区间设置")

    return PathSet(paths=path_count, months=months, seed=int(profile.seed), income=income,
                   sudden=sudden, fixed_expense=fixed_expense,
                   need_monthly=need_series, living_monthly=living)


def _balance_matrix(net: np.ndarray, initial: float = 0.0):
    """余额不允许为负：b_t = max(0, b_{t-1} + n_t)，起点为初始余额。

    该递推等价于「起点余额加累积和」减去历史最低点，可整体向量化。
    """
    cumulative = float(initial) + np.cumsum(net, axis=1)
    running_min = np.minimum.accumulate(cumulative, axis=1)
    floor = np.minimum(0.0, running_min)
    balance = cumulative - floor
    floor_prev = np.concatenate([np.zeros((cumulative.shape[0], 1)), floor[:, :-1]], axis=1)
    deficit = cumulative < floor_prev
    return balance, deficit


def _population_quantile(sorted_reached: np.ndarray, reached_rate: float, q: float):
    """全样本分位。未达成路径视为超出推演范围，因此分位点超过达成比例时返回空值。"""
    if reached_rate <= 0 or sorted_reached.size == 0 or q > reached_rate + 1e-12:
        return None
    return float(np.quantile(sorted_reached, min(1.0, q / reached_rate)))


def _sample_paths(balance: np.ndarray, end: np.ndarray, sample_count: int) -> list[dict]:
    """按期终余额从低到高等距抽样若干条真实路径。

    按名次抽而不是按下标抽：下标抽出来的样本会挤在中位数附近，
    看不出最坏与最好的一成差多少。抽样只用于展示，不参与任何判定。
    """
    total = int(balance.shape[0])
    if total == 0 or sample_count <= 0:
        return []
    if total <= sample_count:
        picks = np.arange(total)
    else:
        picks = np.unique(np.linspace(0, total - 1, sample_count).round().astype(int))
    order = np.argsort(end, kind="stable")
    ranked = np.sort(end)
    return [{
        # 路径序号按下标给出，说明这是第几次随机抽样，而不是名次
        "pathNo": int(index) + 1,
        # 名次转成的分位点：样本落在全部路径的什么位置上
        "percentile": round(float(np.searchsorted(ranked, end[index]) / max(1, total - 1)), 4),
        "endBalance": float(end[index]),
        "series": [round(float(value)) for value in balance[index]],
    } for index in order[picks]]


def _end_balance_histogram(end: np.ndarray, bins: int) -> dict:
    """期末余额分布。横轴从零起，低于零的样本会并入第一格。"""
    if end.size == 0 or bins <= 0:
        return {"minValue": 0.0, "maxValue": 0.0, "buckets": []}
    low = min(0.0, float(end.min()))
    high = float(end.max())
    if not np.isfinite(high) or high <= low:
        high = low + 1.0
    counts, edges = np.histogram(end, bins=bins, range=(low, high))
    return {
        "minValue": low,
        "maxValue": high,
        "buckets": [{"from": float(edges[i]), "to": float(edges[i + 1]),
                     "count": int(counts[i])} for i in range(len(counts))],
    }


def simulate(profile: Profile, paths: PathSet, treat_monthly: float | None = None,
             config: DomainConfig | None = None,
             report: ReportConfig | None = None) -> SimulationResult:
    """按给定悦己预算推演一次。"""
    treat = float(profile.treat_budget if treat_monthly is None else treat_monthly)
    emergency_months = config.model.emergency_months if config else 0.0
    sampling = report or ReportConfig()

    expense = paths.fixed_expense + treat
    net = paths.income - paths.sudden - expense[None, :]
    balance, deficit_mask = _balance_matrix(net, profile.initial_balance)
    deficit_counts = deficit_mask.sum(axis=0)
    percentiles = np.percentile(balance, [10, 50, 90], axis=0)

    goals: list[GoalResult] = []
    reach_curves: list[dict] = []
    for goal in profile.goals:
        reached_mask = balance >= float(goal.amount)
        hit = reached_mask.any(axis=1)
        first = np.where(hit, reached_mask.argmax(axis=1) + 1, 0)
        reached_months = np.sort(first[first > 0])
        reached_rate = float(reached_months.size) / paths.paths
        by_due = int(np.count_nonzero((first > 0) & (first <= int(goal.due_month))))
        index = min(paths.months, int(goal.due_month)) - 1
        goals.append(GoalResult(
            goal_id=goal.goal_id, name=goal.name, amount=float(goal.amount),
            due_month=int(goal.due_month), priority=int(goal.priority),
            hit_probability=by_due / paths.paths,
            reached_rate=reached_rate,
            hit_month_p10=_population_quantile(reached_months, reached_rate, 0.10),
            hit_month_p50=_population_quantile(reached_months, reached_rate, 0.50),
            hit_month_p90=_population_quantile(reached_months, reached_rate, 0.90),
            gap_amount=max(0.0, float(goal.amount) - float(percentiles[1][index])),
            shortfall_paths=int(deficit_mask.any(axis=1).sum()),
        ))
        # 累计达成曲线：按月统计「到第几个月为止累计有多少比例的路径已经够钱」
        per_month = np.bincount(first[first > 0], minlength=paths.months + 1)[1:paths.months + 1]
        reach_curves.append({
            "goalId": goal.goal_id, "name": goal.name,
            "dueMonth": int(goal.due_month), "amount": float(goal.amount),
            "priority": int(goal.priority),
            "curve": (np.cumsum(per_month) / paths.paths).tolist(),
        })

    shares = deficit_counts / paths.paths
    path_mean_income = paths.income.mean(axis=1)
    income_cv = float(path_mean_income.std() / max(1e-9, path_mean_income.mean()))

    end_balance = balance[:, -1]
    end_p10, end_p50, end_p90 = np.percentile(end_balance, [10, 50, 90]).tolist()

    # 断流最集中的月份。deficit_months_* 保留的是「断流占比达到阈值的月份」，
    # 而界面要回写的是「哪几个月断得最凶」，两者不是一回事。
    order = np.argsort(-deficit_counts)[:8]
    deficit_peak_months = [(int(index) + 1, int(deficit_counts[index]))
                           for index in order if deficit_counts[index] > 0]

    return SimulationResult(
        seed=paths.seed, months=paths.months, paths=paths.paths, treat_monthly=treat,
        balance_p10=percentiles[0].tolist(),
        balance_p50=percentiles[1].tolist(),
        balance_p90=percentiles[2].tolist(),
        goal_results=goals,
        deficit_months_p10=[int(i + 1) for i, value in enumerate(shares) if value >= 0.10],
        deficit_months_p50=[int(i + 1) for i, value in enumerate(shares) if value >= 0.50],
        deficit_total=int(deficit_counts.sum()),
        deficit_paths=int(deficit_mask.any(axis=1).sum()),
        deficit_peak_months=deficit_peak_months,
        median_end_balance=float(percentiles[1][-1]),
        need_monthly=float(paths.need_monthly[0]),
        need_series=paths.need_monthly.tolist(),
        income_cv=income_cv,
        emergency_target=float(paths.need_monthly[0] * emergency_months),
        balance=balance,
        path_samples=_sample_paths(balance, end_balance, sampling.path_samples),
        end_balance_histogram=_end_balance_histogram(end_balance, sampling.histogram_bins),
        end_balance_percentiles={"p10": float(end_p10), "p50": float(end_p50),
                                 "p90": float(end_p90)},
        reach_curves=reach_curves,
    )


def scale_income(paths: PathSet, factor: float) -> PathSet:
    """情景对比：只缩放收入，不缩放支出与突发支出。"""
    return PathSet(paths=paths.paths, months=paths.months, seed=paths.seed,
                   income=paths.income * factor, sudden=paths.sudden,
                   fixed_expense=paths.fixed_expense, need_monthly=paths.need_monthly,
                   living_monthly=paths.living_monthly)


def scenario_comparison(profile: Profile, paths: PathSet, config: DomainConfig) -> dict:
    """乐观、基准、悲观三档下的达成概率对比。档位名称与系数均来自数据库。"""
    factors = {
        "pessimistic": config.scenario.pessimistic_factor,
        "base": config.scenario.base_factor,
        "optimistic": config.scenario.optimistic_factor,
    }
    result: dict[str, dict] = {}
    for code, factor in factors.items():
        outcome = simulate(profile, scale_income(paths, factor), config=config)
        result[code] = {goal.goal_id: round(goal.hit_probability, 4)
                        for goal in outcome.goal_results}
    return result
