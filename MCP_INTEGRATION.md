# MCP 集成说明

本文档说明本项目实际使用的麦当劳 MCP Server、Tool、调用流程与业务价值。
所有字段名与返回形态均来自实网抓取验证，不是推测。

---

## 1. MCP Server 信息

| 项目 | 值 |
|---|---|
| Server 名称 | `mcd-mcp` |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 鉴权方式 | HTTP Header `Authorization: Bearer <MCP_TOKEN>` |
| 官方仓库 | https://github.com/M-China/mcd-mcp-server |
| Token 申请 | https://open.mcd.cn/mcp （手机号登录 → 控制台 → 激活） |
| 限流 | 单 Token 600 次/分钟，超限返回 429 |

配置示例见 [`mcp-config.example.json`](./mcp-config.example.json)。

---

## 2. 三个必须知道的坑（实网验证）

### 坑一：返回值不是 JSON，是 Markdown

**这是接入时最大的障碍。** 工具返回的 `content[].text` 不是 JSON，而是一段写给 LLM 看的
Markdown 叙述，机器可读的 JSON 藏在里面：

```
# API Response Information

Below is the response from an API call. To help you understand the data...

## Response Structure
- **data.availablePoint**: 可用积分 (Type: string)
- **data.expiredPoint**: 已过期积分 (Type: string)

## Original Response

{"success":true,"code":200,"data":{"availablePoint":"556.5","expiredPoint":"2355.2"}}
```

更麻烦的是**包装方式不统一**：

| 工具 | JSON 位置 |
|---|---|
| `query-my-account` | `## Original Response` 之后 |
| `mall-points-products` | `## Original Response` 之后 |
| `query-meals` | `## Original Response` 之后 |
| `query-lottery-info` | `## Original Response` 之后 |
| `query-nearby-stores` | **内联在两行说明文字中间，没有该标题** |

结论：`json.loads(返回值)` 必然失败；只锚定 `## Original Response` 会在门店这一步漏掉。

`src/mcp_payload.py` 的三级解法：

1. **行扫描** — 大部分响应把 JSON 压缩在单独一行，逐行试 `json.loads`（最快）
2. **括号平衡扫描** — 字符串感知的通用兜底，正确处理字符串内的 `{}`
3. **放弃** — 返回 None，上层降级，绝不抛异常

顺带一提：部分工具的描述段里带有「必须按表格展示」「禁止模型丢弃字段」这类指令。
本项目只取数据，不执行这些展示指令。

### 坑二：数值字段是字符串，且可能带小数

```json
{"availablePoint": "556.5", "accumulativePoint": "5358.7", "drawPoint": "24"}
```

按 int 解析会丢精度甚至失败。全部走 `to_float`。

### 坑三：字段名有自己的拼写

`query-my-account` 的过期字段是 `currentMouthExpirePoint` / `lastMouthExpirePoint` /
`nextMouthExpirePoint` —— 是 **Mouth**（嘴），不是 Month（月）。

这是服务端的拼写，不是笔误修正的对象。别名表里同时接受了正确拼写，
但必须以服务端为准，否则读出来永远是 None。

---

## 3. 使用的 Tool 清单

| Tool | 所属域 | 必填参数 | 角色 |
|---|---|---|---|
| `query-my-account` | 积分账户 | — | 数据源①：余额与损耗 |
| `query-nearby-stores` | 门店 | `beType`, `searchType`（+`city`,`keyword`） | 拿 storeCode |
| `query-meals` | 菜单 | **`storeCode`**, `orderType`, `beType` | **数据源②：人民币价格锚点** |
| `mall-points-products` | 麦麦商城 | — | 数据源③：可兑换券列表 |
| `query-lottery-info` | 积分抽奖 | — | 数据源④：奖池与消耗规则 |
| `query-my-prizes` | 积分抽奖 | — | 校准：历史中奖分布 |

### 关键依赖：没有门店就没有价格

`query-meals` 不传 `storeCode` 会直接返回 `400 缺少参数`。
而菜单是人民币价格的唯一来源，所以：

```
storeCode 拿不到  →  菜单加载失败  →  所有券无法估值
```

此时工具明确报错并提示换城市，而不是返回一堆零 —— 静默的零比崩溃更危险。

---

## 4. 调用流程

