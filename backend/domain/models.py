"""领域层的数据结构与配置载体。

领域层是纯计算层：不连接数据库、不读写文件、不依赖运行环境。
它需要的全部参数由服务层从数据库取出后注入，函数签名里不存在任何业务默认值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

# ---------------------------------------------------------------- 配置载体


@dataclass(frozen=True)
class SimulationBounds:
    """仿真的默认值与边界。"""

    default_months: int
    default_paths: int
    default_seed: int
    min_months: int
    max_months: int
    min_paths: int
    max_paths: int
    max_path_months: int
    max_goals: int
    max_income_sources: int


@dataclass(frozen=True)
class ModelCoefficients:
    """随机过程与支出模型用到的系数。"""

    sudden_freq_per_year: float
    sudden_low: float
    sudden_high: float
    emergency_months: float


@dataclass(frozen=True)
class SolverConfig:
    """反向求解器的参数。"""

    target_probability: float
    tolerance: float
    max_iterations: int


@dataclass(frozen=True)
class CapacityConfig:
    """风险容量评估的参数。"""

    calendar_months: int
    pending_ramp_months: int
    rigidity_high: float
    rigidity_low: float


@dataclass(frozen=True)
class ScoringConfig:
    """风险容量原始分的归一化区间与权重。"""

    weight_cushion: float
    weight_rigidity: float
    weight_stability: float
    norm_cushion_min: float
    norm_cushion_max: float
    norm_cv_max: float


@dataclass(frozen=True)
class ScenarioConfig:
    """三档情景的收入系数。"""

    pessimistic_factor: float
    base_factor: float
    optimistic_factor: float


@dataclass(frozen=True)
class ReportConfig:
    """逐路径明细的采样口径。

    只决定报告里画出多少条样本、分布分多少格，不参与任何判定，
    因此改动它不会影响达成概率、方案与风险容量。
    """

    path_samples: int = 24
    histogram_bins: int = 20


@dataclass(frozen=True)
class RiskLevel:
    """风险容量的一个档位。"""

    code: str
    name: str
    min_cushion_months: float
    equity_cap: float


@dataclass(frozen=True)
class AccountDefinition:
    """价值分层账户的定义。"""

    code: str
    name: str
    color: str
    priority: int


@dataclass(frozen=True)
class DomainConfig:
    """领域层全部配置的集合。由服务层从数据库装配后传入。"""

    bounds: SimulationBounds
    model: ModelCoefficients
    solver: SolverConfig
    capacity: CapacityConfig
    scoring: ScoringConfig
    scenario: ScenarioConfig
    risk_levels: tuple[RiskLevel, ...]
    accounts: tuple[AccountDefinition, ...]
    # 风险偏好档位名称到允许上限的映射，来自字典表的 attributes
    appetite_caps: dict[str, float] = field(default_factory=dict)
    # 分配顺序，来自账户定义的优先级排序
    @property
    def account_order(self) -> tuple[str, ...]:
        return tuple(item.code for item in sorted(self.accounts, key=lambda x: x.priority))

    @property
    def account_colors(self) -> dict[str, str]:
        return {item.code: item.color for item in self.accounts}

    @property
    def account_names(self) -> dict[str, str]:
        return {item.code: item.name for item in self.accounts}


# ---------------------------------------------------------------- 领域数据


@dataclass(frozen=True)
class Goal:
    goal_id: str
    name: str
    amount: float
    due_month: int
    priority: int


@dataclass(frozen=True)
class IncomeSource:
    source_type: str
    name: str
    enabled: bool
    probability: float
    amount_low: float
    amount_mid: float
    amount_high: float
    start_month: int
    end_month: int
    interrupt_prob: float
    # 分布形态与字段开关来自字典表中该收入来源类别的 attributes
    distribution: str = "fixed"
    has_probability: bool = False
    has_interrupt: bool = False
    has_window: bool = False

    @property
    def is_deterministic(self) -> bool:
        return self.distribution == "fixed"


@dataclass(frozen=True)
class Expense:
    """每月实际花掉的一项支出。刚需不可压缩，弹性可压缩。"""

    category: str
    name: str
    amount: float
    essential: bool
    growth_rate: float
    enabled: bool = True


@dataclass(frozen=True)
class Profile:
    profile_id: str
    name: str
    grade: str
    living_cost: float
    living_growth: float
    initial_balance: float
    risk_appetite: str
    months: int
    paths: int
    seed: int
    growth_budget: float
    treat_budget: float
    income_sources: tuple[IncomeSource, ...]
    expenses: tuple[Expense, ...]
    goals: tuple[Goal, ...]

    def source(self, source_type: str) -> IncomeSource | None:
        for item in self.income_sources:
            if item.source_type == source_type:
                return item
        return None

    def with_treat_budget(self, value: float) -> Profile:
        return Profile(**{**self.__dict__, "treat_budget": float(value)})


@dataclass
class PathSet:
    """一次生成、多次复用的随机路径集合。"""

    paths: int
    months: int
    seed: int
    income: np.ndarray          # (paths, months) 各路径各月收入
    sudden: np.ndarray          # (paths, months) 各路径各月突发支出
    fixed_expense: np.ndarray   # (months,) 各月支出项合计（不含突发与悦己预算）
    need_monthly: np.ndarray    # (months,) 各月刚需支出（Σ 刚需项）
    living_monthly: np.ndarray  # (months,) 各月家庭支持（固定收入）


@dataclass
class GoalResult:
    goal_id: str
    name: str
    amount: float
    due_month: int
    priority: int
    hit_probability: float
    reached_rate: float
    hit_month_p10: float | None
    hit_month_p50: float | None
    hit_month_p90: float | None
    gap_amount: float
    shortfall_paths: int


@dataclass
class SimulationResult:
    seed: int
    months: int
    paths: int
    treat_monthly: float
    balance_p10: list[float]
    balance_p50: list[float]
    balance_p90: list[float]
    goal_results: list[GoalResult]
    deficit_months_p10: list[int]
    deficit_months_p50: list[int]
    deficit_total: int
    deficit_paths: int
    median_end_balance: float
    need_monthly: float
    need_series: list[float]
    income_cv: float
    emergency_target: float
    balance: Any = None
    # 断流最集中的月份及对应断流路径数，供界面回写提示
    deficit_peak_months: list[tuple[int, int]] = field(default_factory=list)
    # 逐路径明细：抽样的单条路径、期末余额分布与各目标的累计达成曲线
    path_samples: list[dict] = field(default_factory=list)
    end_balance_histogram: dict = field(default_factory=dict)
    end_balance_percentiles: dict = field(default_factory=dict)
    reach_curves: list[dict] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
