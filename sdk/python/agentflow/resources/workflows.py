from __future__ import annotations

import json
from typing import Any, Iterator, Optional

from ..errors import ApiError


class WorkflowResource:
    def __init__(self, client: AgentFlowClient) -> None:
        self._c = client

    def list(self, page: int = 1, size: int = 10, keyword: Optional[str] = None) -> Any:
        params: dict[str, Any] = {"page": page, "size": size}
        if keyword:
            params["keyword"] = keyword
        return self._c.request("GET", "/api/workflows", params=params)

    def get(self, workflow_id: int) -> Any:
        return self._c.request("GET", f"/api/workflows/{workflow_id}")

    def create(
        self,
        name: str,
        flow: dict[str, Any],
        *,
        description: str = "",
        engine_type: str = "langgraph",
        status: int = 1,
    ) -> Any:
        payload = {
            "name": name,
            "description": description,
            "engineType": engine_type,
            "status": status,
            "flow": flow,
        }
        return self._c.request("POST", "/api/workflows", json=payload)

    def update(self, workflow_id: int, **fields: Any) -> Any:
        return self._c.request("PUT", f"/api/workflows/{workflow_id}", json=fields)

    def delete(self, workflow_id: int) -> Any:
        return self._c.request("DELETE", f"/api/workflows/{workflow_id}")

    def run(self, workflow_id: int, input: Optional[dict[str, Any]] = None, **opts: Any) -> Any:
        """Synchronous execution: returns the aggregated RunResult."""
        payload: dict[str, Any] = {"input": input or {}}
        payload.update(opts)
        return self._c.request("POST", f"/api/workflows/{workflow_id}/run", json=payload)

    def execute_stream(
        self, workflow_id: int, input: Optional[dict[str, Any]] = None, **opts: Any
    ) -> Iterator[tuple[str, Any]]:
        """Streaming execution: yields (event_name, payload) as SSE events arrive."""
        payload: dict[str, Any] = {"input": input or {}}
        payload.update(opts)
        with self._c._client.stream(
            "POST", f"/api/workflows/{workflow_id}/execute", json=payload,
            headers={"Accept": "text/event-stream"},
        ) as resp:
            if resp.status_code >= 400:
                resp.read()
                raise ApiError(resp.status_code, resp.text)
            event: Optional[str] = None
            data: list[str] = []
            first_line = True
            for line in resp.iter_lines():
                if first_line:
                    line = line.removeprefix("\ufeff")
                    first_line = False
                if line == "":
                    if event is not None or data:
                        body = "\n".join(data)
                        yield event or "message", (json.loads(body) if body else None)
                    event = None
                    data = []
                elif not line.startswith(":"):
                    field, _, value = line.partition(":")
                    value = value.removeprefix(" ")
                    if field == "event":
                        event = value
                    elif field == "data":
                        data.append(value)
            # Compatibility with upstreams that omit the final blank separator.
            if event is not None or data:
                body = "\n".join(data)
                yield event or "message", (json.loads(body) if body else None)
