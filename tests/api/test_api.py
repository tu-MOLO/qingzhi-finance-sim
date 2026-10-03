"""接口层测试：契约、增删改查、输入边界与请求防护。"""

from __future__ import annotations

import copy

import pytest

REQUIRED_RUN_KEYS = [
    "profile", "simulation", "allocation", "capacity", "plan", "gaps", "scenarios",
    "snapshot", "pathsReused", "disclaimer",
]
REQUIRED_SIM_KEYS = [
    "seed", "months", "paths", "treatMonthly", "balancePercentiles", "goalResults",
    "deficitMonthsP10", "deficitMonthsP50", "deficitTotal", "deficitPaths",
    "medianEndBalance", "needMonthly", "incomeCv", "emergencyTarget",
]
REQUIRED_GOAL_KEYS = [
    "goalId", "name", "amount", "dueMonth", "priority", "hitProbability", "reachedRate",
    "hitMonthP10", "hitMonthP50", "hitMonthP90", "gapAmount", "shortfallPaths",
]


# ---------------------------------------------------------------- 配置目录


def test_health(client, api):
    code, body = api(client, "get", "/api/v1/health")
    assert code == 200
    assert body["data"]["localOnly"] is True


def test_catalog_complete(client, api):
    code, body = api(client, "get", "/api/v1/catalog")
    assert code == 200
    data = body["data"]
    for key in ("dictionaries", "uiTexts", "messages", "accounts", "riskLevels",
                "settings", "parameters"):
        assert key in data
    assert len(data["dictionaries"]["income_source"]) >= 4
    assert len(data["uiTexts"]) > 50
    assert len(data["accounts"]) >= 4


def test_parameters_carry_provenance(client, api):
    code, body = api(client, "get", "/api/v1/catalog/parameters")
    assert code == 200
    rows = body["data"]["rows"]
    assert rows
    for row in rows:
        assert row["name"]
        assert row["property"] in {"measured", "assumed", "conventional"}
        assert row["property_name"]


def test_dictionary_items_by_type(client, api):
    code, body = api(client, "get", "/api/v1/catalog/dictionary-items/income_source")
    assert code == 200
    codes = {item["code"] for item in body["data"]["items"]}
    assert {"living", "part_time", "scholarship", "internship"} <= codes


def test_unknown_dictionary_type(client, api):
    code, _ = api(client, "get", "/api/v1/catalog/dictionary-items/unknown_type")
    assert code == 404


# ---------------------------------------------------------------- 画像


def test_archetype_profile_is_runnable(client, api, profile_payload):
    code, body = api(client, "get", "/api/v1/archetypes/intern_junior/profile")
    assert code == 200
    assert body["data"]["profile"]["income_sources"]
    assert code == 200


def test_preview_returns_business_numbers(client, api, profile_payload):
    code, body = api(client, "post", "/api/v1/profile/preview", {"profile": profile_payload})
    assert code == 200
    data = body["data"]
    assert data["expected_income"] > 0
    assert data["need_monthly"] > 0
    assert isinstance(data["within_budget"], bool)


def test_preview_rejects_non_numeric(client, api, profile_payload):
    payload = copy.deepcopy(profile_payload)
    payload["living_cost"] = "很多钱"
    code, body = api(client, "post", "/api/v1/profile/preview", {"profile": payload})
    assert code == 400
    assert body["error"]["field"] == "living_cost"


def test_validate_rejects_unknown_enum(client, api, profile_payload):
    payload = copy.deepcopy(profile_payload)
    payload["grade"] = "g99"
    code, body = api(client, "post", "/api/v1/profile/validate", {"profile": payload})
    assert code == 400
    assert body["error"]["field"] == "grade"


def test_product_limit_enforced(client, api, profile_payload):
    payload = copy.deepcopy(profile_payload)
    payload["paths"] = 50000
    payload["months"] = 120
    code, body = api(client, "post", "/api/v1/simulation/run", {"profile": payload})
    assert code == 400
    assert body["error"]["field"] == "paths"


