"""领域层测试。领域层是纯计算，测试直接构造画像与配置，不经过接口。"""

from __future__ import annotations

import dataclasses

import numpy as np

from backend.domain import allocation as allocation_domain
from backend.domain import capacity as capacity_domain
from backend.domain import planner as planner_domain
from backend.domain import simulation as simulation_domain


def _prepare(profile, catalog):
    path_set = simulation_domain.build_paths(profile, catalog.domain)
    sim = simulation_domain.simulate(profile, path_set, config=catalog.domain)
    alloc = allocation_domain.allocate(profile, sim, catalog.domain)
    capacity = capacity_domain.assess(profile, sim, alloc, catalog.domain)
    return path_set, sim, alloc, capacity


def test_reproducible(domain_profile, catalog):
    """同一画像与同一种子，两次推演结果完全一致。"""
    _, first, _, _ = _prepare(domain_profile, catalog)
    _, second, _, _ = _prepare(domain_profile, catalog)
    assert first.median_end_balance == second.median_end_balance
    for a, b in zip(first.goal_results, second.goal_results, strict=True):
        assert a.hit_probability == b.hit_probability
        assert a.hit_month_p50 == b.hit_month_p50


def test_seed_changes_result(domain_profile, catalog):
    other = dataclasses.replace(domain_profile, seed=domain_profile.seed + 1)
    _, base, _, _ = _prepare(domain_profile, catalog)
    _, changed, _, _ = _prepare(other, catalog)
    assert base.median_end_balance != changed.median_end_balance


def test_no_negative_balance(domain_profile, catalog):
    _, sim, _, _ = _prepare(domain_profile, catalog)
    assert min(sim.balance_p10) >= 0


def test_quantile_is_none_when_unreachable(domain_profile, catalog):
    """半数以上路径在推演期内未达成时，中位达成月必须为空值。"""
    profile = dataclasses.replace(domain_profile, goals=tuple(
        dataclasses.replace(goal, amount=5_000_000) for goal in domain_profile.goals))
    _, sim, _, _ = _prepare(profile, catalog)
    for goal in sim.goal_results:
        assert goal.reached_rate < 0.5
        assert goal.hit_month_p50 is None


def test_shortfall_paths_within_bounds(domain_profile, catalog):
    _, sim, _, _ = _prepare(domain_profile, catalog)
    for goal in sim.goal_results:
        assert 0 <= goal.shortfall_paths <= sim.paths
    assert sim.deficit_paths <= sim.paths


def test_allocation_conservation(domain_profile, catalog):
    _, _, alloc, _ = _prepare(domain_profile, catalog)
    assert alloc.conservation_ok is True
    for month in alloc.monthly[:36]:
        assert abs(sum(month["accounts"].values()) - month["available"]) < 0.01


def test_allocation_priority(domain_profile, catalog):
    """安全底座未填满时，体验悦己与长期复利不分配资金。"""
    _, _, alloc, _ = _prepare(domain_profile, catalog)
    assert alloc.priority_ok is True
    target = alloc.emergency_target
    for index, month in enumerate(alloc.monthly):
        if alloc.series["safe"][index] < target - 0.01:
            assert month["accounts"].get("treat", 0) == 0
            assert month["accounts"].get("compound", 0) == 0


def test_capacity_monotone_bounds(domain_profile, catalog):
    _, _, _, capacity = _prepare(domain_profile, catalog)
    assert len(capacity.calendar) == catalog.domain.capacity.calendar_months
    for item in capacity.calendar:
        assert item["final_cap"] <= item["level_cap"] + 1e-9
        assert item["final_cap"] <= item["appetite_cap"] + 1e-9
    assert capacity.cushion_min <= capacity.cushion_max


