class AgentFlowError(Exception):
    """Base error carrying an error code for API responses."""

    code = "AGENTFLOW_ERROR"

    def __init__(self, message: str, *, code: str | None = None, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.detail = detail or {}


class FlowValidationError(AgentFlowError):
    code = "FLOW_INVALID"


class NodeExecutionError(AgentFlowError):
    code = "NODE_FAILED"

    def __init__(self, node_id: str, message: str, *, detail: dict | None = None):
        super().__init__(message, detail=detail)
        self.node_id = node_id


class ModelNotConfiguredError(AgentFlowError):
    code = "MODEL_NOT_CONFIGURED"


class SkillNotFoundError(AgentFlowError):
    code = "SKILL_NOT_FOUND"
