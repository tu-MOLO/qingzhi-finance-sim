# 接口契约

> 本文件为当前落地的 HTTP 接口契约。设计阶段的初版（层间函数签名、P-01 至 E-03 十六个模块接口）在实现阶段改为浏览器可调用的 REST 接口后已失效，不再保留。

## 一、通用约定

1. 路径前缀 `/api/v1`，另有 `/api/v1/health` 健康检查。
2. 成功响应统一为 `{"ok": true, "data": ...}`；失败为 `{"ok": false, "error": {"code": ..., "message": ..., "field": ...}}`。`field` 仅在能定位到具体字段时出现。
3. 全部响应字段使用驼峰命名；请求体同时接受下划线与驼峰，归一化在服务端完成。
4. 服务只监听本机回环地址，并在请求进入前校验主机名，非本机地址直接拒绝。
5. 请求体有长度上限，超出返回 413。重计算接口带互斥，避免并发推演把内存打满。
6. 响应头加固：禁用内容类型嗅探、限制跨源资源加载、设置内容安全策略。
7. 错误提示一律使用中文、指明具体字段或原因、不暴露堆栈。服务端日志只记异常类型，不记消息与请求体。

## 二、接口清单

### （一）配置目录

| 方法与路径 | 用途 |
| --- | --- |
| GET /catalog | 前端启动所需的全部枚举、文案与配置，一次取齐 |
| GET /catalog/dictionaries、/dictionary-types、/dictionary-items/<type> | 字典 |
| GET /catalog/settings、/accounts、/risk-levels、/ui-texts、/messages、/parameters | 配置项、账户定义、风险分级、界面文案、提示文案、参数 |
| PUT /catalog/<resource> | 写入，resource 取 ui-texts、messages、settings、dictionary-items、parameters、data-sources、accounts、risk-levels |
| DELETE /catalog/<resource>/<key> | 删除，仅 ui_texts、messages、dict_items、app_settings 四类支持 |
| GET /catalog/change-log | 变更留痕 |

任何写入都会让配置缓存失效，下一次读取时重建，因此改参数立即生效，不需要重启。

### （二）画像

| 方法与路径 | 用途 |
| --- | --- |
| POST /profile/validate | 校验画像，返回错误清单 |
| POST /profile/preview | 结余预览。期望收入的口径属业务逻辑，放在服务端计算 |

### （三）典型画像

| 方法与路径 | 用途 |
| --- | --- |
| GET /archetypes、/archetypes/<id> | 列表与详情，返回时区分内置画像与用户档案 |
| GET /archetypes/<id>/profile | 取画像的可编辑结构 |
| POST /archetypes、PUT /archetypes/<id>、DELETE /archetypes/<id> | 用户档案的增删改，内置画像不可删除 |

### （四）推演与方案

| 方法与路径 | 用途 |
| --- | --- |
| POST /simulation/run | 推演。返回分位带、目标结果、账户分配、风险容量、情景对比 |
| POST /simulation/plan | 二选一方案求解 |

### （五）术语与语料

| 方法与路径 | 用途 |
| --- | --- |
| GET /terms、/terms/<code>、/corpus-documents | 术语与语料文档 |
| POST /terms/explain | 三层解释。内部委托给术语解释智能体，与智能体运行接口共用同一条链路 |
| POST /terms、PUT /terms/<code>、DELETE /terms/<code> | 术语增删改 |
| POST /corpus-documents、PUT /corpus-documents/<code>、DELETE /corpus-documents/<code> | 语料增删改 |

### （六）智能体

| 方法与路径 | 用途 |
| --- | --- |
| GET /agents、/agents/<code>、/agent-tools | 智能体与工具定义 |
| POST /agents/<code>/run | 运行一次智能体 |
| GET /agent-settings | 智能体运行配置状态，凭据只返回是否存在的布尔值 |
| PUT /agent-settings | 保存使用者在设置页填写的配置；凭据写入 .env.local，不入库 |
| POST /agent-settings/test | 连通性诊断。只回报是否接通与失败原因，不返回模型输出 |

## 三、核心数据结构

### （一）画像请求

```json
{
  "profileId": "custom",
  "name": "我的画像",
  "city": "gz",
  "grade": "junior",
  "livingCost": 2050,
  "livingGrowth": 0.03,
  "initialBalance": 3000,
  "riskAppetite": "medium",
  "months": 96,
  "paths": 10000,
  "seed": 20260930,
  "incomeSources": [
    {
      "sourceType": "part_time",
      "enabled": true,
      "probability": 0.68,
      "amountLow": 500, "amountMid": 1000, "amountHigh": 1500,
      "startMonth": 1, "endMonth": 96,
      "interruptProb": 0.05
    }
  ],
  "expenses": [
    { "category": "rent", "amount": 900, "enabled": true }
  ],
  "goals": [
    { "goalId": "g1", "name": "升学备付金", "amount": 30000, "dueMonth": 30, "priority": 1 }
  ],
  "budget": { "growthMonthly": 300, "treatMonthly": 600 }
}
```

