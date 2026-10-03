"""智能体运行时：按绑定顺序执行工具，生成文本，再做合规校验。

编排过程固定为三段，每一段都会留下一条可追溯的步骤记录：

    前置工具  →  生成  →  后置校验

必需工具失败、或必需校验不通过时，调用整体失败并给出中文原因，
而不是把半成品交给调用方。步骤记录里只保留工具名与结果摘要，
不写入使用者填写的原始内容。
"""

from __future__ import annotations

from time import perf_counter

from ..common.errors import AppError
from . import providers
from .protocol import (
    PROVIDER_MODEL,
    STAGE_GENERATE,
    STAGE_GUARD,
    STAGE_TOOL,
    STEP_FAILED,
    STEP_OK,
    TOOL_KIND_GUARD,
    AgentContext,
    AgentResult,
    AgentStep,
)
from .providers import ProviderError
from .tools import TOOL_HANDLERS

# 生成阶段在轨迹里的名称
_GENERATE_TITLE = "生成文本"

# 连通性检查用的替身智能体。任务与提示都压到最短：这一步只验证链路通不通，
# 验证不了长文本的质量，也没必要为此多花词元。
_PROBE_AGENT = {
    "code": "__probe__",
    "name": "连通性检查",
    "objective": "只回复一个字：好",
    "system_prompt": "你只回复一个字：好，不要输出任何其他内容。",
    "provider": "inherit",
    "output_schema": None,
}


def run(agent: dict, tools: list[dict], ctx: AgentContext, settings: dict) -> AgentResult:
    """执行一次智能体调用。agent 与 tools 由注册表提供，ctx 由应用层准备。"""
    started = perf_counter()
    ctx.settings = settings or {}
    steps: list[AgentStep] = []
    warnings: list[str] = []
    index = 0

    # ---------------------------------------------------------- 前置工具
    for tool in [item for item in tools if item.get("kind") != TOOL_KIND_GUARD]:
        index += 1
        step = _run_tool(tool, ctx, index, STAGE_TOOL)
        steps.append(step)
        if step.status == STEP_FAILED:
            if tool.get("required"):
                raise AppError("E-05-02", f"步骤「{tool['name']}」未能完成：{step.detail}",
                               http_status=500)
            warnings.append(f"{tool['name']}未完成：{step.detail}")

    # ---------------------------------------------------------- 生成
    provider, reason = providers.choose_provider(agent, settings)
    index += 1
    generate_started = perf_counter()
    try:
        outcome = providers.generate(agent, ctx, settings, provider, reason)
    except ProviderError as exc:
        raise AppError("E-05-03", f"生成阶段失败：{exc}", http_status=500) from exc
    ctx.shared["output"] = outcome.output
    steps.append(AgentStep(
        index=index, stage=STAGE_GENERATE, ref=outcome.provider, title=_GENERATE_TITLE,
        status=STEP_OK, detail=outcome.detail,
        duration_ms=int((perf_counter() - generate_started) * 1000)))
    if outcome.warning:
        warnings.append(f"已降级：{outcome.warning}")

    # ---------------------------------------------------------- 后置校验
    for tool in [item for item in tools if item.get("kind") == TOOL_KIND_GUARD]:
        index += 1
        step = _run_tool(tool, ctx, index, STAGE_GUARD)
        steps.append(step)
        if step.status == STEP_FAILED:
            if tool.get("required"):
                raise AppError("E-05-04", f"输出未通过「{tool['name']}」：{step.detail}",
                               http_status=500)
            warnings.append(f"{tool['name']}未通过：{step.detail}")

    output = ctx.shared.get("output")
    if not isinstance(output, dict):
        raise AppError("E-05-03", "生成阶段没有产出可用的结果", http_status=500)

    return AgentResult(
        agent=_summary(agent),
        provider=outcome.provider,
        degraded=outcome.degraded,
        steps=steps,
        output=output,
        warnings=warnings,
        elapsed_ms=int((perf_counter() - started) * 1000),
    )


def _run_tool(tool: dict, ctx: AgentContext, index: int, stage: str) -> AgentStep:
    handler = TOOL_HANDLERS.get(tool.get("handler", ""))
    started = perf_counter()
    if handler is None:
        return AgentStep(index=index, stage=stage, ref=tool["code"], title=tool["name"],
                         status=STEP_FAILED, detail="该工具的处理器尚未实现", duration_ms=0)
    try:
        outcome = handler(ctx)
    except Exception as exc:  # noqa: BLE001  工具内部不应抛出，这里兜底以保证轨迹完整
        elapsed = int((perf_counter() - started) * 1000)
        return AgentStep(index=index, stage=stage, ref=tool["code"], title=tool["name"],
                         status=STEP_FAILED, detail=f"执行时出现异常：{type(exc).__name__}",
                         duration_ms=elapsed)
    return AgentStep(index=index, stage=stage, ref=tool["code"], title=tool["name"],
                     status=outcome.status, detail=outcome.detail,
                     duration_ms=int((perf_counter() - started) * 1000))


def probe(catalog) -> dict:
    """用一段最小请求验证服务端到模型接口的链路是否通的。

    走的是真实请求路径：路径选择、地址校验、鉴权头、超时都与生成阶段同一套逻辑，
    因此这里返回「通」意味着解释功能真的能调用出去。返回体不回吐模型输出——
    这一步只做连通性诊断，正式输出仍要由调用链路产出并过合规校验。
    """
    settings = catalog.settings
    provider, reason = providers.choose_provider(_PROBE_AGENT, settings)
    if provider != PROVIDER_MODEL:
        return {"connected": False, "provider": provider,
                "reason": reason or "当前配置走本地规则路径，不会发起网络请求"}

    ctx = AgentContext(settings=settings, messages=catalog.messages)
    started = perf_counter()
    try:
        outcome = providers.generate_by_model(_PROBE_AGENT, ctx, settings)
    except ProviderError as exc:
        return {"connected": False, "provider": PROVIDER_MODEL, "reason": str(exc),
                "elapsedMs": int((perf_counter() - started) * 1000)}
    return {"connected": not outcome.degraded, "provider": outcome.provider,
            "reason": "" if not outcome.degraded else outcome.detail,
            "elapsedMs": int((perf_counter() - started) * 1000)}


def _summary(agent: dict) -> dict:
    """对外暴露的智能体摘要。提示词属于内部配置，不随结果返回。"""
    return {
        "code": agent.get("code"),
        "name": agent.get("name"),
        "category": agent.get("category"),
        "description": agent.get("description"),
    }
