"""A local web front-end for configuring and running the analysis.

Why a local server instead of a hosted login page
-------------------------------------------------
The token is obtained through phone + SMS verification on open.mcd.cn. Putting
that form inside a third-party page is indistinguishable from phishing: the
user cannot tell who receives the code. So the SMS step stays on McDonald's own
origin, where the address bar can be verified.

Everything *after* that step happens here, on the user's machine:

    open.mcd.cn (SMS)  →  user pastes token  →  stored locally  →  analysis runs

Because the server binds to 127.0.0.1 only, no third party can reach it, and the
token never leaves the machine. This is the closest honest approximation of
"log in on the page" — the only step we refuse to own is the one that would make
us a custodian of someone else's identity.

Implementation notes:
- stdlib only (`http.server`), preserving the project's zero-dependency rule
- `ThreadingHTTPServer` so a long analysis does not block the page
- every handler is wrapped so a failure returns JSON rather than a stack trace
"""

from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

DEFAULT_PORT = 8723
# Hard cap on request bodies — both endpoints take tiny JSON payloads.
MAX_BODY_BYTES = 64 * 1024
_HOST = "127.0.0.1"
_UI_PATH = Path(__file__).resolve().parent / "webui.html"
# The live run writes to the gitignored root report, NOT docs/sample-report.html —
# that one is the shipped showcase and must not be clobbered by a user run.
_REPORT_PATH = Path(__file__).resolve().parent.parent / "report.html"


def _ui_html() -> str:
    return _UI_PATH.read_text(encoding="utf-8")


class _Handler(BaseHTTPRequestHandler):
    # Silence the default per-request logging to stderr.
    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _origin_ok(self) -> bool:
        """Reject cross-site writes.

        Any page the user happens to visit can POST to 127.0.0.1 without a CORS
        preflight (a simple request with Content-Type: text/plain sails through),
        which would let it plant a token in our local store. Browsers always
        attach an Origin header to such requests, so requiring it to match our
        own host blocks them. Non-browser clients (curl, the test suite) send no
        Origin and are allowed.
        """
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        return origin in (f"http://{host}", f"https://{host}")

    def _json(self, obj: Dict[str, Any], code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _serve_report(self) -> None:
        """Serve the freshly written report.

        The query string carries the file's mtime purely as a cache buster, so
        it is ignored here.
        """
        report = _REPORT_PATH
        if not report.is_file():
            self._json({"error": "还没有生成报告，先跑一次分析"}, 404)
            return
        self._send(200, report.read_bytes(), "text/html; charset=utf-8")

    def _read_json(self) -> Dict[str, Any]:
        """Parse a JSON body with a hard size cap.

        `read(-1)` on a negative Content-Length would read until EOF, and an
        unbounded length lets a caller exhaust memory — neither is acceptable
        even on a loopback socket.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return {}
        if length <= 0 or length > MAX_BODY_BYTES:
            return {}
        try:
            raw = self.rfile.read(length)
            obj = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return {}
        return obj if isinstance(obj, dict) else {}

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                self._send(200, _ui_html().encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/status":
                self._json(_status())
            elif path == "/report":
                self._serve_report()
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, 500)

    def do_POST(self) -> None:  # noqa: N802
        if not self._origin_ok():
            self._json({"error": "跨站请求被拒绝"}, 403)
            return
        path = urlparse(self.path).path
        body = self._read_json()
        try:
            if path == "/api/token":
                self._json(_save_token(str(body.get("token", ""))))
            elif path == "/api/analyze":
                self._json(_analyze(str(body.get("city", "")).strip()))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, 500)


def _status() -> Dict[str, Any]:
    from .credentials import load_token, token_path, token_status

    ok, path, source = token_status()
    return {
        "configured": bool(ok),
        "source": source or "",
        "path": str(path or token_path()),
        "has_saved": bool(load_token()),
    }


def _save_token(token: str) -> Dict[str, Any]:
    from .credentials import looks_like_token, save_token

    if not token:
        return {"ok": False, "error": "Token 为空"}
    if not looks_like_token(token):
        return {"ok": False, "error": "格式不像有效 Token（过短或含空格）"}
    path, restricted = save_token(token)
    return {"ok": True, "path": str(path), "restricted": restricted}


def _analyze(city: str) -> Dict[str, Any]:
    from .analyze import analyse
    from .mcp_client import McpClient, McpError

    try:
        client = McpClient()  # picks up env var or the locally saved token
        client.initialize()
    except McpError as exc:
        return {"ok": False, "error": str(exc)}

    data = analyse(client=client, mode="live", city=city or "上海市")

    # Write the report next to the page source so the link always resolves.
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = _REPORT_PATH
    from .report import render

    report.write_text(render(data), encoding="utf-8")

    acc = data.account
    priced, total = data.coverage
    lot = data.lottery
    return {
        "ok": True,
        "report_url": f"/report?{report.stat().st_mtime_ns}",
        "report_path": str(report),
        "data": {
            "account": {
                "available": acc.available,
                "accumulated": acc.accumulated,
                "expired_total": acc.expired,
                "expiring_this_month": acc.expiring_soon,
                "lost_ratio": acc.lost_ratio,
            },
            "best_ppv": data.best_ppv,
            "coverage": [priced, total],
            "verdict": {"decision": data.verdict[0], "reason": data.verdict[1]},
            "lottery": {
                "ppv": {
                    "optimistic": lot.ppv("optimistic") if lot else None,
                    "realistic": lot.ppv("realistic") if lot else None,
                    "pessimistic": lot.ppv("pessimistic") if lot else None,
                }
            } if lot else None,
        },
    }


def serve(port: int = DEFAULT_PORT, open_browser: bool = True) -> int:
    """Start the local configuration server."""
    server = ThreadingHTTPServer((_HOST, port), _Handler)
    url = f"http://{_HOST}:{port}/"
    print("  麦麦积分清算局 · 本机配置面板")
    print("  " + "─" * 62)
    print(f"  {url}")
    print(f"  只监听 {_HOST}，外部无法访问")
    print("  " + "─" * 62)
    print("  流程：点按钮去 open.mcd.cn 拿 Token → 回来粘贴 → 直接出报告")
    print("  Ctrl+C 退出")
    print()

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  已退出。")
    finally:
        server.server_close()
    return 0
