# 在 WorkBuddy 中使用

本项目既是一个独立 CLI 工具，也是一个 WorkBuddy Skill。

## 方式一：装成全局技能（推荐）

装一次，之后**任何** WorkBuddy 会话里都能用。

```bash
# macOS / Linux
mkdir -p ~/.workbuddy/skills
git clone https://github.com/wdzju/mcd-points-rescue ~/.workbuddy/skills/mcd-points-rescue
```

```powershell
# Windows PowerShell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.workbuddy\skills" | Out-Null
git clone https://github.com/wdzju/mcd-points-rescue "$env:USERPROFILE\.workbuddy\skills\mcd-points-rescue"
```

**重启 WorkBuddy**，然后在任意会话里说：

> 帮我看看我的麦当劳积分

没有 git 的话，下载 ZIP 解压到 `~/.workbuddy/skills/`
（Windows：`%USERPROFILE%\.workbuddy\skills\`）也一样：
<https://github.com/wdzju/mcd-points-rescue/archive/refs/heads/main.zip>

### 装完怎么确认

在 WorkBuddy 里问「你有 mcd-points-rescue 这个技能吗」，或者确认文件存在：

```bash
ls ~/.workbuddy/skills/mcd-points-rescue/SKILL.md
```

## 方式二：不装，直接打开目录

```bash
git clone https://github.com/wdzju/mcd-points-rescue
```

用 WorkBuddy 打开 `mcd-points-rescue` 这个目录，说同一句话。

> **必须是仓库目录本身，不能是它的上级目录。**
> WorkBuddy 只扫描 `{工作区}/.workbuddy/skills/`，打开上级目录时 Skill 不会被加载。

### 两种方式的区别

| | 全局安装 | 打开目录 |
|---|---|---|
| 装一次 | 之后到处能用 | 每次都要打开对目录 |
| 代码位置 | `~/.workbuddy/skills/mcd-points-rescue/` | 你 clone 的地方 |
| 更新 | 在技能目录 `git pull` | 在仓库目录 `git pull` |
| 适合 | 长期使用 | 试一次 |

## 第一次会发生什么

你大概率还没配 Token，所以会看到这个流程：

```
你说「帮我看看我的麦当劳积分」
  ↓
它检查 Token → 没找到
  ↓
先用演示数据跑一份，告诉你报告在 report.html
  ↓
你想看真实数据 → 它引导你在终端执行 --setup 或 --web
  ↓
配好 → 自检 → 跑你自己的账户 → 用大白话讲结论
```

**Token 全程不经过对话** —— 你在自己的终端里粘贴，AI 看不到。

### 可以这样问

> 我的麦麦积分还能干嘛？

> 我这月有多少积分要过期？值多少钱？

> 积分抽奖划不划算？帮我算一下

> 帮我把快过期的积分安排掉，给个方案

## 不需要配置 MCP 连接器

本项目的 CLI **自己直连** `https://mcp.mcd.cn`（见 `src/mcp_client.py`），
不依赖 WorkBuddy 的连接器机制。

所以**不用**去【连接器】里配置 `mcd-mcp`。`mcp-config.example.json` 只是给
WorkBuddy / 其他 MCP 客户端的通用配置参考，跑本项目的 CLI 时用不上。

Token 通过 `--token` / 环境变量 `MCD_MCP_TOKEN` / 本地文件三选一提供即可。

## Skill 与 CLI 的分工

| 场景 | 用哪个 |
|---|---|
| 日常快速问一句 | Skill（对话） |
| 要存档 HTML 报告 | CLI `--out` |
| 要做二次开发 | CLI `--json` |
| 校准字段名 | CLI `--dump-raw` |

两者的分析引擎完全相同，Skill 只是包了一层自然语言交互。

## 常见问题

**Q：AI 说找不到 `points_rescue.py`？**

A：当前目录不对。全局安装的请先执行：

```bash
cd ~/.workbuddy/skills/mcd-points-rescue
```

Windows 用 `cd "$env:USERPROFILE\.workbuddy\skills\mcd-points-rescue"`。
进去后确认 `points_rescue.py` 在里面。

**Q：AI 让我把 Token 发给它？**

A：不该这样。SKILL.md 里明确写了不能索要 Token。请拒绝，并让它引导你
在自己的终端跑 `python points_rescue.py --setup`。

**Q：跑出来覆盖率很低（30% 左右）？**

A：多半是早餐时段（10:30 前），菜单里没有正餐单品。换到 10:30 之后再跑。

**Q：Mac 上 `python` 报 command not found？**

A：用 `python3`。下文所有命令都替换成 `python3 points_rescue.py`。

**Q：能不能自动帮我兑换？**

A：不能，这是设计上的边界。本项目只读，所有操作需要你在麦当劳 App 里手动完成。
