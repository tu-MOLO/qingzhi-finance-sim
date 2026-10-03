"""智能体能力的测试。

覆盖三件事：定义与处理器的对应关系是否完整、工具与渲染器的行为是否正确、
以及生成路径在外部模型不可用时是否确实回落到本地规则。
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.agents import providers, registry, runtime
from backend.agents.protocol import PROVIDER_MODEL, PROVIDER_RULE, AgentContext
from backend.agents.tools import TOOL_HANDLERS, format_amount, format_months
from backend.common.errors import AppError, ConfigurationError, NotFoundError
from backend.db import connection
from backend.services import agent as agent_service
from backend.services.configuration import Catalog

# ---------------------------------------------------------------- 定义完整性


def test_agents_are_seeded(conn: sqlite3.Connection):
    agents = registry.list_agents(conn)
    assert len(agents) >= 2
    codes = {item["code"] for item in agents}
    assert "term_explain" in codes
    assert "plan_insight" in codes


def test_every_bound_tool_has_a_handler(conn: sqlite3.Connection):
    """绑定关系里的每个工具都必须在代码中存在处理器。"""
    for agent in registry.list_agents(conn):
        for tool in registry.bound_tools(conn, agent["code"]):
            assert tool["handler"] in TOOL_HANDLERS, (
                f"智能体 {agent['code']} 绑定了没有实现的工具 {tool['code']}")


def test_self_check_reports_no_problem(conn: sqlite3.Connection):
    assert agent_service.self_check(conn) == []


def test_output_schema_is_decoded(conn: sqlite3.Connection):
    """提示词中的输出结构以 JSON 文本落库，读出来应当是字典。"""
    for agent in registry.list_agents(conn):
        assert isinstance(agent["output_schema"], dict)


# ---------------------------------------------------------------- 工具


def test_corpus_lookup_extracts_excerpt(conn: sqlite3.Connection):
    term = _term(conn, "max_drawdown")
    ctx = AgentContext(term=term)
    outcome = TOOL_HANDLERS["corpus_lookup"](ctx)
    assert outcome.ok
    assert outcome.data["count"] >= 1
    for item in ctx.shared["corpus"]:
        assert item["title"]
        assert item["excerpt"]
        assert len(item["excerpt"]) <= 260


def test_corpus_lookup_without_sources_is_skipped():
    ctx = AgentContext(term={"term_code": "x", "source_documents": []})
    outcome = TOOL_HANDLERS["corpus_lookup"](ctx)
    assert outcome.status == "skipped"
    assert ctx.shared["corpus"] == []


def test_simulation_context_reads_goal(conn: sqlite3.Connection):
    ctx = AgentContext(snapshot=_snapshot())
    outcome = TOOL_HANDLERS["simulation_context"](ctx)
    assert outcome.data["hasGoal"] is True
    goal = ctx.shared["goal"]
    assert goal["name"]
    assert goal["probabilityText"].endswith("%")
    assert ctx.shared["capacity"]["finalCapText"].endswith("%")


@pytest.mark.parametrize("snapshot", [None, {}, {"primaryGoal": "字符串"},
                                      {"primaryGoal": {"name": "缺编码"}}])
def test_simulation_context_without_goal(snapshot):
    """任何不完整的摘要都按无目标处理，绝不伪造数字。"""
    ctx = AgentContext(snapshot=snapshot or {})
    outcome = TOOL_HANDLERS["simulation_context"](ctx)
    assert outcome.status == "skipped"
    assert ctx.shared["goal"] is None


def test_simulation_context_keeps_every_goal(conn: sqlite3.Connection):
    """清单里有几个目标就准备几个，主目标仍是排在最前的那个。"""
    ctx = AgentContext(snapshot=_multi_goal_snapshot())
    TOOL_HANDLERS["simulation_context"](ctx)
    goals = ctx.shared["goals"]
    assert [item["name"] for item in goals] == ["考研升学备付金", "考证与课程", "毕业旅行"]
    assert ctx.shared["goal"]["goalId"] == "g1"
    assert goals[1]["probabilityText"].endswith("%")
    assert goals[2]["gapText"]


def test_simulation_context_falls_back_to_primary_goal(conn: sqlite3.Connection):
    """只给了主目标的老摘要照样能出上下文。"""
    ctx = AgentContext(snapshot=_snapshot())
    TOOL_HANDLERS["simulation_context"](ctx)
    assert len(ctx.shared["goals"]) == 1
    assert ctx.shared["goal"]["goalId"] == "g1"


def test_scenario_compare_covers_every_goal(conn: sqlite3.Connection):
    ctx = AgentContext(snapshot=_multi_goal_snapshot())
    TOOL_HANDLERS["simulation_context"](ctx)
    TOOL_HANDLERS["scenario_compare"](ctx)
    by_goal = ctx.shared["scenarios"]["byGoal"]
    assert set(by_goal) == {"g1", "g2", "g3"}
    assert by_goal["g3"]["optimisticText"].endswith("%")


def test_plan_insight_mentions_every_goal(conn: sqlite3.Connection):
    """解读不能只讲主目标：每个目标都要在要点里出现。"""
    ctx = AgentContext(snapshot=_multi_goal_snapshot())
    TOOL_HANDLERS["simulation_context"](ctx)
    TOOL_HANDLERS["scenario_compare"](ctx)
    TOOL_HANDLERS["allocation_profile"](ctx)
    output = providers.render({"code": "plan_insight"}, ctx)
    joined = "\n".join(output["points"])
    for name in ("考研升学备付金", "考证与课程", "毕业旅行"):
        assert name in joined, f"解读漏掉了目标 {name}"


def test_scenario_compare_needs_both_sides(conn: sqlite3.Connection):
    ctx = AgentContext(snapshot=_snapshot())
    TOOL_HANDLERS["simulation_context"](ctx)
    outcome = TOOL_HANDLERS["scenario_compare"](ctx)
    assert outcome.ok
    scenarios = ctx.shared["scenarios"]
    assert scenarios is None or "values" in scenarios


def test_amount_formatter_uses_wan_unit(conn: sqlite3.Connection):
    ctx = AgentContext(snapshot=_snapshot(), settings={"explain.drawdown_reference_ratio": 0.2})
    TOOL_HANDLERS["simulation_context"](ctx)
    TOOL_HANDLERS["amount_formatter"](ctx)
    numeric = ctx.shared["numeric"]
    assert numeric["lossRatioText"] == "20%"
    assert numeric["amountText"].endswith(("元", "万元"))


def test_amount_formatter_covers_every_goal(conn: sqlite3.Connection):
    ctx = AgentContext(snapshot=_multi_goal_snapshot(),
                       settings={"explain.drawdown_reference_ratio": 0.2})
    TOOL_HANDLERS["simulation_context"](ctx)
    TOOL_HANDLERS["amount_formatter"](ctx)
    numerics = ctx.shared["numerics"]
    assert [item["goalId"] for item in numerics] == ["g1", "g2", "g3"]
    assert all(item["lossText"] for item in numerics)
    # numeric 仍然指向首要目标，只讲一个目标的环节不受影响
    assert ctx.shared["numeric"]["goalId"] == "g1"


def test_amount_formatter_without_goal_is_empty():
    ctx = AgentContext(snapshot={}, settings={"explain.drawdown_reference_ratio": 0.2})
    TOOL_HANDLERS["simulation_context"](ctx)
    TOOL_HANDLERS["amount_formatter"](ctx)
    assert ctx.shared["numerics"] == []
    assert ctx.shared["numeric"] is None


def test_format_helpers():
    assert format_amount(None) == "—"
    assert format_amount(9800).endswith("元")
    assert format_amount(55000).endswith("万元")
    assert format_months(None) == "尚未达成"
    assert "月" in format_months(30)


def test_compliance_guard_blocks_numbers_without_goal():
    messages = {"compliance.no_goal": {"body": "您当前尚未设置目标，暂不生成量化说明"}}
    ctx = AgentContext(messages=messages)
    ctx.shared["output"] = {"layer3": "目标会推迟 12 个月", "points": ["减少 3000 元"]}
    outcome = TOOL_HANDLERS["compliance_guard"](ctx)
    assert outcome.status == "replaced"
    assert not any(ch.isdigit() for ch in ctx.shared["output"]["layer3"])
    assert ctx.shared["output"]["points"] == []


def test_compliance_guard_blocks_forbidden_clause():
    ctx = AgentContext(
        messages={"compliance.no_goal": {"body": "合规文案"}},
        settings={"agent.forbidden_phrases": "保证收益,稳赚"})
    ctx.shared["goal"] = {"goalId": "g1", "name": "目标"}
    ctx.shared["output"] = {"layer3": "这款产品保证收益"}
    outcome = TOOL_HANDLERS["compliance_guard"](ctx)
    assert outcome.ok is False
    assert outcome.status == "failed"


def test_compliance_guard_appends_disclaimer():
    ctx = AgentContext(messages={"disclaimer.term": {"title": "免责", "body": "仅供参考"}})
    ctx.shared["goal"] = {"goalId": "g1", "name": "目标"}
    ctx.shared["output"] = {"layer3": "这是一段说明"}
    outcome = TOOL_HANDLERS["compliance_guard"](ctx)
    assert outcome.ok
    assert ctx.shared["output"]["disclaimer"] == "仅供参考"


# ---------------------------------------------------------------- 渲染器


def test_render_term_explain_links_goal(conn: sqlite3.Connection):
    ctx = _prepared_context(conn, with_goal=True)
    output = providers.render({"code": "term_explain"}, ctx)
    assert output["layer3"]
    assert output["hasNumbers"] is True
    assert output["linkedGoalName"]


def test_render_term_explain_without_goal_has_no_numbers(conn: sqlite3.Connection):
    ctx = _prepared_context(conn, with_goal=False)
    ctx.messages["compliance.no_goal"] = {"body": "请先设置目标"}
    output = providers.render({"code": "term_explain"}, ctx)
    assert output["hasNumbers"] is False
    assert not any(ch.isdigit() for ch in output["layer3"])


def test_render_term_explain_with_goal_but_no_numbers(conn: sqlite3.Connection):
    """有目标却拿不到推演数字时，只讲目标本身，不编造任何数值。"""
    ctx = _prepared_context(conn, with_goal=True)
    ctx.shared["numeric"] = None
    ctx.shared["numerics"] = []
    output = providers.render({"code": "term_explain"}, ctx)
    assert output["hasNumbers"] is False
    assert not any(ch.isdigit() for ch in output["layer3"])
    assert output["linkedGoalName"]


def test_render_term_explain_mentions_other_goals(conn: sqlite3.Connection):
    ctx = _prepared_context(conn, with_goal=True)
    ctx.snapshot = _multi_goal_snapshot()
    for code in ("simulation_context", "amount_formatter"):
        TOOL_HANDLERS[code](ctx)
    output = providers.render({"code": "term_explain"}, ctx)
    assert output["linkedGoalIds"] == ["g1", "g2", "g3"]
    assert "考证与课程" in output["layer3"]
    assert "毕业旅行" in output["layer3"]


def test_plan_insight_scenarios_cover_every_goal(conn: sqlite3.Connection):
    ctx = AgentContext(snapshot=_multi_goal_snapshot())
    for code in ("simulation_context", "scenario_compare", "amount_formatter"):
        TOOL_HANDLERS[code](ctx)
    output = providers.render({"code": "plan_insight"}, ctx)
    lines = [point for point in output["points"] if "三档情景" in point]
    assert lines
    for name in ("考研升学备付金", "考证与课程", "毕业旅行"):
        assert name in lines[0], f"情景行漏掉了目标 {name}"


def test_plan_insight_tail_covers_every_goal(conn: sqlite3.Connection):
    ctx = AgentContext(snapshot=_multi_goal_snapshot())
    for code in ("simulation_context", "scenario_compare", "amount_formatter"):
        TOOL_HANDLERS[code](ctx)
    output = providers.render({"code": "plan_insight"}, ctx)
    tail = output["points"][-1]
    for name in ("考研升学备付金", "考证与课程", "毕业旅行"):
        assert name in tail, f"末句漏掉了目标 {name}"


def test_plan_insight_states_goal_count_before_capacity(conn: sqlite3.Connection):
    """共几个目标要紧接首要目标交代，不能落在容量等级之后。"""
    ctx = AgentContext(snapshot=_multi_goal_snapshot())
    for code in ("simulation_context", "scenario_compare", "amount_formatter"):
        TOOL_HANDLERS[code](ctx)
    headline = providers.render({"code": "plan_insight"}, ctx)["headline"]
    assert "共纳入 3 个目标" in headline
    assert headline.index("共纳入 3 个目标") < headline.index("风险容量等级")


def test_render_plan_insight_produces_points(conn: sqlite3.Connection):
    ctx = _prepared_context(conn, with_goal=True)
    output = providers.render({"code": "plan_insight"}, ctx)
    assert output["headline"]
    assert len(output["points"]) >= 2
    assert isinstance(output["riskNote"], str)


def test_render_unknown_agent_raises(conn: sqlite3.Connection):
    ctx = _prepared_context(conn, with_goal=True)
    with pytest.raises(providers.ProviderError):
        providers.render({"code": "nobody"}, ctx)


# ---------------------------------------------------------------- 路径选择


def test_choose_provider_defaults_to_rule(conn: sqlite3.Connection, catalog: Catalog):
    agent = registry.get_agent(conn, "term_explain")
    provider, reason = providers.choose_provider(agent, catalog.settings)
    assert provider == PROVIDER_RULE
    assert reason


def test_choose_provider_needs_address_and_model(conn: sqlite3.Connection, catalog: Catalog):
    agent = registry.get_agent(conn, "term_explain")
    opened = dict(catalog.settings)
    opened["agent.allow_network"] = True
    opened["agent.provider"] = PROVIDER_MODEL
    assert providers.choose_provider(agent, opened)[0] == PROVIDER_RULE
    opened["agent.base_url"] = "http://127.0.0.1:1/v1"
    assert providers.choose_provider(agent, opened)[0] == PROVIDER_RULE
    opened["agent.model"] = "local"
    assert providers.choose_provider(agent, opened) == (PROVIDER_MODEL, None)


def test_network_gate_wins_over_provider(conn: sqlite3.Connection, catalog: Catalog):
    """即使生成方式设为模型，只要不允许联网就必须走本地规则。"""
    agent = registry.get_agent(conn, "term_explain")
    settings = dict(catalog.settings)
    settings["agent.provider"] = PROVIDER_MODEL
    settings["agent.base_url"] = "http://127.0.0.1:1/v1"
    settings["agent.model"] = "local"
    settings["agent.allow_network"] = False
    assert providers.choose_provider(agent, settings)[0] == PROVIDER_RULE


def test_agent_can_force_local_rule(conn: sqlite3.Connection, catalog: Catalog):
    """智能体自己指定为规则路径时，不与全局配置冲突。"""
    agent = dict(registry.get_agent(conn, "term_explain"))
    agent["provider"] = PROVIDER_RULE
    settings = dict(catalog.settings)
    settings["agent.allow_network"] = True
    settings["agent.provider"] = PROVIDER_MODEL
    settings["agent.base_url"] = "http://127.0.0.1:1/v1"
    settings["agent.model"] = "local"
    assert providers.choose_provider(agent, settings)[0] == PROVIDER_RULE


def test_unreachable_model_falls_back(conn: sqlite3.Connection, catalog: Catalog):
    """外部模型连不上时，结果仍然由本地规则产出并标记降级。"""
    agent = registry.get_agent(conn, "term_explain")
    settings = dict(catalog.settings)
    settings.update({
        "agent.allow_network": True,
        "agent.provider": PROVIDER_MODEL,
        "agent.base_url": "http://127.0.0.1:1/v1",
        "agent.model": "local",
        "agent.timeout_seconds": 2,
        "agent.max_attempts": 1,
        "agent.temperature": 0.2,
        "agent.max_tokens": 800,
    })
    ctx = _prepared_context(conn, with_goal=True)
    outcome = providers.generate(agent, ctx, settings, PROVIDER_MODEL, None)
    assert outcome.degraded is True
    assert outcome.provider == PROVIDER_RULE
    assert outcome.output["layer3"]


def test_missing_model_settings_are_reported(conn: sqlite3.Connection, catalog: Catalog):
    """配置缺失必须报错，而不是回落到代码里的默认值。"""
    agent = registry.get_agent(conn, "term_explain")
    settings = {key: value for key, value in catalog.settings.items()
                if not key.startswith("agent.")}
    ctx = _prepared_context(conn, with_goal=True)
    with pytest.raises(ConfigurationError):
        providers.generate(agent, ctx, settings, PROVIDER_MODEL, None)


# ---------------------------------------------------------------- 运行时


def test_run_records_steps_and_guard_stage(conn: sqlite3.Connection, catalog: Catalog):
    agent = registry.get_agent(conn, "term_explain")
    tools = registry.bound_tools(conn, "term_explain")
    ctx = _prepared_context(conn, with_goal=True)
    result = runtime.run(agent, tools, ctx, catalog.settings)

    assert result.provider == PROVIDER_RULE
    assert not result.degraded
    stages = [step.stage for step in result.steps]
    assert "generate" in stages
    assert stages[-1] == "guard"
    assert result.output["layer3"]


def test_run_unknown_agent_reports_missing_handler(conn: sqlite3.Connection, catalog: Catalog):
    agent = registry.get_agent(conn, "term_explain")
    tools = [{"code": "ghost", "name": "不存在的工具", "kind": "retrieval",
              "handler": "ghost_handler", "required": True}]
    ctx = _prepared_context(conn, with_goal=True)
    # 必需工具的处理器缺失属于配置错误，必须整体失败而不是静默跳过
    with pytest.raises(AppError):
        runtime.run(agent, tools, ctx, catalog.settings)


def test_invoke_unknown_agent(conn: sqlite3.Connection, catalog: Catalog):
    with pytest.raises(NotFoundError):
        agent_service.invoke(conn, "nobody", {}, catalog)


def test_invoke_returns_disclaimer_separately(conn: sqlite3.Connection, catalog: Catalog):
    result = agent_service.invoke(
        conn, "term_explain", {"term": "回撤", "snapshot": _snapshot()}, catalog)
    assert result["disclaimer"]["body"]
    # 免责提示单独返回后，输出体中不应再重复出现
    assert "disclaimer" not in result["output"]


# ---------------------------------------------------------------- 摘要清洗


def test_clean_snapshot_drops_malformed_fields():
    dirty = {
        "primaryGoal": {"goalId": "g1", "name": "目标", "amount": "abc",
                        "dueMonth": None, "hitMonthP50": [1]},
        "capacity": {"level": "低", "finalCap": "x", "dipMonths": [7, "8", None]},
        "scenarios": {"base": {"g1": 0.5}, "pessimistic": "不是字典"},
        "allocation": {"accounts": "不是列表"},
        "未知字段": {"x": 1},
    }
    cleaned = agent_service.clean_snapshot(dirty)
    assert cleaned["primaryGoal"]["amount"] == 0.0
    assert cleaned["primaryGoal"]["hitMonthP50"] is None
    assert cleaned["capacity"]["finalCap"] == 0.0
    assert cleaned["capacity"]["dipMonths"] == [7, 8]
    assert cleaned["scenarios"]["base"] == {"g1": 0.5}
    assert "pessimistic" not in cleaned["scenarios"]
    assert "allocation" not in cleaned
    assert "未知字段" not in cleaned


def test_clean_snapshot_keeps_goal_list_in_order():
    """清单逐项重建：缺编号的按行次序补上，结构不符的整项丢弃。"""
    cleaned = agent_service.clean_snapshot({
        "goals": [
            {"goalId": "g2", "name": "考证与课程", "amount": 6000, "priority": 2},
            "不是对象",
            {"goalId": "g1", "name": "升学备付金", "amount": 55000},
            {"name": "缺编号", "amount": 100},
        ]
    })
    assert [item["goalId"] for item in cleaned["goals"]] == ["g2", "g1"]
    assert [item["priority"] for item in cleaned["goals"]] == [2, 3]
    # 只给了清单时，排在最前的那个充当主目标
    assert cleaned["primaryGoal"]["goalId"] == "g2"


def test_clean_snapshot_repairs_bad_priority():
    """顺序不允许小于 1，越界值回落到所在行的次序。"""
    cleaned = agent_service.clean_snapshot({
        "goals": [{"goalId": "g1", "name": "甲", "priority": 0},
                  {"goalId": "g2", "name": "乙", "priority": -3}]
    })
    assert [item["priority"] for item in cleaned["goals"]] == [1, 2]


@pytest.mark.parametrize("raw", [None, "", [], 0, "字符串"])
def test_clean_snapshot_rejects_non_objects(raw):
    assert agent_service.clean_snapshot(raw) == {}


# ---------------------------------------------------------------- 助手


@pytest.fixture()
def conn():
    with connection.session() as session_conn:
        yield session_conn


def _term(conn: sqlite3.Connection, term_code: str) -> dict:
    from backend.db.repository import term as term_repo
    term = term_repo.get_term(conn, term_code)
    if term is None:
        term = term_repo.list_terms(conn)[0]
        term = term_repo.get_term(conn, term["term_code"])
    term["source_documents"] = term_repo.source_documents(conn, term["term_code"])
    return term


def _snapshot() -> dict:
    return {
        "primaryGoal": {"goalId": "g1", "name": "考研升学备付金", "amount": 55000,
                        "dueMonth": 30, "hitProbability": 0.42,
                        "hitMonthP50": 40, "reachedRate": 0.88},
        "capacity": {"level": "低", "finalCap": 0.2, "cushionMonths": 3.2, "dipMonths": [19, 31]},
        "scenarios": {"pessimistic": {"g1": 0.10}, "base": {"g1": 0.42},
                      "optimistic": {"g1": 0.71}},
        "allocation": {
            "accounts": [{"code": "safe", "name": "安全底座"},
                         {"code": "growth", "name": "成长悦己"}],
            "order": ["safe", "growth"],
            "series": {"safe": [1000.0, 4000.0], "growth": [0.0, 300.0]},
            "emergencyTarget": 3690.0,
            "conservationOk": True,
            "priorityOk": True,
        },
    }


def _multi_goal_snapshot() -> dict:
    """三个目标的摘要，顺序故意打乱，交出去之前要按优先级排好。"""
    snapshot = _snapshot()
    snapshot["goals"] = [
        {"goalId": "g3", "name": "毕业旅行", "amount": 12000, "dueMonth": 42,
         "priority": 3, "hitProbability": 0.66, "hitMonthP50": 44,
         "reachedRate": 0.9, "gapAmount": 4200},
        {"goalId": "g1", "name": "考研升学备付金", "amount": 55000, "dueMonth": 30,
         "priority": 1, "hitProbability": 0.42, "hitMonthP50": 40,
         "reachedRate": 0.88, "gapAmount": 12000},
        {"goalId": "g2", "name": "考证与课程", "amount": 6000, "dueMonth": 12,
         "priority": 2, "hitProbability": 0.81, "hitMonthP50": 11,
         "reachedRate": 1.0, "gapAmount": 0},
    ]
    snapshot["scenarios"] = {
        "pessimistic": {"g1": 0.10, "g2": 0.52, "g3": 0.31},
        "base": {"g1": 0.42, "g2": 0.81, "g3": 0.66},
        "optimistic": {"g1": 0.71, "g2": 0.94, "g3": 0.88},
    }
    return snapshot


def _prepared_context(conn: sqlite3.Connection, with_goal: bool) -> AgentContext:
    ctx = AgentContext()
    ctx.term = _term(conn, "max_drawdown")
    ctx.query = ctx.term["name"]
    ctx.snapshot = _snapshot() if with_goal else {}
    ctx.settings = {"explain.drawdown_reference_ratio": 0.2}
    for code in ("corpus_lookup", "simulation_context", "scenario_compare",
                 "allocation_profile", "amount_formatter"):
        TOOL_HANDLERS[code](ctx)
    return ctx
