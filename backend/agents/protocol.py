"""智能体的输入输出协议。

一次智能体调用由三段构成：按绑定顺序执行前置工具、生成最终文本、执行后置校验。
本模块把请求、步骤轨迹与结果三样东西固定下来，使调用方与具体实现解耦。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------- 常量
# 步骤状态与字典表 step_status 的取值保持一致
STEP_OK = "ok"
STEP_SKIPPED = "skipped"
STEP_FAILED = "failed"
STEP_REPLACED = "replaced"

# 步骤所处的阶段
STAGE_TOOL = "tool"
STAGE_GENERATE = "generate"
STAGE_GUARD = "guard"

# 生成方式。rule 为本地确定性生成，openai_compat 为可选的 OpenAI 兼容接口
PROVIDER_RULE = "rule"
PROVIDER_MODEL = "openai_compat"

# 工具类别。guard 类工具在生成之后执行，其余在生成之前执行
TOOL_KIND_GUARD = "guard"


@dataclass
class ToolOutcome:
    """一个工具的执行结果。detail 为面向使用者的中文说明。"""

    ok: bool
    detail: str
    status: str = STEP_OK
    data: dict = field(default_factory=dict)


@dataclass
class AgentContext:
    """贯穿一次调用的上下文。工具把结果写入 shared，生成器从 shared 读取。"""

    query: str = ""
    term: dict | None = None
    snapshot: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    messages: dict = field(default_factory=dict)
    shared: dict = field(default_factory=dict)

    def message(self, code: str, fallback: str = "") -> str:
        item = self.messages.get(code)
        if not item:
            return fallback
        return item.get("body") or fallback

    def message_title(self, code: str, fallback: str = "") -> str:
        item = self.messages.get(code)
        if not item or not item.get("title"):
            return fallback
        return item["title"]


@dataclass
class AgentStep:
    """步骤轨迹中的一条记录。detail 不得包含使用者填写的原始内容。"""

    index: int
    stage: str
    ref: str
    title: str
    status: str
    detail: str
    duration_ms: int

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "stage": self.stage,
            "ref": self.ref,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "durationMs": self.duration_ms,
        }


@dataclass
class AgentRequest:
    """调用输入。术语类智能体使用 query，决策类智能体使用 snapshot。"""

    agent_code: str
    query: str = ""
    snapshot: dict | None = None

    def normalized_snapshot(self) -> dict:
        return self.snapshot if isinstance(self.snapshot, dict) else {}


@dataclass
class AgentResult:
    """调用输出。provider 为实际使用的生成方式，与请求的偏好可能不同。"""

    agent: dict
    provider: str
    degraded: bool
    steps: list[AgentStep]
    output: dict
    warnings: list[str] = field(default_factory=list)
    elapsed_ms: int = 0

    def to_dict(self, include_steps: bool = True) -> dict:
        payload: dict[str, Any] = {
            "agent": self.agent,
            "provider": self.provider,
            "degraded": self.degraded,
            "output": self.output,
            "warnings": self.warnings,
            "elapsedMs": self.elapsed_ms,
        }
        if include_steps:
            payload["steps"] = [step.to_dict() for step in self.steps]
        else:
            payload["steps"] = []
        return payload
