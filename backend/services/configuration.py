"""配置服务：把数据库中的配置装配成领域层需要的载体，并提供给前端的目录数据。

配置一经改动即失效重建，业务代码不缓存副本。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..common.errors import ConfigurationError
from ..db import connection
from ..db.repository import configuration as config_repo
from ..db.repository import parameter as param_repo
from ..domain.models import (
    AccountDefinition,
    CapacityConfig,
    DomainConfig,
    ModelCoefficients,
    RiskLevel,
    ScenarioConfig,
    ScoringConfig,
    SimulationBounds,
    SolverConfig,
)

_CACHE: Catalog | None = None


@dataclass
class Catalog:
    settings: dict
    dictionaries: dict[str, list[dict]]
    accounts: list[dict]
    risk_levels: list[dict]
    ui_texts: dict[str, str]
    messages: dict[str, dict]
    domain: DomainConfig

    # ---------------------------------------------------------- 便捷读取

    def text(self, key: str, fallback: str = "") -> str:
        return self.ui_texts.get(key, fallback)

    def message(self, code: str, fallback: str = "") -> str:
        item = self.messages.get(code)
        return fallback if item is None else item["body"]

    def message_title(self, code: str, fallback: str = "") -> str:
        item = self.messages.get(code)
        if item is None or not item.get("title"):
            return fallback
        return item["title"]

    def dict_items(self, type_code: str) -> list[dict]:
        return self.dictionaries.get(type_code, [])

    def dict_codes(self, type_code: str) -> set[str]:
        return {item["code"] for item in self.dict_items(type_code)}

    def dict_name(self, type_code: str, code: str, fallback: str = "") -> str:
        for item in self.dict_items(type_code):
            if item["code"] == code:
                return item["name"]
        return fallback

    def source_attribute(self, source_code: str, key: str, default=None):
        for item in self.dict_items("income_source"):
            if item["code"] == source_code:
                attributes = item.get("attributes") or {}
                return attributes.get(key, default)
        return default


def _required(settings: dict, key: str):
    if key not in settings or settings[key] is None:
        raise ConfigurationError(f"缺少必要配置项：{key}", field=key)
    return settings[key]


def _required_param(params: dict, key: str) -> float:
    if key not in params or params[key] is None:
        raise ConfigurationError(f"缺少必要模型参数：{key}", field=key)
    return float(params[key])


def build_domain_config(settings: dict, dictionaries: dict[str, list[dict]],
                        accounts: list[dict], risk_levels: list[dict],
                        params: dict[str, float]) -> DomainConfig:
    bounds = SimulationBounds(
        default_months=int(_required(settings, "simulation.default_months")),
        default_paths=int(_required(settings, "simulation.default_paths")),
        default_seed=int(_required(settings, "simulation.default_seed")),
        min_months=int(_required(settings, "simulation.min_months")),
        max_months=int(_required(settings, "simulation.max_months")),
        min_paths=int(_required(settings, "simulation.min_paths")),
        max_paths=int(_required(settings, "simulation.max_paths")),
        max_path_months=int(_required(settings, "simulation.max_path_months")),
        max_goals=int(_required(settings, "limits.max_goals")),
        max_income_sources=int(_required(settings, "limits.max_income_sources")),
    )
    # 模型系数的唯一来源是参数表，与展示给使用者的参数值保持一致
    model = ModelCoefficients(
        sudden_freq_per_year=_required_param(params, "sudden_freq"),
        sudden_low=_required_param(params, "sudden_low"),
        sudden_high=_required_param(params, "sudden_high"),
        emergency_months=_required_param(params, "emergency_months"),
    )
    solver = SolverConfig(
        target_probability=float(_required(settings, "solver.target_probability")),
        tolerance=float(_required(settings, "solver.tolerance")),
        max_iterations=int(_required(settings, "solver.max_iterations")),
    )
    capacity = CapacityConfig(
        calendar_months=int(_required(settings, "capacity.calendar_months")),
        pending_ramp_months=int(_required(settings, "capacity.pending_ramp_months")),
        rigidity_high=float(_required(settings, "capacity.rigidity_high")),
        rigidity_low=float(_required(settings, "capacity.rigidity_low")),
    )
    scoring = ScoringConfig(
        weight_cushion=float(_required(settings, "scoring.weight_cushion")),
        weight_rigidity=float(_required(settings, "scoring.weight_rigidity")),
        weight_stability=float(_required(settings, "scoring.weight_stability")),
        norm_cushion_min=float(_required(settings, "scoring.norm_cushion_min")),
        norm_cushion_max=float(_required(settings, "scoring.norm_cushion_max")),
        norm_cv_max=float(_required(settings, "scoring.norm_cv_max")),
    )
    scenario = ScenarioConfig(
        pessimistic_factor=float(_required(settings, "scenario.pessimistic_factor")),
        base_factor=float(_required(settings, "scenario.base_factor")),
        optimistic_factor=float(_required(settings, "scenario.optimistic_factor")),
    )
    appetite_caps: dict[str, float] = {}
    for item in dictionaries.get("risk_appetite", []):
        attributes = item.get("attributes") or {}
        if "cap" in attributes:
            appetite_caps[item["code"]] = float(attributes["cap"])

    return DomainConfig(
        bounds=bounds, model=model, solver=solver, capacity=capacity, scoring=scoring,
        scenario=scenario,
        risk_levels=tuple(RiskLevel(code=row["code"], name=row["name"],
                                    min_cushion_months=float(row["min_cushion_months"]),
                                    equity_cap=float(row["equity_cap"])) for row in risk_levels),
        accounts=tuple(AccountDefinition(code=row["code"], name=row["name"],
                                         color=row["color"], priority=int(row["priority"]))
                       for row in accounts),
        appetite_caps=appetite_caps,
    )


def load_catalog(conn: sqlite3.Connection | None = None) -> Catalog:
    """装配配置目录。数据库中的数据必须完整，否则直接报错而不是回落兜底。"""
    def build(session_conn: sqlite3.Connection) -> Catalog:
        settings = config_repo.settings(session_conn)
        dictionaries = config_repo.dictionaries(session_conn)
        accounts = config_repo.accounts(session_conn)
        risk_levels = config_repo.risk_levels(session_conn)
        ui_texts = config_repo.ui_texts(session_conn)
        messages = config_repo.messages(session_conn)
        params = param_repo.param_values(session_conn)
        return Catalog(
            settings=settings, dictionaries=dictionaries, accounts=accounts,
            risk_levels=risk_levels, ui_texts=ui_texts, messages=messages,
            domain=build_domain_config(settings, dictionaries, accounts, risk_levels, params),
        )

    if conn is not None:
        return build(conn)
    with connection.session() as session_conn:
        return build(session_conn)


def get_catalog(refresh: bool = False) -> Catalog:
    global _CACHE
    if _CACHE is None or refresh:
        _CACHE = load_catalog()
    return _CACHE


def invalidate() -> None:
    """任何配置写入之后调用，下一次读取时重建。"""
    global _CACHE
    _CACHE = None


# ---------------------------------------------------------------- 接口目录


def catalog_payload(catalog: Catalog | None = None) -> dict:
    """一次返回前端启动所需的全部枚举、文案与配置。"""
    catalog = catalog or get_catalog()
    with connection.session() as conn:
        params = param_repo.param_values(conn)
        param_rows = param_repo.list_params(conn)
    property_names = {item["code"]: item["name"] for item in catalog.dict_items("param_property")}
    for row in param_rows:
        row["property_name"] = property_names.get(row["property"], row["property"])
    return {
        "dictionaries": catalog.dictionaries,
        "uiTexts": catalog.ui_texts,
        "messages": catalog.messages,
        "accounts": sorted(catalog.accounts, key=lambda item: item["sort_order"]),
        "riskLevels": catalog.risk_levels,
        "settings": {key: value for key, value in catalog.settings.items() if not key.startswith("_")},
        "parameters": params,
        "parameterRows": param_rows,
    }


def parameters_payload(catalog: Catalog | None = None) -> dict:
    with connection.session() as conn:
        rows = param_repo.list_params(conn)
        sources = param_repo.list_sources(conn)
    dictionary = {item["code"]: item for item in (catalog or get_catalog()).dict_items("param_property")}
    for row in rows:
        item = dictionary.get(row["property"])
        row["property_name"] = item["name"] if item else row["property"]
        row["property_tone"] = (item.get("attributes") or {}).get("tone") if item else None
    return {"rows": rows, "sources": sources}
