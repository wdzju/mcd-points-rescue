# 在 WorkBuddy 中使用

本项目既是一个独立 CLI 工具，也是一个可直接安装的 WorkBuddy Skill。

## 安装为 Skill

把整个目录复制到用户级 skills 目录：

```bash
# Windows
copy /Y SKILL.md %USERPROFILE%\.workbuddy\skills\mcd-points-rescue\SKILL.md

# macOS / Linux
mkdir -p ~/.workbuddy/skills/mcd-points-rescue
cp -r . ~/.workbuddy/skills/mcd-points-rescue/
```

重新进入 WorkBuddy 会话后即可自动识别。

## 配置 MCP 连接器

在 WorkBuddy 左侧边栏【专家·技能·连接器】→【连接器】→【自定义连接器】→【配置 MCP】，
填入 `mcp-config.example.json` 的内容，并把 `${MCD_MCP_TOKEN}` 换成你自己的 Token。

然后在【自定义连接器】列表中把 `mcd-mcp` 启用。

## 对话式使用

配置完成后，直接用自然语言提问即可：

> 我的麦麦积分还能干嘛？

> 我这月有多少积分要过期？值多少钱？

> 积分抽奖划不划算？帮我算一下

> 帮我把快过期的积分安排掉，给个方案

WorkBuddy 会自动触发本 Skill，跑分析并用人话讲给你听。

## Skill 与 CLI 的分工

| 场景 | 用哪个 |
|---|---|
| 日常快速问一句 | Skill（对话） |
| 要存档 HTML 报告 | CLI `--out` |
| 要做二次开发 | CLI `--json` |
| 校准字段名 | CLI `--dump-raw` |

两者的分析引擎完全相同，Skill 只是包了一层自然语言交互。