def test_planner_reuses_paths(domain_profile, catalog):
    """同一批路径重复求解必须得到同一答案。"""
    path_set, sim, _, _ = _prepare(domain_profile, catalog)
    goal_id = planner_domain.primary_goal(domain_profile).goal_id
    first = planner_domain.solve(domain_profile, path_set, goal_id, catalog.domain)
    second = planner_domain.solve(domain_profile, path_set, goal_id, catalog.domain)
    assert first["base_probability"] == second["base_probability"]
    assert [item["treat_monthly"] for item in first["plans"]] == \
           [item["treat_monthly"] for item in second["plans"]]


def test_planner_result_within_feasible_region(domain_profile, catalog):
    path_set, _, _, _ = _prepare(domain_profile, catalog)
    goal_id = planner_domain.primary_goal(domain_profile).goal_id
    plan = planner_domain.solve(domain_profile, path_set, goal_id, catalog.domain)
    compress = plan["plans"][0]
    if compress["feasible"] and not compress["keep_current"]:
        assert compress["achieved_probability"] >= plan["target_probability"] - 1e-9
        assert compress["treat_monthly"] <= domain_profile.treat_budget


def test_planner_handles_zero_budget(domain_profile, catalog):
    profile = dataclasses.replace(domain_profile, treat_budget=0.0)
    path_set = simulation_domain.build_paths(profile, catalog.domain)
    goal_id = planner_domain.primary_goal(profile).goal_id
    plan = planner_domain.solve(profile, path_set, goal_id, catalog.domain)
    compress = plan["plans"][0]
    assert compress["treat_monthly"] is None or compress["treat_monthly"] == 0
    assert compress["delta_amount"] <= 0


