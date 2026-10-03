"""智能体能力。

定义（名称、目标、提示词、输出结构、工具绑定、生成方式）全部存放在数据库，
代码只提供三样东西：工具处理器、本地渲染器、以及把两者串起来的运行时。
"""

from __future__ import annotations

from . import registry, runtime
from .protocol import AgentContext, AgentRequest, AgentResult, AgentStep

__all__ = ["AgentContext", "AgentRequest", "AgentResult", "AgentStep", "registry", "runtime"]