```
┌────────────────────────────────────────────────────────────────┐
│ ① query-my-account                                             │
│   availablePoint 可用 / accumulativePoint 累计                  │
│   expiredPoint 已过期 / usedPoint 已用                          │
│   currentMouthExpirePoint 本月到期                              │
└───────────────────────────┬────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────┐
│ ② query-nearby-stores(city, keyword)  →  storeCode              │
└───────────────────────────┬────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────┐
│ ③ query-meals(storeCode, orderType=1, beType=1)                 │
│   → data.meals = {code: {name, currentPrice, originalPrice}}    │
│   → 101~106 条真实价格，建立 MealIndex                          │
└───────────────────────────┬────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────┐
│ ④ mall-points-products  （过滤 point=0 的纯现金商品）            │
│   "28.9元板烧四件套" 800分                                       │
│      → 匹配菜单「板烧鸡腿堡四件套」原价 ¥58.0                    │
│      → 收益 = 58.0 − 28.9 = ¥29.1                               │
│      → PPV = 29.1 / 800 × 100 = 3.64                            │
└───────────────────────────┬────────────────────────────────────┘
                            │  PPV 排序 + 完全背包求解
                            │
┌───────────────────────────▼────────────────────────────────────┐
│ ⑤ query-lottery-info                                            │
│   drawPoint 单次消耗 / prizes[] 奖池（无概率）                   │
│   → 每张券估值后按三情景概率求 EV                                │
└───────────────────────────┬────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────┐
│ ⑥ query-my-prizes   历史中奖，校验概率假设                       │
└───────────────────────────┬────────────────────────────────────┘
                            ▼
                   report.html  单文件可视化报告
```

**调用次数**：一次完整分析约 6 次 `tools/call`，远低于 600 次/分钟的限流上限。

**只读承诺**：全流程未调用 `mall-create-order`、`create-order`、`draw-lottery`、
`auto-bind-coupons` 等任何写操作 Tool。涉及真实积分扣减的动作一律不做。

---

## 5. 真实字段对照表

以下是实网抓到的字段，供后来者直接抄（不用再猜）：

### query-my-account

```json
{"availablePoint":"556.5","accumulativePoint":"5358.7","usedPoint":"2447",
 "frozenPoint":"0","expiredPoint":"2355.2",
 "currentMouthExpirePoint":"166","lastMouthExpirePoint":"0",
 "nextMouthExpirePoint":"0","currency":"麦享会积分"}
```

### query-meals

```json
{"categories":[{"name":"巨无霸\n牛鱼肉堡","meals":[{"code":"9900005456"}]}],
 "meals":{"9900005456":{"name":"麦辣鸡腿汉堡三件套",
                        "currentPrice":"34","originalPrice":"47.5"}}}
```

注意 `meals` 是 **code → 详情的映射**，不是数组。

### mall-points-products

```json
{"spuName":"28.9元板烧四件套","spuId":1010,"point":"800","price":"0",
 "catName":"到店专用","status":2,"upTime":"...","downTime":"..."}
```

`point="0"` 表示纯现金商品（派对、读书会等），**必须过滤**，否则会污染积分排行。

### query-lottery-info

```json
{"activityName":"麦麦积分抽奖","drawPoint":"24","drawTypeText":"消耗积分抽奖",
 "availablePoint":"556.5",
 "prizes":[{"name":"板烧三件套5折券","typeText":"优惠券"}, ...]}
```

奖池**不含任何概率或库存字段** —— 这是三情景 EV 设计的直接原因。

### query-my-prizes

```json
{"prizes":[{"name":"麦旋风5折券","prizeTypeText":"优惠券",
            "recordTime":"2026-09-03 18:07:14","statusText":"已失效"}]}
```

---

## 6. 字段容错设计

即便上表已经很全，仍然假设上游会变。`src/models.py` 的 `dig()` 提供：

- **多别名**：中英文、驼峰、下划线，以及服务端特有的拼写（Mouth/Month 都收）
- **深度无关**：任意嵌套层级做深度优先搜索
- **浅层优先**：先比对当前层所有 key，再下钻，避免误取无关子树
- **永不抛异常**：取不到返回 None，走降级分支
- **类型安全**：`to_float` / `parse_date` / `parse_percent` 各自处理字符串数字、逗号、
  百分号、8 种日期格式、秒/毫秒时间戳

配套 `--dump-raw` 把原始报文完整落盘，便于上游变更时快速定位：

```bash
python points_rescue.py --live --dump-raw raw.json
```

---

## 7. 业务价值

对麦当劳而言，这套组合解决的是**积分资产低效沉淀**问题：

1. **降低积分沉默率**。用户知道损耗率（本项目实测 44%）后，兑换意愿会明显高于
   "看到一个余额数字但没概念"。
2. **提升兑换的确定性**。统一的「元/100积分」标尺让犹豫中的用户有客观依据，决策链路缩短。
3. **把抽奖从玄学变透明**。用户清楚知道抽奖的期望区间后，反而更愿意在知情前提下
   为娱乐付费，或坚定选择兑换 —— 都比「猜着投然后后悔」体验好。
4. **为积分运营提供可量化口径**。同一套 PPV 模型反向可用于评估积分体系健康度：
   若整体 PPV 长期过低，说明获取成本与兑换价值之间存在缺口。

对开发者而言，本项目验证了一件事：**麦当劳 MCP 的价值不止于点餐自动化。**
把「菜单价格」当作一把尺子去度量「商城积分价」，就能打开一个此前无人涉足的分析维度。
