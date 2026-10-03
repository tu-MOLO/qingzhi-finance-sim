"""反事实分析的测试。

扰动一次就能拿到全部目标的结果，因此多目标不应该只多花时间、
却只留下首要目标的一组数。这里守住「每个目标都有自己的一组数」这条线。
"""

from __future__ import annotations

from backend.services import whatif as whatif_service


def test_analyze_covers_every_goal(domain_profile, catalog):
    result = whatif_service.analyze(domain_profile, catalog)
    goals = result["goals"]
    assert goals
    assert [item["goalId"] for item in goals] == [
        item["goalId"] for item in sorted(goals, key=lambda x: x["priority"])]
    assert goals[0]["goalId"] == result["goal"]["goalId"]
    assert all("baseProbability" in item for item in goals)


def test_analyze_rows_carry_per_goal_numbers(domain_profile, catalog):
    result = whatif_service.analyze(domain_profile, catalog)
    goal_ids = {item["goalId"] for item in result["goals"]}
    assert result["rows"], "参数表里应当有可扰动的参数"
    for row in result["rows"]:
        assert set(row["byGoal"]) == goal_ids, f"行 {row['key']} 没有覆盖全部目标"
        for bucket in row["byGoal"].values():
            assert 0.0 <= bucket["lowProbability"] <= 1.0
            assert 0.0 <= bucket["highProbability"] <= 1.0
            assert bucket["swing"] >= 0.0


def test_analyze_rows_are_sorted_by_strongest_swing(domain_profile, catalog):
    result = whatif_service.analyze(domain_profile, catalog)
    strengths = [max(bucket["swing"] for bucket in row["byGoal"].values())
                 for row in result["rows"]]
    assert strengths == sorted(strengths, reverse=True)


def test_analyze_keeps_primary_goal_on_top(domain_profile, catalog):
    """首要目标的数值仍在行的顶层，既有的读法不受影响。"""
    result = whatif_service.analyze(domain_profile, catalog)
    primary = result["goal"]["goalId"]
    for row in result["rows"]:
        assert row["swing"] == row["byGoal"][primary]["swing"]
        assert row["lowProbability"] == row["byGoal"][primary]["lowProbability"]
        assert row["highProbability"] == row["byGoal"][primary]["highProbability"]