# ---------------------------------------------------------------- 推演


def test_run_contract(client, api, profile_payload):
    code, body = api(client, "post", "/api/v1/simulation/run", {"profile": profile_payload})
    assert code == 200
    data = body["data"]
    for key in REQUIRED_RUN_KEYS:
        assert key in data, key
    for key in REQUIRED_SIM_KEYS:
        assert key in data["simulation"], key
    for goal in data["simulation"]["goalResults"]:
        for key in REQUIRED_GOAL_KEYS:
            assert key in goal, key
    assert data["allocation"]["conservationOk"] is True
    assert data["allocation"]["priorityOk"] is True


def test_run_is_reproducible(client, api, profile_payload):
    first = api(client, "post", "/api/v1/simulation/run", {"profile": profile_payload})[1]["data"]
    second = api(client, "post", "/api/v1/simulation/run", {"profile": profile_payload})[1]["data"]
    assert first["simulation"]["medianEndBalance"] == second["simulation"]["medianEndBalance"]
    assert second["pathsReused"] is True


def test_plan_for_each_goal(client, api, profile_payload):
    result = api(client, "post", "/api/v1/simulation/run", {"profile": profile_payload})[1]["data"]
    for goal in result["simulation"]["goalResults"]:
        code, body = api(client, "post", "/api/v1/simulation/plan",
                         {"profile": profile_payload, "goalId": goal["goalId"]})
        assert code == 200
        data = body["data"]
        assert data["goal"]["goalId"] == goal["goalId"]
        assert len(data["plans"]) == 2
        assert data["pathsReused"] is True


def test_plan_unknown_goal(client, api, profile_payload):
    code, _ = api(client, "post", "/api/v1/simulation/plan",
                  {"profile": profile_payload, "goalId": "不存在"})
    assert code in (400, 404)


def test_plan_rejects_bad_goal_id(client, api, profile_payload):
    code, _ = api(client, "post", "/api/v1/simulation/plan",
                  {"profile": profile_payload, "goalId": 123})
    assert code == 400


# ---------------------------------------------------------------- 术语


def test_explain_without_goal_has_no_numbers(client, api):
    code, body = api(client, "post", "/api/v1/terms/explain",
                     {"term": "最大回撤", "snapshot": None})
    assert code == 200
    assert body["data"]["hasNumbers"] is False
    assert not any(ch.isdigit() for ch in body["data"]["layer3"])


def test_explain_with_goal_links_target(client, api, profile_payload):
    result = api(client, "post", "/api/v1/simulation/run", {"profile": profile_payload})[1]["data"]
    code, body = api(client, "post", "/api/v1/terms/explain",
                     {"term": "回撤", "snapshot": result["snapshot"]})
    assert code == 200
    assert body["data"]["term"] == "最大回撤"
    assert body["data"]["linkedGoalName"]


def test_explain_unknown_term(client, api):
    code, _ = api(client, "post", "/api/v1/terms/explain", {"term": "量子基金"})
    assert code == 404


def test_explain_rejects_bad_snapshot(client, api):
    code, body = api(client, "post", "/api/v1/terms/explain",
                     {"term": "最大回撤", "snapshot": [1, 2, 3]})
    assert code == 400
    assert body["error"]["field"] == "snapshot"


def test_explain_tolerates_malformed_snapshot(client, api):
    code, body = api(client, "post", "/api/v1/terms/explain",
                     {"term": "最大回撤", "snapshot": {"primaryGoal": "字符串"}})
    assert code == 200
    assert body["data"]["hasNumbers"] is False


# ---------------------------------------------------------------- 配置写入


