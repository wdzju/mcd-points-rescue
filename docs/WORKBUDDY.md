# 在 WorkBuddy 中使用

本项目既是一个独立 CLI 工具，也是一个 WorkBuddy Skill。

## 方式一：直接打开仓库目录（推荐）

**不需要任何安装步骤。**

1. 用 WorkBuddy 打开**这个仓库的根目录**（不是它的父目录）
2. 直接说：「帮我看看我的麦当劳积分」

AI 会自动读取 `.workbuddy/skills/mcd-points-rescue/SKILL.md`，按内置流程执行。

> **为什么必须是仓库目录**：WorkBuddy 只扫描 `{工作区}/.workbuddy/skills/`。
> 打开父目录的话，Skill 不会被自动加载。

### 第一次会发生什么

你大概率还没配 Token，所以会看到这个流程：

```
AI：检查 Token → 没找到
  ↓
AI：先跑演示模式，生成一份样例报告
  ↓
AI：报告在 report.html，你先看看长什么样
  ↓
你想跑真实数据 → AI 引导你在终端执行 --setup 或 --web
  ↓
配好 → AI 自检 → 跑分析 → 用大白话讲结论
```

**Token 全程不经过对话** —— 你在自己的终端里粘贴，AI 看不到。

### 可以这样问

> 我的麦麦积分还能干嘛？

> 我这月有多少积分要过期？值多少钱？

> 积分抽奖划不划算？帮我算一下

> 帮我把快过期的积分安排掉，给个方案

## 方式二：装到用户级 skills 目录

如果你想让**所有** WorkBuddy 工作区都能用这个 Skill，可以装到用户级目录。

```bash
# macOS / Linux
mkdir -p ~/.workbuddy/skills/mcd-points-rescue
cp SKILL.md ~/.workbuddy/skills/mcd-points-rescue/
```

```powershell
# Windows PowerShell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.workbuddy\skills\mcd-points-rescue"
Copy-Item SKILL.md "$env:USERPROFILE\.workbuddy\skills\mcd-points-rescue\"
```

⚠️ **但这样有个问题**：用户级 Skill 目录里只有 `SKILL.md`，**没有代码**。
执行 `python points_rescue.py` 时，取决于你当时的工作区是不是这个项目目录。

**结论：只在你确实需要跨项目调用时才装。日常使用方式一就够。**

## 不需要配置 MCP 连接器

本项目的 CLI **自己直连** `https://mcp.mcd.cn`（见 `src/mcp_client.py`），
不依赖 WorkBuddy 的连接器机制。

所以**不用**去【连接器】里配置 `mcd-mcp`。`mcp-config.example.json` 只是给
WorkBuddy / 其他 MCP 客户端的通用配置参考，跑本项目的 CLI 时用不上。

Token 通过 `--token` / 环境变量 `MCD_MCP_TOKEN` / 本地文件三选一提供即可。

## 手动触发（工作区不是仓库目录时）

如果你已经在别的项目里，想临时用一下这个 Skill：

1. 在对话里 `@` 引用这个仓库的 `SKILL.md`
2. 或直接说：「读一下 `<仓库路径>/SKILL.md`，按它的流程帮我跑麦当劳积分分析」

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
A：工作区不对。确认 WorkBuddy 打开的是仓库根目录，那里应该有 `points_rescue.py`。

**Q：AI 让我把 Token 发给它？**
A：不该这样。SKILL.md 里明确写了不能索要 Token。请拒绝，并让它引导你
在自己的终端跑 `python points_rescue.py --setup`。

**Q：跑出来覆盖率很低（30% 左右）？**
A：多半是早餐时段（10:30 前），菜单里没有正餐单品。换到 10:30 之后再跑。

**Q：能不能自动帮我兑换？**
A：不能，这是设计上的边界。本项目只读，所有操作需要你在麦当劳 App 里手动完成。
