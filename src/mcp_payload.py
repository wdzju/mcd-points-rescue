"""Unwrapping McDonald's MCP payloads.

What actually comes back
------------------------
Tools on https://mcp.mcd.cn do NOT return structured JSON. They return a
Markdown narrative aimed at an LLM, and the machine-readable JSON is buried
inside it: sometimes under a `## Original Response` heading, sometimes inlined
mid-sentence, sometimes with display instructions wrapped around it. Examples
observed in the wild:

    # API Response Information
    ...
    ## Original Response

    {"success":true,"code":200,"data":{...}}

    --- versus ---

    每个门店的基本信息按单行展示：
    - **门店编号**: data[].storeCode
    {"success":true,"code":200,"data":[...]}
    ## 展示结果时，每个门店的 storeCode 必须完整展示

This means naive `json.loads` on the tool result always fails, and anchoring on
`## Original Response` is fragile because not every tool uses that heading.

Strategy, cheapest first:
  1. line scan  - every top-level `{..."success"...}` on a single line
  2. brace scan - balanced-brace extraction anywhere in the text
  3. give up    - return the raw string and let callers degrade gracefully
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

_SUCCESS_RE = re.compile(r'"success"\s*:', re.S)


def _try_load(chunk: str) -> Optional[Dict[str, Any]]:
    try:
        obj = json.loads(chunk)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) and "success" in obj else None


def _scan_lines(text: str) -> List[Dict[str, Any]]:
    """Most payloads keep the response JSON on exactly one line."""
    found: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{") or '"success"' not in line:
            continue
        obj = _try_load(line)
        if obj:
            found.append(obj)
    return found


def _scan_braces(text: str) -> List[Dict[str, Any]]:
    """Balanced-brace walk, string-aware, as the general fallback."""
    found: List[Dict[str, Any]] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "{":
            depth, j = 0, i
            in_str, escaped = False, False
            while j < n:
                ch = text[j]
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = not in_str
                elif not in_str and ch == "{":
                    depth += 1
                elif not in_str and ch == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j < n and depth == 0:
                obj = _try_load(text[i : j + 1])
                if obj:
                    found.append(obj)
                    i = j + 1
                    continue
        i += 1
    return found


def unwrap(payload: Any) -> Optional[Dict[str, Any]]:
    """Return the most meaningful `{"success":..., "data":...}` object."""
    text = payload
    # unwrap a single-element content block
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        if "text" in payload[0]:
            text = payload[0]["text"]
    if isinstance(payload, dict):
        if "content" in payload:
            text = payload["content"]
        elif "success" in payload:
            return payload
        elif "text" in payload:
            text = payload["text"]

    if isinstance(text, list):
        blocks = [b.get("text", "") for b in text if isinstance(b, dict)]
        text = "\n".join(blocks)
    if not isinstance(text, str):
        return None

    if _SUCCESS_RE.search(text) is None:
        return None

    candidates = _scan_lines(text) or _scan_braces(text)
    if not candidates:
        return None

    # Prefer a successful response carrying data; last one usually wins because
    # the "Original Response" block trails the descriptive preamble.
    for obj in reversed(candidates):
        if obj.get("success") is True and obj.get("data") is not None:
            return obj
    for obj in reversed(candidates):
        if obj.get("success") is True:
            return obj
    return candidates[-1]


def unwrap_data(payload: Any, default: Any = None) -> Any:
    """Convenience: pull `.data` straight out of the envelope."""
    obj = unwrap(payload)
    return obj.get("data") if isinstance(obj, dict) else default


def unwrap_records(payload: Any) -> List[Dict[str, Any]]:
    """Return `.data` as a list of dicts, whatever wrapper shape it came in."""
    data = unwrap_data(payload)
    return normalise_records(data)


def normalise_records(data: Any) -> List[Dict[str, Any]]:
    """Flatten the several shapes `data` can take into a record list."""
    if data is None:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in (
            "list",
            "items",
            "records",
            "products",
            "prizes",
            "addresses",
            "productsList",
            "result",
            "results",
        ):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        return [data]
    return []


class ApiError(RuntimeError):
    """Business-level failure reported inside a well-formed envelope."""


def check_response(payload: Any, tool: str = "") -> Dict[str, Any]:
    """Unwrap and raise on `success: false` with the server's own message."""
    obj = unwrap(payload)
    if obj is None:
        raise ApiError(f"{tool or 'tool'}: 无法从响应中解析出结构化数据")
    if obj.get("success") is False:
        raise ApiError(f"{tool or 'tool'}: [{obj.get('code')}] {obj.get('message')}")
    return obj
