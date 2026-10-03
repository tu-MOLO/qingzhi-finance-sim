"""智能体的生成器。

生成阶段有两条路径，对外产出同一套结构：

  · rule —— 本地确定性渲染，用模板与规则把工具取到的素材拼装成文本。
    不产生任何网络请求，因此离线环境下产品的完整性不受影响。
  · openai_compat —— 调用 OpenAI 兼容的对话补全接口。服务地址、模型名与
    超时都来自数据库配置，凭据只从环境变量读取。任何环节失败都会回落到 rule。

路径的选择遵循两个闸门：全局是否允许联网、以及该智能体是否被指定为本地规则。
两个闸门都放行时才会真正发出网络请求。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

from ..common.errors import ConfigurationError
from .protocol import PROVIDER_MODEL, PROVIDER_RULE, AgentContext
from .tools import format_amount


class ProviderError(RuntimeError):
    """生成阶段的失败。携带面向使用者的中文说明，由运行期决定是否降级。"""


@dataclass
class GenerationOutcome:
    output: dict
    provider: str
    degraded: bool
    detail: str
    warning: str | None = None
    extra_steps: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- 路径选择


def choose_provider(agent: dict, settings: dict) -> tuple[str, str | None]:
    """决定本次调用使用哪条生成路径。

    返回生成方式与放弃外部模型的原因。原因为空表示可以走外部模型。
    """
    if not _as_bool(settings.get("agent.allow_network")):
        return PROVIDER_RULE, "配置未允许联网"
    preference = str(agent.get("provider") or "inherit")
    if preference == PROVIDER_RULE:
        return PROVIDER_RULE, "该智能体已指定为本地规则"
    provider = str(settings.get("agent.provider") or PROVIDER_RULE)
    if provider != PROVIDER_MODEL:
        return PROVIDER_RULE, "全局生成方式为本地规则"
    if not str(settings.get("agent.base_url") or "").strip():
        return PROVIDER_RULE, "尚未配置模型服务地址"
    if not str(settings.get("agent.model") or "").strip():
        return PROVIDER_RULE, "尚未配置模型名称"
    return PROVIDER_MODEL, None


# ---------------------------------------------------------------- 生成入口


def generate(agent: dict, ctx: AgentContext, settings: dict,
             provider: str, reason: str | None) -> GenerationOutcome:
    if provider == PROVIDER_MODEL:
        try:
            return generate_by_model(agent, ctx, settings)
        except ProviderError as exc:
            output = render(agent, ctx)
            return GenerationOutcome(
                output=output, provider=PROVIDER_RULE, degraded=True,
                detail=f"外部模型调用失败，已回落到本地规则：{exc}",
                warning=str(exc))
    output = render(agent, ctx)
    detail = "由本地规则生成" if not reason else f"由本地规则生成（{reason}）"
    return GenerationOutcome(output=output, provider=PROVIDER_RULE, degraded=False, detail=detail)


# ---------------------------------------------------------------- 本地规则渲染


def render(agent: dict, ctx: AgentContext) -> dict:
    renderer = RENDERERS.get(str(agent.get("code")))
    if renderer is None:
        raise ProviderError(f"智能体 {agent.get('code')} 尚未注册本地渲染器")
    return renderer(ctx)


def _layer3_from_template(ctx: AgentContext, term: dict, goal: dict, numeric: dict) -> str:
    """第三层按该术语自己的模板渲染，而不是所有术语套同一句回撤文案。

    模板中的占位符由 numeric 工具的输出填充；缺失的占位符以空串兜底，
    模板本身缺字段时回落到通用句，避免渲染中断。
    """
    template = str(term.get("layer3_template") or "").strip()
    if not template:
        return ""
    values = {
        "goal": goal.get("name", ""),
        "loss": numeric.get("lossText", ""),
        "delay_clause": numeric.get("delayClause") or "",
        "cap": numeric.get("capText", ""),
        "amount": numeric.get("amountText", ""),
        "gain": numeric.get("gainText", ""),
        "median": numeric.get("medianText", ""),
        "due": numeric.get("dueText", ""),
    }
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError):
        return ""


def _render_term_explain(ctx: AgentContext) -> dict:
    """术语三层解释。第三层落到使用者的目标上，无目标时改用固定合规文案。

    有多个目标时第三层仍以首要目标为主体展开，随后把同一幅度落在其余目标上的结果
    补一句，避免「只算第一个目标」的错觉。
    """
    term = ctx.term or {}
    goal = ctx.shared.get("goal")
    numeric = ctx.shared.get("numeric") or {}
    numerics = [item for item in (ctx.shared.get("numerics") or [])
                if goal and item.get("goalId") != goal.get("goalId")]

    if not goal:
        layer3 = ctx.message("compliance.no_goal", "")
        has_numbers = False
    elif not numeric:
        # 有目标但推演没给出数字：只讲目标本身，不编造任何数值
        layer3 = (f"您已设置「{goal['name']}」，但本次尚未取得推演结果，"
                  "因此这里不给出具体数字；先运行一次推演，即可得到落在您自己目标上的换算。")
        has_numbers = False
    else:
        layer3 = _layer3_from_template(ctx, term, goal, numeric)
        if not layer3:
            layer3 = (f"按您设置的「{goal['name']}」计算，目标金额为 {numeric.get('amountText', '')}，"
                      f"若出现 {numeric.get('lossRatioText', '')} 的回撤，"
                      f"相当于减少约 {numeric.get('lossText', '')}，"
                      f"{numeric.get('delayClause') or ''}。")
        if numerics:
            # 只有确实用到回撤金额的术语才讲回撤，概率类术语改讲目标金额，避免文不对题
            used_loss = "{loss}" in str(term.get("layer3_template") or "")
            key = "lossText" if used_loss else "amountText"
            lead = "同样的幅度落在其余目标上，" if used_loss else "您设置的目标还包括"
            others = "、".join(f"「{item['name']}」{item[key]}" for item in numerics)
            layer3 += f"{lead}{others}。"
        has_numbers = True

    goals = ctx.shared.get("goals") or []
    return {
        "layer1": term.get("layer1", ""),
        "layer2": term.get("layer2", ""),
        "layer3": layer3,
        "hasNumbers": has_numbers,
        "linkedGoalId": goal["goalId"] if goal else None,
        "linkedGoalName": goal["name"] if goal else None,
        "linkedGoalIds": [item["goalId"] for item in goals],
        "sources": ctx.shared.get("corpus") or [],
    }


def _goal_clause(item: dict, lead: str = "") -> str:
    """单个目标的处境一句话：金额、到期月、概率、延后与缺口。"""
    clause = (f"{lead}「{item['name']}」目标金额 {item['amountText']}，"
              f"第 {item['dueMonth'] or '—'} 个月到期，"
              f"按期达成概率 {item['probabilityText']}，{item['delayClause']}")
    if item["gapAmount"] > 0:
        clause += f"，目前还差 {item['gapText']}"
    else:
        clause += "，当前资金已能覆盖"
    if (item.get("probability") or 0) < 0.5:
        clause += "；概率不足五成，这个目标在当前收入结构下压力较大，先动它的到期时间或金额更划算"
    return clause + "。"


def _render_plan_insight(ctx: AgentContext) -> dict:
    """结论解读。总述讲处境，要点逐个目标讲做法与代价，末句点出最脆弱的环节。"""
    goal = ctx.shared.get("goal")
    goals = ctx.shared.get("goals") or ([goal] if goal else [])
    capacity = ctx.shared.get("capacity")
    scenarios = ctx.shared.get("scenarios")
    allocation = ctx.shared.get("allocation")

    if not goal:
        # 无推演摘要时不产生任何数字
        return {
            "headline": ctx.message("status.agent_prompt_missing", ""),
            "points": [],
            "riskNote": "",
            "hasNumbers": False,
            "linkedGoalId": None,
            "linkedGoalName": None,
            "sources": [],
        }

    points: list[str] = []
    cap_clause = ""
    if capacity:
        cap_clause = (f"当前风险容量等级为{capacity['level']}，"
                      f"权益类资产的建议上限为 {capacity['finalCapText']}。")
    headline = (f"在您当前的收入结构下，「{goal['name']}」的目标金额为 {goal['amountText']}，"
                f"按期达成概率为 {goal['probabilityText']}，{goal['delayClause']}。")
    # 共几个目标紧接在首要目标之后交代，读的人先知道后面还有几条，再听容量等级
    if len(goals) > 1:
        headline += f"本次共纳入 {len(goals)} 个目标，逐个说明如下。"
    headline += cap_clause

    # 每个目标各占一条，主目标排在最前并标明身份，其余按顺序跟上
    for index, item in enumerate(goals):
        points.append(_goal_clause(item, "主目标" if index == 0 else ""))

    # 资金按优先级依次填，缺口同时存在时要说清谁先谁后
    pressured = [item for item in goals if item["gapAmount"] > 0]
    if len(goals) > 1 and pressured:
        names = "、".join(f"「{item['name']}」" for item in pressured)
        points.append(f"{names}目前仍有缺口，结余按优先级依次流向各目标，"
                      "排在后面的目标要让位于排在前面的目标。")

    if scenarios:
        # 三档情景逐个目标列齐，包括主目标：只给首要目标一档区间，其余目标的波动无从比较
        by_goal = scenarios.get("byGoal") or {}
        lines = []
        for item in goals:
            bucket = by_goal.get(item["goalId"])
            if not bucket:
                continue
            lines.append(f"「{item['name']}」悲观 {bucket.get('pessimisticText') or '—'}"
                         f"、基准 {bucket.get('baseText') or '—'}"
                         f"、乐观 {bucket.get('optimisticText') or '—'}")
        if lines:
            points.append("三档情景下各目标的达成概率：" + "；".join(lines) + "。")
        if scenarios.get("spreadText"):
            points.append(f"主目标在悲观与乐观两档之间相差 {scenarios['spreadText']}，"
                          "说明收入波动本身是影响结果的主要来源。")

    if allocation:
        if allocation["safeFilled"]:
            points.append(f"安全底座目标为 {allocation['emergencyTargetText']}，目前已经填满，"
                          "后续结余可以完整流向其余账户。")
        else:
            points.append(f"安全底座目标为 {allocation['emergencyTargetText']}，目前尚未填满。"
                          "在它填满之前，其余账户能分到的资金都会被压缩。")

    # 末句逐个目标交代达成时刻。推演期内没达成的目标不给月数，改说攒不够，避免出现「第 — 个月」
    tails = []
    for item in goals:
        tails.append(f"「{item['name']}」的达成时刻为第 {item['medianMonth']} 个月"
                     if item.get("medianMonth")
                     else f"「{item['name']}」在推演期内多数路径都攒不够")
    reached = any(item.get("medianMonth") for item in goals)
    points.append("若维持现有开销，" + "，".join(tails) +
                  ("；若提前压缩非必要开支，可以把达成时刻前移，代价是当期的可支配金额减少。"
                   if reached else
                   "；若提前压缩非必要开支或下调目标金额，可以让它们重新回到推演期内。"))

    risk_note = ""
    if capacity and capacity.get("dipMonths"):
        months = "、".join(f"第 {item} 个月" for item in capacity["dipMonths"][:4])
        risk_note = f"推演期内，{months}出现了容量下探，这几个时点需要预留更大余量。"
    elif capacity:
        risk_note = "推演期内容量没有出现明显下探，主要风险来自收入本身的中断。"

    return {
        "headline": headline,
        "points": points,
        "riskNote": risk_note,
        "hasNumbers": True,
        "linkedGoalId": goal["goalId"],
        "linkedGoalName": goal["name"],
        "sources": [],
    }


RENDERERS: dict[str, Callable[[AgentContext], dict]] = {
    "term_explain": _render_term_explain,
    "plan_insight": _render_plan_insight,
}


# ---------------------------------------------------------------- 外部模型


def generate_by_model(agent: dict, ctx: AgentContext, settings: dict) -> GenerationOutcome:
    base_url = str(_setting(settings, "agent.base_url")).strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ProviderError("模型服务地址不是有效的 http 或 https 地址")

    timeout = _to_float(settings, "agent.timeout_seconds")
    attempts = max(1, int(_to_float(settings, "agent.max_attempts")))
    temperature = _to_float(settings, "agent.temperature")
    max_tokens = int(_to_float(settings, "agent.max_tokens"))

    payload = {
        "model": str(_setting(settings, "agent.model")),
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": str(agent.get("system_prompt") or "")},
            {"role": "user", "content": _compose_user_message(agent, ctx)},
        ],
    }
    headers = {"Content-Type": "application/json"}
    key_env = str(settings.get("agent.api_key_env") or "").strip()
    if key_env:
        import os
        token = os.environ.get(key_env, "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

    endpoint = base_url + "/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error = "未知错误"
    for _ in range(attempts):
        # 端点地址在上一步已校验过协议，此处只可能是 http 或 https
        request = urllib.request.Request(  # noqa: S310
            endpoint, data=body, headers=headers, method="POST")
        try:
            # 地址已在上一步校验过协议，这里只允许 http 与 https
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last_error = f"服务返回状态 {exc.code}"
            continue
        except urllib.error.URLError as exc:
            last_error = f"无法连接模型服务（{exc.reason}）"
            continue
        except TimeoutError:
            last_error = "调用超时"
            continue
        except OSError as exc:
            last_error = f"网络异常（{type(exc).__name__}）"
            continue

        text = _extract_text(raw)
        if not text:
            last_error = "服务返回内容无法解析"
            continue
        output = _parse_output(str(agent.get("code")), text, ctx)
        if output is None:
            last_error = "服务返回内容不符合约定的结构"
            continue
        return GenerationOutcome(output=output, provider=PROVIDER_MODEL, degraded=False,
                                 detail="由外部模型生成")
    raise ProviderError(last_error)


def _compose_user_message(agent: dict, ctx: AgentContext) -> str:
    """把工具取到的素材组织成一段提示。"""
    blocks = [f"任务：{agent.get('objective') or ''}"]
    if ctx.query:
        blocks.append(f"需要解释的说法：{ctx.query}")
    term = ctx.term or {}
    if term:
        blocks.append(f"该说法的既有释义：{term.get('layer1', '')}")
    corpus = ctx.shared.get("corpus") or []
    if corpus:
        lines = [f"【{item['docTypeName']}】{item['title']}\n{item['excerpt']}" for item in corpus]
        blocks.append("可引用的语料：\n" + "\n\n".join(lines))
    else:
        blocks.append("可引用的语料：无")
    goals = ctx.shared.get("goals") or []
    if goals:
        lines = []
        for index, item in enumerate(goals):
            lines.append(
                f"目标 {index + 1}"
                f"（{'主目标' if index == 0 else '次目标'}）：{item['name']}\n"
                f"  目标金额：{item['amountText']}\n"
                f"  到期月份：第 {item['dueMonth']} 个月\n"
                f"  按期达成概率：{item['probabilityText']}\n"
                f"  中位达成时刻：{item['medianMonth'] or '推演期内未达成'}\n"
                f"  达成情况：{item['delayClause']}\n"
                f"  资金缺口：{item['gapText']}")
        blocks.append("使用者情况：\n" + "\n".join(lines))
    else:
        blocks.append("使用者情况：未设置目标，不得输出任何数字。")
    numeric = ctx.shared.get("numeric")
    if numeric:
        blocks.append(f"回撤示例幅度：{numeric['lossRatioText']}，对应金额 {numeric['lossText']}")
    capacity = ctx.shared.get("capacity")
    if capacity:
        blocks.append(f"风险容量等级：{capacity['level']}，权益类建议上限 {capacity['finalCapText']}")
    scenarios = ctx.shared.get("scenarios")
    if scenarios:
        blocks.append(f"悲观情景达成概率：{scenarios.get('pessimisticText') or '—'}；"
                      f"乐观情景：{scenarios.get('optimisticText') or '—'}")
    allocation = ctx.shared.get("allocation")
    if allocation:
        blocks.append(f"安全底座目标：{allocation['emergencyTargetText']}，"
                      f"{'已填满' if allocation['safeFilled'] else '尚未填满'}")
    schema = agent.get("output_schema")
    if schema:
        blocks.append(f"输出结构：{schema}")
    return "\n\n".join(block for block in blocks if block)


def _extract_text(raw: str) -> str | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    return content if isinstance(content, str) and content.strip() else None


def _parse_output(agent_code: str, text: str, ctx: AgentContext) -> dict | None:
    """把模型返回的自然语言拆成结构化输出。结构不符时返回空，由上层降级。"""
    plain = text.strip()
    if not plain:
        return None

    if agent_code == "term_explain":
        paragraphs = [item.strip() for item in plain.split("\n\n") if item.strip()]
        if len(paragraphs) < 3:
            paragraphs = [item.strip() for item in plain.split("\n") if item.strip()]
        if len(paragraphs) < 3:
            return None
        goal = ctx.shared.get("goal")
        return {
            "layer1": paragraphs[0],
            "layer2": paragraphs[1],
            "layer3": "\n".join(paragraphs[2:]),
            "hasNumbers": any(ch.isdigit() for ch in paragraphs[2]),
            "linkedGoalId": goal["goalId"] if goal else None,
            "linkedGoalName": goal["name"] if goal else None,
            "sources": ctx.shared.get("corpus") or [],
        }

    if agent_code == "plan_insight":
        lines = [item.strip() for item in plain.splitlines() if item.strip()]
        headline = lines[0] if lines else ""
        points = [item.lstrip("-·• ").strip() for item in lines[1:] if item.startswith(("-", "·", "•"))]
        risk_note = ""
        if not points:
            points = list(lines[1:])
        if points and ("脆弱" in points[-1] or "下探" in points[-1]):
            risk_note = points.pop()
        goal = ctx.shared.get("goal")
        return {
            "headline": headline,
            "points": points,
            "riskNote": risk_note,
            "hasNumbers": any(ch.isdigit() for ch in plain),
            "linkedGoalId": goal["goalId"] if goal else None,
            "linkedGoalName": goal["name"] if goal else None,
            "sources": [],
        }

    return {"text": plain, "hasNumbers": any(ch.isdigit() for ch in plain)}


# ---------------------------------------------------------------- 工具函数


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return False


def _setting(settings: dict, key: str):
    """读取必需的配置项。

    配置缺失时一律报错，不回落代码中的默认值——这是本项目对配置的一贯纪律，
    也与「业务数据的唯一来源是数据库」保持一致。
    """
    value = settings.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ConfigurationError(f"缺少必要配置项：{key}", field=key)
    return value


def _to_float(settings: dict, key: str) -> float:
    try:
        result = float(_setting(settings, key))
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"配置项 {key} 不是有效的数值", field=key) from exc
    if result != result or result in (float("inf"), float("-inf")):
        raise ConfigurationError(f"配置项 {key} 的取值无效", field=key)
    return result


def describe_amount(value: float | None) -> str:
    """供其他模块复用的金额表述，避免各处重复实现。"""
    return format_amount(value)
