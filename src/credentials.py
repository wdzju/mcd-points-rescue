"""Local credential handling for the McDonald's MCP token.

Design decision: no login system
--------------------------------
The obvious question is "why not build a login page so users just sign in?".
Because McDonald's MCP authentication is **phone number + SMS code**, which
means:

1. **It is the user's real identity.** Holding it — or proxying it — means
   taking custody of someone else's account credential. That is a compliance
   and security obligation this tool has no business accepting.
2. **It would turn a local CLI into a hosted service.** The whole point of
   this project is that it runs on your machine with zero dependencies and
   sends your data nowhere. A backend breaks that promise.
3. **The MCP service rules govern token use.** Acting as an intermediary in
   token acquisition is exactly the kind of thing those rules tend to restrict.
4. **It buys very little.** The expensive part is not typing the token once —
   it is *knowing where to get it*. That is a documentation problem, and
   documentation is cheaper than a credential vault.

So the answer is: **guided authorisation, local custody, never transmitted.**

    user fetches the token themselves  →  pastes once  →  stored locally (0600)
    →  reused automatically  →  nothing ever leaves the machine

Guarantees enforced here:
- Token lives in the user's own home directory, never in the repo.
- File is created with owner-only permissions.
- No logging, no printing, no echoing the token back.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Optional

APP_DIR_NAME = ".mcd-points-rescue"
TOKEN_FILE_NAME = "token"

# Anything that does not look like a plausible token is rejected early, so a
# pasted URL or a stray line does not end up written to disk.
MIN_TOKEN_LENGTH = 8


def token_path() -> Path:
    return Path.home() / APP_DIR_NAME / TOKEN_FILE_NAME


def looks_like_token(value: str) -> bool:
    candidate = (value or "").strip()
    if len(candidate) < MIN_TOKEN_LENGTH:
        return False
    return not any(ch.isspace() for ch in candidate)


def _restrict_permissions(path: Path) -> bool:
    """Tighten the file to owner-only. Returns whether it actually worked.

    On POSIX this is `chmod 600`. On Windows `os.chmod` only honours the
    read-only bit — calling it and reporting success would be a lie, so we
    shell out to `icacls` instead and report honestly if that fails too.
    """
    if os.name != "nt":
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            return True
        except OSError:
            return False

    import subprocess

    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if not user:
        return False
    try:
        result = subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def save_token(token: str) -> tuple[Path, bool]:
    """Persist the token. Returns (path, permissions_are_owner_only)."""
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.strip(), encoding="utf-8")
    return path, _restrict_permissions(path)


def load_token() -> Optional[str]:
    """Read a previously saved token, if any."""
    path = token_path()
    if not path.is_file():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def clear_token() -> bool:
    path = token_path()
    if not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def token_status() -> tuple[bool, Optional[Path], Optional[str]]:
    """Where the token came from — reported without revealing it."""
    from_env = os.environ.get("MCD_MCP_TOKEN")
    if from_env:
        return True, None, "环境变量 MCD_MCP_TOKEN"
    saved = load_token()
    if saved:
        return True, token_path(), f"本地文件 {token_path()}"
    return False, token_path(), None


SETUP_STEPS = [
    "打开 https://open.mcd.cn/mcp",
    "点右上角【登录】，用手机号完成验证",
    "登录后点右上角【控制台】",
    "点【激活】申请 MCP Token",
    "同意服务协议后，复制生成的 Token",
]


def print_setup_guide() -> None:
    print("  申请麦当劳 MCP Token（只需做一次，大约 1 分钟）：")
    print()
    for idx, step in enumerate(SETUP_STEPS, 1):
        print(f"    {idx}. {step}")
    print()
    print("  拿到后粘贴到这里，本工具会保存在你本机的")
    print(f"    {token_path()}")
    print("  权限设为仅本人可读，不会写入仓库，也不会上传到任何地方。")
    print()


def interactive_setup() -> int:
    """Walk the user through authorisation and store the token locally."""
    print_setup_guide()
    try:
        raw = input("  粘贴 Token（直接回车取消）: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  已取消。")
        return 1

    if not raw:
        print("  未输入，已取消。")
        return 1
    if not looks_like_token(raw):
        print("  这个不像有效的 Token（长度过短或含有空格），未保存。")
        return 2

    path, restricted = save_token(raw)
    # Keep the secret out of scrollback: never echo it back.
    print(f"\n  已保存到 {path}")
    if restricted:
        print("  权限已收紧为仅本人可读写。")
    else:
        print("  注意：权限收紧未生效，该文件可能对其他本机账户可读。")
        print("  文件位于你的用户目录下，通常已有系统级保护。")
    print("  现在可以直接运行：python points_rescue.py --live")
    return 0


def _mask(token: Optional[str]) -> str:
    if not token:
        return "—"
    head = token[:3]
    return f"{head}{'*' * max(3, len(token) - 3)}（长度 {len(token)}）"


def run_doctor(endpoint: str) -> int:
    """Diagnose every upstream dependency and report what is broken."""
    print("  自检：逐项确认上游是否可用")
    print("  " + "─" * 62)

    ok, path, source = token_status()
    print(f"  Token        {'已配置' if ok else '缺失'}  {source or ''}")
    if ok:
        print(f"               值 {_mask(os.environ.get('MCD_MCP_TOKEN') or load_token())}")
    else:
        print("               运行 python points_rescue.py --setup 进行配置")
        print("  " + "─" * 62)
        return 1

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from .mcp_client import McpClient, McpError
    except Exception as exc:  # noqa: BLE001
        print(f"  客户端      导入失败：{exc}")
        return 1

    try:
        client = McpClient(endpoint=endpoint)
        client.initialize()
    except McpError as exc:
        print(f"  连接        失败：{exc}")
        print("  " + "─" * 62)
        return 1
    print("  连接        正常")

    from .mcp_payload import unwrap_data

    checks = [
        ("积分账户", "query-my-account", None, lambda d: "可用积分" if isinstance(d, dict) else "异常"),
        ("商城券池", "mall-points-products", None, lambda d: f"{len(d) if isinstance(d, list) else 0} 件"),
        ("抽奖活动", "query-lottery-info", None, lambda d: str((d or {}).get("activityName", "—"))),
        ("历史订单", "order-list", None, lambda d: f"{len((d or {}).get('list', []))} 单"),
    ]
    failures = 0
    for label, tool, args, describe in checks:
        try:
            data = unwrap_data(client.call_json(tool, args or {}))
            print(f"  {label:<10}  正常　{describe(data)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {label:<10}  失败　{str(exc)[:48]}")
            if tool != "order-list":  # order-list is an enhancement
                failures += 1

    # Store lookup is what unlocks menu pricing.
    try:
        from .analyze import fetch_store_code

        code, label, _ = fetch_store_code(client, "上海市", "麦当劳")
        if code:
            print(f"  门店        正常　{label}")
        else:
            print("  门店        未找到（请确认 --city 能搜到门店）")
            failures += 1
    except Exception as exc:  # noqa: BLE001
        print(f"  门店        失败　{str(exc)[:48]}")
        failures += 1

    print("  " + "─" * 62)
    if failures:
        print(f"  {failures} 项不可用，相关分析会降级。")
        return 1
    print("  全部可用，可以跑 --live 了。")
    return 0