def test_settings_write_takes_effect(client, api, profile_payload, catalog):
    key = "solver.target_probability"
    before = api(client, "post", "/api/v1/simulation/run", {"profile": profile_payload})[1]["data"]

    code, _ = api(client, "put", "/api/v1/catalog/settings", {"key": key, "value": "0.65"})
    assert code == 200
    changed = api(client, "post", "/api/v1/simulation/run", {"profile": profile_payload})[1]["data"]
    api(client, "put", "/api/v1/catalog/settings", {"key": key, "value": "0.5"})
    restored = api(client, "post", "/api/v1/simulation/run", {"profile": profile_payload})[1]["data"]

    assert changed["plan"]["targetProbability"] == 0.65
    assert restored["plan"]["targetProbability"] == before["plan"]["targetProbability"]


def test_parameter_write_takes_effect(client, api, profile_payload):
    before = api(client, "post", "/api/v1/simulation/run", {"profile": profile_payload})[1]["data"]
    code, _ = api(client, "put", "/api/v1/catalog/parameters",
                  {"key": "sudden_freq", "value_base": "3.0"})
    assert code == 200
    after = api(client, "post", "/api/v1/simulation/run", {"profile": profile_payload})[1]["data"]
    api(client, "put", "/api/v1/catalog/parameters", {"key": "sudden_freq", "value_base": "1.5"})
    restored = api(client, "post", "/api/v1/simulation/run", {"profile": profile_payload})[1]["data"]

    assert after["simulation"]["medianEndBalance"] < before["simulation"]["medianEndBalance"]
    assert restored["simulation"]["medianEndBalance"] == before["simulation"]["medianEndBalance"]


def test_ui_text_roundtrip(client, api):
    assert api(client, "put", "/api/v1/catalog/ui-texts",
               {"key": "test.key", "area": "app", "text": "临时文案"})[0] == 200
    rows = api(client, "get", "/api/v1/catalog/ui-texts")[1]["data"]["uiTexts"]
    assert "test.key" in {item["key"] for item in rows}
    assert api(client, "delete", "/api/v1/catalog/ui-texts/test.key")[0] == 200


def test_dictionary_item_roundtrip(client, api):
    payload = {"type_code": "grade", "code": "g9", "name": "测试年级", "sort_order": 99}
    assert api(client, "put", "/api/v1/catalog/dictionary-items", payload)[0] == 200
    codes = {item["code"] for item in
             api(client, "get", "/api/v1/catalog/dictionary-items/grade")[1]["data"]["items"]}
    assert "g9" in codes
    assert api(client, "delete", "/api/v1/catalog/dictionary-items/g9")[0] == 200


def test_change_log_written(client, api):
    api(client, "put", "/api/v1/catalog/ui-texts",
        {"key": "log.probe", "area": "app", "text": "留痕"})
    entries = api(client, "get", "/api/v1/catalog/change-log")[1]["data"]["entries"]
    assert any(item["record_key"] == "log.probe" for item in entries)
    api(client, "delete", "/api/v1/catalog/ui-texts/log.probe")


# ---------------------------------------------------------------- 业务实体增删改查


def test_archetype_crud(client, api, profile_payload):
    payload = copy.deepcopy(profile_payload)
    payload["archetype_id"] = "tmp_archetype"
    payload["name"] = "临时画像"
    api(client, "delete", "/api/v1/archetypes/tmp_archetype")   # 清理历史残留
    assert api(client, "post", "/api/v1/archetypes", payload)[0] == 201

    updated = api(client, "put", "/api/v1/archetypes/tmp_archetype", {"name": "临时画像二"})
    assert updated[1]["data"]["name"] == "临时画像二"

    assert api(client, "delete", "/api/v1/archetypes/tmp_archetype")[0] == 200
    ids = {item["archetype_id"] for item in
           api(client, "get", "/api/v1/archetypes")[1]["data"]["archetypes"]}
    assert "tmp_archetype" not in ids


def test_archetype_rejects_invalid_payload(client, api, profile_payload):
    payload = copy.deepcopy(profile_payload)
    payload["archetype_id"] = "tmp_bad"
    payload["living_cost"] = -1
    code, body = api(client, "post", "/api/v1/archetypes", payload)
    assert code == 400
    assert body["error"]["field"] == "living_cost"


