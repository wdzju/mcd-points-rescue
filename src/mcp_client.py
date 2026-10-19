"""Minimal MCP client for Streamable HTTP transport (JSON-RPC 2.0).

Implements just enough of the Model Context Protocol to talk to
https://mcp.mcd.cn without pulling in the official SDK, so the project
stays dependency-free on the standard library.

Protocol reference: https://modelcontextprotocol.io/specification/2025-06-18
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

PROTOCOL_VERSION = "2025-06-18"
DEFAULT_ENDPOINT = "https://mcp.mcd.cn"
DEFAULT_TIMEOUT = 30.0


class McpError(RuntimeError):
    """Base error for MCP transport / protocol failures."""


class McpAuthError(McpError):
    """401 - token missing, invalid or expired."""


class McpRateLimitError(McpError):
    """429 - exceeded the per-token request budget (600 req/min)."""


class McpToolError(McpError):
    """The tool itself reported a failure (isError=true)."""


@dataclass
class ToolSchema:
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CallResult:
    """Normalised result of a tools/call request."""

    tool: str
    data: Any
    is_error: bool = False

    @property
    def ok(self) -> bool:
        return not self.is_error


class McpClient:
    """Streamable HTTP client with session handling and SSE/JSON decoding."""

    def __init__(
        self,
        token: Optional[str] = None,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = 3,
    ) -> None:
        # Resolution order: explicit argument → environment variable → the
        # token saved by `--setup`. Nothing else, and never a repo file.
        resolved = token or os.environ.get("MCD_MCP_TOKEN", "")
        if not resolved:
            try:
                from .credentials import load_token

                resolved = load_token() or ""
            except Exception:  # noqa: BLE001
                resolved = ""
        self.token = resolved
        if not self.token:
            raise McpAuthError(
                "缺少 MCP Token。运行 `python points_rescue.py --setup` 配置，"
                "或设置环境变量 MCD_MCP_TOKEN。申请地址：https://open.mcd.cn/mcp"
            )
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session_id: Optional[str] = None
        self._request_id = 0
        self._tools_cache: Optional[List[ToolSchema]] = None

    # ------------------------------------------------------------------
    # transport
    # ------------------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _post_raw(self, payload: Dict[str, Any]) -> Any:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint, data=body, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                new_session = resp.headers.get("Mcp-Session-Id")
                if new_session:
                    self.session_id = new_session
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            if exc.code == 401:
                raise McpAuthError(f"401 unauthorized: {detail}") from exc
            if exc.code == 429:
                raise McpRateLimitError(f"429 rate limited: {detail}") from exc
            raise McpError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise McpError(f"network failure: {exc.reason}") from exc
        return self._decode(raw)

    @staticmethod
    def _decode(raw: str) -> Any:
        """Accept either `application/json` or SSE `data:` frames."""
        stripped = raw.strip()
        if not stripped:
            return None
        if stripped.startswith("{"):
            return json.loads(stripped)
        # SSE framing: "event: message\ndata: {...}\n\n"
        for line in stripped.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    return json.loads(payload)
        raise McpError(f"unrecognised response payload: {raw[:300]}")

    def _request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        delay = 1.0
        for attempt in range(self.max_retries):
            last = attempt == self.max_retries - 1
            try:
                result = self._post_raw(payload)
            except McpAuthError:
                # A bad token will never become good by retrying.
                raise
            except McpRateLimitError:
                if last:
                    raise
                time.sleep(delay)
                delay *= 2
                continue
            except (urllib.error.URLError, TimeoutError, OSError):
                # Transient network faults are worth one or two more tries —
                # failing instantly on a dropped connection is a poor
                # experience for a tool that runs on home wifi.
                if last:
                    raise
                time.sleep(delay)
                delay *= 2
                continue
            if isinstance(result, dict) and "error" in result:
                err = result["error"]
                raise McpError(f"{method} failed: {err.get('message', err)}")
            return result.get("result") if isinstance(result, dict) else result
        raise McpError(f"{method} 重试 {self.max_retries} 次后仍失败")

    def _notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint, data=body, headers=self._headers(), method="POST"
        )
        try:
            urllib.request.urlopen(req, timeout=self.timeout).read()
        except urllib.error.HTTPError as exc:
            if exc.code in (202, 204):
                return
            # some gateways answer notifications with 4xx; not fatal
            return
        except urllib.error.URLError:
            return

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def initialize(self) -> Dict[str, Any]:
        result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "mcd-points-rescue", "version": "1.0.0"},
            },
        )
        self._notify("notifications/initialized")
        return result or {}

    def list_tools(self, refresh: bool = False) -> List[ToolSchema]:
        if self._tools_cache is not None and not refresh:
            return self._tools_cache
        result = self._request("tools/list") or {}
        tools: List[ToolSchema] = []
        for item in result.get("tools", []):
            tools.append(
                ToolSchema(
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                    input_schema=item.get("inputSchema", {}) or {},
                )
            )
        self._tools_cache = tools
        return tools

    # ------------------------------------------------------------------
    # tool invocation
    # ------------------------------------------------------------------
    def call(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> CallResult:
        result = self._request(
            "tools/call", {"name": name, "arguments": arguments or {}}
        )
        return self._normalise(name, result or {})

    @staticmethod
    def _normalise(tool: str, result: Dict[str, Any]) -> CallResult:
        is_error = bool(result.get("isError", False))
        blocks = result.get("content", []) or []
        collected: List[Any] = []
        for block in blocks:
            btype = block.get("type")
            if btype == "text":
                text = block.get("text", "")
                collected.append(McpClient._maybe_json(text))
            elif btype in ("image", "audio", "blob"):
                collected.append({"_binary": btype})
            elif "json" in block:
                collected.append(block["json"])
        data: Any = collected[0] if len(collected) == 1 else collected
        return CallResult(tool=tool, data=data, is_error=is_error)

    @staticmethod
    def _maybe_json(text: str) -> Any:
        stripped = text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return text
        return text

    def call_json(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """Call a tool and raise if it errored or returned non-structured data."""
        result = self.call(name, arguments)
        if result.is_error:
            raise McpToolError(f"{name} returned an error: {result.data}")
        return result.data
