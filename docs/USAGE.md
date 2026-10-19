# 使用指南

面向**第一次看到这个项目的人**。如果你只是想知道它是什么，看
[项目展示页](../site/index.html) 或 [样例报告](./sample-report.html) 就够了，不用往下读。

---

## 0. 你需要什么

| 要求 | 说明 |
|---|---|
| Python 3.9+ | 只用标准库，**不需要 pip install** |
| 网络 | 只有 `--live` 需要；`--demo` 完全离线 |
| 麦当劳 MCP Token | 只有 `--live` 需要，免费申请，见第 3 节 |

检查你的 Python：

```bash
python --version
# 期望：Python 3.9.x 或更高
```

Windows 上如果 `python` 不可用，试试 `py --version`。

---

## 1. 三十秒：先看效果（不需要任何东西）

```bash
git clone https://github.com/wdzju/mcd-points-rescue.git
cd mcd-points-rescue
python points_rescue.py --demo
```

跑完会在当前目录生成 `report.html`，用浏览器打开就是完整报告。

`--demo` 用的是**内置的脱敏样例数据**，不连网、不花钱、不需要 Token。
它只用来让你看清工具长什么样、算什么，**结论和你的账号无关**。

---

## 2. 关于 GitHub 上的两个 HTML

`site/index.html`（展示页）和 `docs/sample-report.html`（样例报告）
在 GitHub 网页上点进去只会看到**源码**，这是 GitHub 的默认行为。

两种办法看到渲染效果：

**A. 开 GitHub Pages（仓库主人一次性操作）**

```
仓库 → Settings → Pages
  Source: Deploy from a branch
  Branch: main   /  目录: / (root)
  → Save
```

等约一分钟，访问：

```
https://wdzju.github.io/mcd-points-rescue/          → 自动跳到展示页
https://wdzju.github.io/mcd-points-rescue/site/     → 项目展示页
https://wdzju.github.io/mcd-points-rescue/docs/sample-report.html  → 样例报告
```

根目录的 `index.html` 是一个跳转页，专门为 Pages 准备的。

**B. 克隆到本地直接打开（不需要 Pages）**

```bash
# macOS
open site/index.html
# Windows
start site\index.html
```

---

## 3. 三分钟：跑你自己的真实数据

### 先拿 Token

麦当劳 MCP 的登录是**手机号 + 短信验证码**，必须由你本人在官网完成。

1. 打开 <https://open.mcd.cn/mcp>（确认地址栏是 `open.mcd.cn`）
2. 右上角 **登录** → 手机号完成验证
3. 右上角 **控制台**
4. 点 **激活**，同意服务协议
5. 复制生成的 Token