def test_archetype_duplicate_rejected(client, api, profile_payload):
    code, _ = api(client, "post", "/api/v1/archetypes", profile_payload)
    assert code in (400, 409)


def test_term_crud(client, api):
    documents = api(client, "get", "/api/v1/corpus-documents")[1]["data"]["documents"]
    assert documents, "语料为空，术语无法建立来源引用"
    payload = {"term_code": "tmp_term", "name": "临时术语", "layer1": "一",
               "layer2": "二", "layer3_template": "三 {goal}", "aliases": ["临时别名"],
               "sources": [documents[0]["doc_code"]]}
    api(client, "delete", "/api/v1/terms/tmp_term")             # 清理历史残留
    assert api(client, "post", "/api/v1/terms", payload)[0] == 201
    assert api(client, "put", "/api/v1/terms/tmp_term", {"name": "临时术语二"})[1]["data"]["name"] == "临时术语二"
    assert api(client, "delete", "/api/v1/terms/tmp_term")[0] == 200
    assert api(client, "get", "/api/v1/terms/tmp_term")[0] == 404


def test_term_duplicate_rejected(client, api):
    payload = {"term_code": "max_drawdown", "name": "重复", "layer1": "一",
               "layer2": "二", "layer3_template": "三"}
    code, _ = api(client, "post", "/api/v1/terms", payload)
    assert code in (400, 409)


def test_corpus_document_crud(client, api):
    payload = {"doc_code": "tmp_doc", "doc_type": "regulation", "title": "临时语料"}
    api(client, "delete", "/api/v1/corpus-documents/tmp_doc")   # 清理历史残留
    assert api(client, "post", "/api/v1/corpus-documents", payload)[0] == 201
    updated = api(client, "put", "/api/v1/corpus-documents/tmp_doc", {"title": "临时语料二"})
    assert updated[1]["data"]["title"] == "临时语料二"
    assert api(client, "delete", "/api/v1/corpus-documents/tmp_doc")[0] == 200


# ---------------------------------------------------------------- 请求防护


@pytest.mark.parametrize("path", [
    "/../run.py", "/..%2frun.py", "/%2e%2e/run.py",
    "/../database/seeds/terms.json", "/../backend/config.py",
    "/assets/../../backend/config.py", "/assets/../../../Windows/win.ini",
])
def test_static_blocks_traversal(client, path):
    """解析后落在前端目录之外的一律拒绝。"""
    response = client.get(path)
    assert response.status_code in (400, 404, 405, 308)


def test_static_allows_internal_normalisation(client):
    """域内路径的常规归一化不应被误拦。"""
    assert client.get("/assets/../index.html").status_code == 200


def test_static_serves_index(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"<html" in response.data.lower()


def test_security_headers(client):
    response = client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_host_guard(client):
    response = client.get("/api/v1/health", headers={"Host": "evil.example.com"})
    assert response.status_code == 403


def test_oversized_body_rejected(client):
    payload = {"profile": {"name": "广" * 400000}}
    response = client.post("/api/v1/simulation/run", json=payload)
    assert response.status_code in (400, 413)
    assert response.status_code in (400, 413)


def test_non_json_body_rejected(client):
    response = client.post("/api/v1/simulation/run", data="not json",
                           content_type="text/plain")
    assert response.status_code in (400, 415)


def test_unknown_field_dropped(client, api, profile_payload):
    payload = copy.deepcopy(profile_payload)
    payload["malicious"] = "drop table archetypes"
    code, body = api(client, "post", "/api/v1/simulation/run", {"profile": payload})
    assert code == 200
    assert body["ok"] is True

def test_builtin_archetype_not_deletable(client, api):
    code, body = api(client, "delete", "/api/v1/archetypes/intern_junior")
    assert code == 400
    assert body["error"]["code"] == "C-02-03"