枚举一律使用字典编码，服务端按字典定义补全缺失项。收入来源的分布形态与是否允许填概率、中断、时间窗口，由该类别的字典属性决定：固定型收入概率恒为一、中断概率恒为零。

### （二）推演结果

```json
{
  "seed": 20260930,
  "months": 96,
  "paths": 10000,
  "treatMonthly": 600,
  "balancePercentiles": { "p10": [], "p50": [], "p90": [] },
  "goalResults": [
    {
      "goalId": "g1", "name": "升学备付金", "amount": 30000,
      "dueMonth": 30, "priority": 1,
      "hitProbability": 0.62,
      "reachedRate": 0.91,
      "hitMonthP10": 34, "hitMonthP50": 28, "hitMonthP90": 22,
      "gapAmount": 8200,
      "shortfallPaths": 187
    }
  ],
  "deficitPeakMonths": [ { "month": 7, "paths": 132 } ],
  "deficitTotal": 12480,
  "deficitPaths": 187,
  "medianEndBalance": 42000,
  "needMonthly": 1680,
  "incomeCv": 0.28,
  "emergencyTarget": 10080
}
```

三个达成月份分位是**全样本分位**，未达成路径视为超出推演范围，因此达成比例低于相应分位点时该字段为空值而非数字。若把未达成一律记成推演期末，中位达成月会被系统性地推到最后一个月。

`deficitPeakMonths` 是断流最集中的月份及对应断流路径数，用于回写提示；只报「任一路径断流」的月份在上万条路径下几乎等于全部月份，没有信息量。

### （三）账户分配

```json
{
  "monthly": [],
  "series": [],
  "totals": {},
  "accounts": [ { "code": "safe", "name": "安全底座", "color": "#7A1014" } ],
  "conservationOk": true,
  "priorityOk": true,
  "emergencyTarget": 10080,
  "order": ["safe", "growth", "treat", "compound"]
}
```

`conservationOk` 与 `priorityOk` 是两个自检标志，分别对应 AC-03 与 AC-04。把验收条件做进返回值，可以让验收自测少写一批断言。`order` 由账户表的优先顺序决定，前端配色与此保持一致。

### （四）风险容量

```json
{
  "current": {
    "month": 1,
    "cushionMonths": 3.2,
    "rigidity": 0.41,
    "incomeCv": 0.28,
    "rawScore": 0.58,
    "levelCode": "medium",
    "level": "中",
    "levelCap": 0.40,
    "appetiteCap": 0.60,
    "finalCap": 0.40
  },
  "calendar": [
    { "month": 1, "cushionMonths": 3.2, "pendingAmount": 0, "rigidity": 0.41,
      "levelCode": "medium", "level": "中", "levelCap": 0.40, "appetiteCap": 0.60, "finalCap": 0.40 }
  ],
  "dipMonths": [],
  "cushionMin": 0, "cushionMax": 12,
  "levels": [ { "code": "low", "name": "低", "minCushionMonths": 0, "equityCap": 0.1 } ]
}
```

`finalCap` 即 GR-02 的双约束结果。`calendar` 由推演阶段一次算好，前端不得在渲染时重算。

### （五）二选一方案

```json
{
  "goalId": "g1",
  "goal": { "goalId": "g1", "name": "升学备付金", "dueMonth": 30, "priority": 1, "amount": 30000 },
  "options": [
    {
      "planId": "p1",
      "planType": "compress",
      "title": "……",
      "feasible": true,
      "keepCurrent": false,
      "treatMonthly": 412,
      "deltaAmount": -188,
      "achievedProbability": 0.87,
      "bestProbability": 0.91,
      "delayMonths": 0,
      "medianHitMonth": 28,
      "iterations": 14,
      "message": "……"
    }
  ]
}
```

方案一求的是可行上界而非最小值：预算越低储蓄越多、达成概率单调上升，所以「能达标的最小预算」恒等于零，有意义的是反面——在不放弃按期达成的前提下最多还能花多少体验悦己预算。预算本来就是零时直接判定不可行，不给正数的压缩建议。

无解时 `feasible` 为假，界面按「即便把体验悦己压到零，该目标仍需顺延若干月」呈现，而不是强行给出一个不存在的数字。

### （六）三层解释