> 本工具**不会**替你完成这一步，也不会代持你的手机号或验证码。
> 详见 [为什么不做一个登录页面](../README.md#为什么不做一个登录页面)。

### 方式一：浏览器面板（推荐给不熟命令行的）

```bash
python points_rescue.py --web
```

会自动打开 `http://127.0.0.1:8723`，页面上三步：

1. 点按钮去官网拿 Token（新窗口）
2. 回来粘贴 → 保存
3. 填城市 → 开始分析 → 直接看结果

服务只监听 `127.0.0.1`，外部访问不到；Token 存在本机，不出机器。

### 方式二：命令行

```bash
# 交互式配置 Token（只需一次）
python points_rescue.py --setup

# 自检：确认 Token、连接、门店、菜单都通
python points_rescue.py --doctor

# 跑分析
python points_rescue.py --live --city 上海市 --out my-report.html
```

`--city` 填**你自己的城市**（`上海市`、`北京市`……），否则价格锚点用的是别人的门店。

### 方式三：环境变量

```bash
export MCD_MCP_TOKEN=你的Token          # Windows: set MCD_MCP_TOKEN=你的Token
python points_rescue.py --live --city 上海市
```

Token 解析顺序：`--token` → 环境变量 `MCD_MCP_TOKEN` → `~/.mcd-points-rescue/token`。

清除本地保存的 Token：

```bash
python points_rescue.py --forget
```

---

## 4. 在 AI 客户端里用（对话式，最省事）

这一节讲「让 AI 替你跑」，和上面的命令行是两条路。

**不绑定任何特定客户端** —— Claude Desktop、Cursor、Cherry Studio、WorkBuddy 都能用，
只要它能连 MCP。

### 4.1 通用方式：复制一行链接（任何支持 MCP 的客户端）

先把 MCP 配好。各家界面不同，但认的都是 `mcpServers` 这个字段：

```json
{"mcpServers":{"mcd-mcp":{"type":"streamablehttp","url":"https://mcp.mcd.cn","headers":{"Authorization":"Bearer 你的Token"}}}}
```

| 客户端 | 在哪里填 |
|---|---|
| Claude Desktop | 配置文件里的 `mcpServers` |
| Cursor | Settings → MCP |
| Cherry Studio | 设置 → MCP 服务器 |
| WorkBuddy | 【连接器】→【自定义连接器】→【配置 MCP】 |
| 其他 | 找设置里的 MCP / 自定义连接器 |

然后直接发这句给 AI：

```
读一下 https://raw.githubusercontent.com/wdzju/mcd-points-rescue/main/SKILL-lite.md 然后按里面的流程帮我查麦当劳积分
```

AI 会自己去读那份纯提示词的说明，然后调接口、算结果、讲结论。

> ⚠️ **纯网页对话用不了**（ChatGPT 网页、Kimi 网页这类）：没有 MCP 能力，
> 连不上 `mcp.mcd.cn`，只能看演示数据，算不出你的真实账户。

这是**零安装**路径，代价是精度不如 Python 版 —— 模糊匹配靠 AI，结果不可完全复现。

### 4.2 WorkBuddy 额外支持：装成常驻技能

如果你用 WorkBuddy，还可以把它装成技能，之后**说一句就自动触发**，不用每次贴链接。

```bash
# macOS / Linux
mkdir -p ~/.workbuddy/skills
git clone https://github.com/wdzju/mcd-points-rescue ~/.workbuddy/skills/mcd-points-rescue
```

Windows 上把目标路径换成 `%USERPROFILE%\.workbuddy\skills\mcd-points-rescue`。

重启 WorkBuddy，在任意会话里说：

> 帮我看看我的麦当劳积分

**或者不装，直接打开目录**：用 WorkBuddy 打开仓库目录（**必须是仓库本身，不是上级目录**），
说同一句话。原因：WorkBuddy 只扫描 `{工作区}/.workbuddy/skills/`。

### 4.3 AI 会怎么执行（四个工具，四段输出）

不管哪个客户端，流程都一样：

| 步骤 | 工具 | 做什么 |
|---|---|---|
| 1 | `query-my-account` | 累计 / 已用 / 已过期 / 可用 / 本月到期，算蒸发率 |
| 2 | `mall-points-products` | 券列表，按「菜单原价 − 券名价格」算收益，统一换算成 元/100积分 排序 |
| 3 | `query-nearby-stores` + `query-meals` | 取菜单原价（指定城市/门店更好，不指定就按券名匹配） |
| 4 | `query-lottery-info` | 有概率才算期望值，没概率只做定性判断 |

### 4.4 不需要配置 MCP 连接器（完整版的情况）

项目的 CLI **自己直连** `https://mcp.mcd.cn`（见 `src/mcp_client.py`），
不依赖任何客户端机制。

所以跑 `python points_rescue.py --live` 时**不用**配 MCP 连接器。
`mcp-config.example.json` 只是给 AI 客户端用的参考。

Token 通过 `--token` / 环境变量 `MCD_MCP_TOKEN` / 本地文件三选一提供即可。

### 4.5 两种形态的分工

| 场景 | 用哪个 |
|---|---|
| 日常快速问一句 | 对话式（任何支持 MCP 的 AI） |
| 要存档 HTML 报告 | CLI `--out` |
| 要做二次开发 | CLI `--json` |
| 校准字段名 | CLI `--dump-raw` |

分析引擎完全相同，对话式只是包了一层自然语言交互。

---

## 5. 跑出奇怪结果时，先看这两点

### 现在是几点？

`query-meals` 返回的是**当前可售菜单**。**10:30 之前是早餐菜单**，只有麦满分、
炒双蛋、油条、豆浆 —— 没有板烧、四件套、巨无霸。

后果：所有正餐券都无法估值，**覆盖率会从约 71% 掉到 30% 上下**。

工具会检测到这个情况并在报告顶部提示：

> 当前拉取的是早餐时段菜单（约 10:30 前），其中几乎没有正餐单品 ——
> 所以多数正餐券无法估值、覆盖率会明显偏低。建议 10:30 之后再跑一次。

**想看完整结果，请在正餐时段（10:30–22:00）运行。**

### 用的是哪家门店？

不同门店的菜单差异很大（实测 60–101 项），菜单越薄、能对齐的单品越少、覆盖率越低。
而且门店搜索按距离排序，距离来自 IP 定位，**结果不稳定**。

工具会自动对比前 5 家候选、选菜单最全的一家。想固定用某一家：

```bash
python points_rescue.py --live --city 上海市 --store <你的门店编码>
```

门店编码从 `--doctor` 的输出里能看到（形如 `麦当劳XX餐厅（1990123）` 括号里的数字）。

---

## 6. 常见问题

**Q：跑完说"缺少 MCP Token"？**
A：你还没配置。用 `--setup` 或 `--web`，或者设环境变量。只想看效果就直接 `--demo`。

**Q：报告里很多"无法估值"？**
A：正常。商城里有相当一部分券是「指定小食任选」这类定位不到具体餐品的，
工具刻意**不编数字**，宁可标原因。另外请确认不是早餐时段。

**Q：数字和我 App 里看到的不一样？**
A：只有两种可能：一是时段/门店不同导致菜单不同（见第 4 节）；
二是 App 的活动状态、库存实时变化。以麦当劳官方 App 为准。

**Q：会不会自动帮我兑换或下单？**
A：**不会。** 本项目全程只读，不调用任何下单、兑换、抽奖接口。
所有操作都需要你自己在 App 里确认。

**Q：它会把我的 Token 或积分数据传到哪去吗？**
A：不会。Token 存在你本机，所有请求都是你的电脑直接发给麦当劳 MCP，
本项目没有任何后端服务器。

---

## 7. 想二次开发？

- 架构与模块说明：[MCP_INTEGRATION.md](../MCP_INTEGRATION.md)
- 设计系统（配色、排版、组件规范）：[DESIGN.md](../DESIGN.md)
- 测试：`python -m unittest discover -s tests`（79 个用例，纯标准库）
- 想看原始报文：`python points_rescue.py --live --dump-raw raw.json`