def test_income_sources_drive_distribution(domain_profile, catalog):
    """关掉全部不确定收入后，收入应只剩下生活费。"""
    profile = dataclasses.replace(domain_profile, income_sources=tuple(
        dataclasses.replace(item, enabled=item.distribution == "fixed")
        for item in domain_profile.income_sources))
    path_set = simulation_domain.build_paths(profile, catalog.domain)
    fixed = domain_profile.living_cost * np.power(
        1 + domain_profile.living_growth, np.arange(profile.months) // 12)
    assert np.allclose(path_set.income.mean(axis=0), fixed, rtol=1e-6)


def test_balance_vectorisation_matches_loop(domain_profile, catalog):
    """余额递推的向量化实现与逐路径循环等价。"""
    path_set, sim, _, _ = _prepare(domain_profile, catalog)
    net = path_set.income - path_set.sudden - (path_set.fixed_expense + domain_profile.treat_budget)[None, :]
    reference = np.zeros(net.shape)
    for i in range(net.shape[0]):
        balance = domain_profile.initial_balance
        for m in range(net.shape[1]):
            balance = max(0.0, balance + net[i, m])
            reference[i, m] = balance
    assert np.allclose(np.asarray(sim.balance), reference, atol=1e-6)

def test_experience_account_receives_funds_once_safety_is_filled(catalog):
    """安全底座填满之后，体验悦己必须能按预算分到资金。

    长期复利没有上限。它一旦排在体验悦己之前，就会吸走全部剩余资金，
    使「允许用户设置体验悦己预算」这一设定完全失效。
    """
    from backend.db import connection
    from backend.db.repository import archetype as arch_repo
    from backend.services import profile as profile_service

    # 本用例需要画像本来的规模，因此不借用缩小过样本量的夹具
    with connection.session() as conn:
        raw = arch_repo.to_profile(arch_repo.get_archetype(conn, "intern_junior"))
    profile = profile_service.normalize_and_validate(raw, catalog)
    path_set = simulation_domain.build_paths(profile, catalog.domain)
    sim = simulation_domain.simulate(profile, path_set, config=catalog.domain)
    alloc = allocation_domain.allocate(profile, sim, catalog.domain)

    order = list(alloc.order)
    assert order.index("treat") < order.index("compound"), (
        "体验悦己必须排在长期复利之前，否则永远分不到资金")

    # monthly 记录当月新增额，series 才是累计余额，判断填满要看后者
    safe = alloc.series["safe"]
    treat = alloc.series["treat"]
    filled_index = [i for i, value in enumerate(safe)
                    if value >= alloc.emergency_target - 1e-6]
    assert filled_index, "该画像在推演期内没有填满安全底座，本用例无从验证"
    assert any(treat[i] > 0 for i in filled_index), (
        "安全底座已经填满，体验悦己仍然分到零")


def test_allocation_order_matches_account_definition(domain_profile, catalog):
    """分配顺序取自账户定义的优先级，两者不得出现分歧。"""
    _, _, alloc, _ = _prepare(domain_profile, catalog)
    assert list(alloc.order) == list(catalog.domain.account_order)


def test_capacity_does_not_improve_when_rigidity_exceeds_threshold(domain_profile, catalog):
    """目标刚性超过阈值时，风险容量只会向下调整，绝不会变宽松。"""
    from dataclasses import replace

    path_set = simulation_domain.build_paths(domain_profile, catalog.domain)
    sim = simulation_domain.simulate(domain_profile, path_set, config=catalog.domain)
    alloc = allocation_domain.allocate(domain_profile, sim, catalog.domain)
    base = capacity_domain.assess(domain_profile, sim, alloc, catalog.domain)

    # 把下调阈值降到零，意味着任何目标刚性都会触发下调
    strict = capacity_domain.assess(
        domain_profile, sim, alloc,
        replace(catalog.domain,
                capacity=replace(catalog.domain.capacity, rigidity_high=0.0)))
    assert strict.current["level_cap"] <= base.current["level_cap"] + 1e-9

    # 把上调阈值降到零，意味着「刚性低于阈值」永远不会成立，不再触发上调
    relaxed = capacity_domain.assess(
        domain_profile, sim, alloc,
        replace(catalog.domain,
                capacity=replace(catalog.domain.capacity, rigidity_low=0.0)))
    assert relaxed.current["level_cap"] <= base.current["level_cap"] + 1e-9

def test_expenses_drive_the_balance(catalog):
    """支出项必须真正影响推演结果，而不是被写死的比例替代。"""
    from dataclasses import replace

    from backend.db import connection
    from backend.db.repository import archetype as arch_repo
    from backend.services import profile as profile_service

    with connection.session() as conn:
        raw = arch_repo.to_profile(arch_repo.get_archetype(conn, "intern_junior"))
    profile = profile_service.normalize_and_validate(raw, catalog)

    def run(item):
        path_set = simulation_domain.build_paths(item, catalog.domain)
        return simulation_domain.simulate(item, path_set, config=catalog.domain)

    base = run(profile)
    inflated = replace(profile, expenses=tuple(
        replace(expense, amount=expense.amount * 1.5) for expense in profile.expenses))
    changed = run(inflated)
    assert changed.median_end_balance < base.median_end_balance
    # 刚需项金额放大后，应急金目标（刚需×月数）也应同步放大
    assert changed.emergency_target > base.emergency_target

def test_archetype_goal_probabilities_are_meaningful(catalog):
    """三份内置财务画像的主目标达成率应落在 30% 到 85% 之间。

    既不能高到必然成功（推演失去意义），也不能低到必然失败（画像自相矛盾）。
    """
    from backend.db import connection
    from backend.db.repository import archetype as arch_repo
    from backend.services import profile as profile_service

    for aid in ("intern_junior", "postgrad_exam", "civil_service"):
        with connection.session() as conn:
            raw = arch_repo.to_profile(arch_repo.get_archetype(conn, aid))
        profile = profile_service.normalize_and_validate(raw, catalog)
        path_set = simulation_domain.build_paths(profile, catalog.domain)
        sim = simulation_domain.simulate(profile, path_set, config=catalog.domain)
        primary = sim.goal_results[0]
        assert 0.30 < primary.hit_probability < 0.85, (
            f"画像 {profile.name} 主目标达成率 {primary.hit_probability:.0%} 超出合理区间")
