"""错误码体系。

三段式：`<层>-<类别>-<序号>`。
层：P 参数层、S 仿真层、D 决策层、E 解释层、V 呈现层、C 配置层。
类别：01 输入校验、02 数据缺失、03 计算异常、04 资源、05 外部依赖、06 无解或不可行。
"""

from __future__ import annotations


class AppError(Exception):
    """带错误码的业务异常。message 为面向使用者的中文文案。"""

    def __init__(self, code: str, message: str, field: str | None = None, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.http_status = http_status

    def to_dict(self) -> dict:
        payload = {"code": self.code, "message": self.message}
        if self.field:
            payload["field"] = self.field
        return payload


class ValidationError(AppError):
    """输入校验失败。"""

    def __init__(self, field: str, message: str, code: str = "P-01-01"):
        super().__init__(code, message, field=field, http_status=400)


class NotFoundError(AppError):
    """目标记录不存在。"""

    def __init__(self, code: str, message: str, field: str | None = None):
        super().__init__(code, message, field=field, http_status=404)


class ConflictError(AppError):
    """唯一约束冲突。"""

    def __init__(self, code: str, message: str, field: str | None = None):
        super().__init__(code, message, field=field, http_status=409)


class ConfigurationError(AppError):
    """配置数据缺失或不可用，需要先初始化数据库。"""

    def __init__(self, message: str, field: str | None = None):
        super().__init__("C-02-01", message, field=field, http_status=503)


class SimulationError(AppError):
    def __init__(self, code: str, message: str, http_status: int = 500):
        super().__init__(code, message, http_status=http_status)


class DecisionError(AppError):
    def __init__(self, code: str, message: str, http_status: int = 500):
        super().__init__(code, message, http_status=http_status)


class ExplainError(AppError):
    def __init__(self, code: str, message: str, http_status: int = 500):
        super().__init__(code, message, http_status=http_status)