```json
{
  "termCode": "max_drawdown",
  "term": "最大回撤",
  "layer1": "……用大白话解释。",
  "layer2": "……说明何种市场环境会触发。",
  "layer3": "……结合您的升学备付金目标，该情形意味着目标将推迟约四个月。",
  "linkedGoalId": "g1",
  "linkedGoalName": "升学备付金",
  "hasNumbers": true,
  "generatedBy": "rule",
  "degraded": false,
  "sources": [ { "docId": "disc_001", "title": "……", "url": "……" } ],
  "disclaimer": "……固定文案，不得改写。",
  "disclaimerTitle": "……",
  "agent": "term_explain",
  "steps": [],
  "elapsedMs": 12
}
```

`layer3` 与 `linkedGoalId`、`hasNumbers` 三者必须自洽：没有关联目标时 `hasNumbers` 必须为假，第三层退化为固定合规文案（对应 GR-05 与 AC-10）。`generatedBy` 取 rule 或 openai_compat，`degraded` 为真表示曾尝试外部模型并回落到本地规则。

## 四、错误码体系

三段式：`<层>-<类别>-<序号>`。层取 P 画像、S 仿真、D 决策、E 解释、C 配置、V 呈现；类别取 01 输入校验、02 数据缺失、03 计算异常、04 资源、05 外部依赖、06 无解或不可行。

| 错误码 | 触发条件 | 用户可见文案 | 处理 |
| --- | --- | --- | --- |
| P-01-01 | 必填字段缺失或取值越界 | 家庭支持必须大于零，请检查该字段 | 高亮具体字段，保留其余输入 |
| P-01-02 | 概率或比率不在零至一之间 | 参与概率需在零到一之间 | 高亮具体字段 |
| P-01-03 | 数量或区间超出允许范围 | 仿真次数与推演时长的乘积不能超过上限，请调低其中一项 | 给出当前上限 |
| P-01-04 | 该填数字的地方填了别的，或该填整数却填了小数 | 到期月份需要填写整数 | 高亮具体字段 |
| P-01-05 | 枚举取值不在字典定义内 | 年级的取值不在允许范围内 | 给出可选值 |
| P-01-06 | 结构不合法 | 目标内容格式不正确 | 阻断 |
| C-01-01 | 写入内容过长或主键为空 | 字段内容过长 | 阻断并指明字段 |
| C-01-02 | 资源类型不支持 | 不支持的资源类型 | 404 |
| C-02-01 | 配置缺失或数据库不可用 | 需要先初始化数据库 | 503 |
| C-02-03 | 目标记录不存在 | 该字典类型不存在或没有条目 | 404 |
| S-03-01 | 推演参数非法 | 推演参数无效，请检查仿真时长与次数 | 阻断 |
| S-03-02 | 数值溢出或出现非有限值 | 当前参数下推演结果异常，请检查金额区间设置 | 阻断并指出可疑字段 |
| S-04-01 | 内存不足 | 推演所需内存不足，可尝试减少仿真次数 | 允许用户下调次数后重试 |
| D-03-01 | 四账户分配不守恒 | 账户分配结果异常，已回退到上一版结果 | 内部自检，界面不暴露细节 |
| D-06-01 | 二选一方案无可行解 | 即便把体验悦己预算降到零，该目标仍需顺延约若干个月 | 按不可行分支呈现，不给虚假数字 |
| E-02-01 | 语料检索无结果 | 暂时没有收录这个说法，可以换一个词试试 | 给出建议词表 |
| E-05-01 | 外部模型不可用 | 已切换到本地解释模式，内容可能略有不同 | 自动降级，不阻断 |
| V-01-01 | 请求内容过大 | 请求内容过大 | 413 |
| V-02-01、V-02-02 | 资源不存在或路径不被允许 | 请求的资源不存在 | 404 |
| V-03-01 | 未捕获的内部异常 | 服务内部出现异常，请重试 | 500，日志只记类型 |

## 五、不变量

以下不变量在每次调用后都应成立，已作为测试的断言集合。

| 编号 | 不变量 | 依据 |
| --- | --- | --- |
| IV-01 | 同一画像与同一种子，两次推演的达成概率完全一致 | AC-13、GR-07 |
| IV-02 | 任意月份的四个账户分配额之和等于当月可用资金 | AC-03 |
| IV-03 | 安全底座未填满时，体验悦己与长期复利的当月分配为零 | AC-04 |
| IV-04 | 安全底座填满之后，体验悦己的分配额大于零 | D-19 |
| IV-05 | 任意账户余额不为负 | GR-03 |
| IV-06 | 每条目标都有对应的达成结果，概率落在零至一之间 | AC-02 |
| IV-07 | 求解过程全程复用同一批随机路径 | GR-07 |
| IV-08 | 解释结果中的目标标识为空时，第三层不含数字 | GR-05、AC-10 |
| IV-09 | 任何输出都附带免责提示 | AC-11 |
| IV-10 | 前端引用的每个文案键、字典类型、配置键、参数键在数据库中真实存在 | 数据一致性检查 |
