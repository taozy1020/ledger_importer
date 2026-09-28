# 研究方向：多来源归一化与 LLM 语义分类

**状态：** `dev` 分支的当前研究方向  
**日期：** 2026-09-28

这份文档把后续实现收成一条流水线。0.1 预研里的来源隔离、人工审核和不改主账继续有效。分类主路径改为：确定性代码判断经济活动类型，LLM 只在允许的账户集合里完成语义归类。

当前仓库里的 CSV 映射和 related-batch demo 仍是这条流水线的最小样例，还没有 LLM，也还没有通用的多来源归一化。

## 1. 目标

用户一次性提供一组账单。系统分源解析，把同一笔经济活动收成一条归一化事件，再生成可在 Fava Import 里审核的 Beancount 交易。

```mermaid
flowchart LR
    A[多来源账单批次] --> B[分源提取]
    B --> C[SourceRecord 序列]
    C --> D[跨来源关联与归一化]
    D --> E[AccountingEvent 序列]
    E --> F[确定性事件类型]
    F --> G[LLM 语义分类]
    G --> H[Beancount 渲染]
    H --> I[Fava 审核并写入专用文件]
```

各阶段的产物：

| 阶段 | 输入 | 输出 | 由谁决定 |
| --- | --- | --- | --- |
| 批次 | 一组账单文件和来源配置 | 一个导入批次 | 用户选择的文件 |
| 分源提取 | 单个账单文件 | `SourceRecord` | 该来源的解析器 |
| 归一化 | 多条 `SourceRecord` | `AccountingEvent` 序列 | 金额、日期、渠道证据 |
| 事件类型 | 一条 `AccountingEvent` | expense / income / transfer / refund / repayment / fee / unknown | 账户角色和资金方向 |
| 语义分类 | 未决的费用或收入角色 | 账户建议 | LLM，且必须落在账户允许列表内 |
| 最终输出 | 事件 + 已校验建议 | Beancount Transaction | 渲染器；Fava 负责审核和保存 |

## 2. 多账单批次

一次导入是一个批次，不是 Fava 里多次互不知情的单文件导入。批次包含：

- 一个稳定 `batch_id`
- 一张或多张账单，每张账单有来源类型、来源资金账户、解析配置和文件路径
- 批次根目录；所有账单路径都限制在这个根目录内

Fava Import 按单个文件调用 importer。因此 Fava 看到的是一张批次清单，清单再引用旁边的账单文件。现有 `*.merge.json` 就是这个入口的 demo：`imports/` 里只有清单，`related/` 里的 CSV 不会被当成另一批独立账单。

研究阶段把清单从“银行 + 支付宝”推广为 N 个来源。第一批实现仍可以只有这两种来源，数据契约按 N 个来源设计。

批次级错误直接失败，不产出部分 entries：

- 清单路径越界、文件缺失或超过大小限制
- 某个解析器无法识别列、日期或金额
- 同一来源内出现重复 `source_id`

关联含糊属于事件级问题，在第 4 节单独处理，不把整批废掉。

## 3. 分源提取

每种账单一个适配器。适配器只回答“这张账单里有哪些行”，输出 `SourceRecord`。

```text
SourceRecord
  source_record_id     平台交易号；没有时用来源类型、账户、原始行生成稳定指纹
  source_type          alipay / wechat / bank / credit_card / csv
  source_account       这张账单代表的资金账户
  txn_date             标准日期
  amount               资金账户视角的带符号 Decimal；流出为负，流入为正
  currency
  payee, narration
  source_category      平台自己的分类文本，可为空
  funding_method       余额、银行卡、信用卡等；没有则为空
  raw_fields           原始列，只读
  locator              文件指纹、文件名、行号
  parser_id, version
```

适配器在进入关联之前完成符号规范化。下游看到的金额已经是“该资金账户减少或增加了多少”，不再保留各平台原始的正负约定。

适配器不做这些事：

- 不选择 `Expenses:*` 或 `Income:*`
- 不读取其他账单
- 不删除看起来重复的行

现有 `csv_source.py` 是这个阶段的单文件实现。支付宝、微信和银行的真实导出格式以后各加一个适配器，输出仍是 `SourceRecord`。

## 4. 归一化交易序列

归一化的结果是 `AccountingEvent` 序列。一条事件表示一次经济活动，可以引用一条或多条来源记录。它还不是 Beancount 交易。

```text
AccountingEvent
  event_id             由排序后的 evidence id 和 normalizer 版本生成
  evidence_ids         一条或多条 SourceRecord
  canonical_date
  funding_account      实际进出的资金账户
  amount, currency     资金账户视角的带符号金额
  payee, narration     描述最完整的那条证据上的商户和摘要
  source_category      平台分类，作为后续提示
  field_provenance     每个标准字段来自哪条证据
  link_candidates      没能唯一匹配时保留的候选 id
  flags                ambiguous_link 等审核标记
```

序列按 `canonical_date`、`event_id` 排序，相同输入和相同 normalizer 版本得到相同顺序。

关联只使用这些结构性证据：

- 币种相同
- 规范化后的流出或流入金额精确相等
- 日期落在配置的闭区间窗口内
- 渠道证据吻合，例如支付宝资金方式是银行卡，且银行摘要包含对应渠道词
- 一对一；一条来源记录只进入一条已合并事件

唯一匹配后合并成一条事件：资金账户、日期和金额取清算账户那一侧，商户、摘要和平台分类取叙述更完整的那一侧。两条证据都留在 `evidence_ids` 里。同一笔消费的两行金额只保留一次，禁止相加。

三种关联结果：

| 情况 | 事件 |
| --- | --- |
| 唯一一对一 | 一条事件，引用全部证据 |
| 没有可匹配对象 | 每条来源记录单独成为一条事件 |
| 多候选、多对一或证据冲突 | 不合并；每条记录仍单独成事件，并把候选 id 写入 `link_candidates` |

余额支付没有对应的银行清算行，单独成为以支付宝余额为资金账户的事件。内部转账和信用卡还款在下一阶段识别，不送去按消费分类。

现有 `related_batch.py` 已经验证了“唯一匹配才合并”。它在含糊时让整批 `extract()` 失败。研究方向改为：解析和身份错误失败整批，关联含糊则保留分行事件并打标。这样一次导入里已经清楚的交易仍能进入审核。

## 5. 确定性事件类型

事件类型是一个有限集合，在调用 LLM 之前确定。

| 类型 | 判定依据 | 已知 posting | 留给 LLM 的角色 |
| --- | --- | --- | --- |
| `expense` | 资金账户流出，对手是外部商户 | 资金账户和金额 | `expense_account` |
| `income` | 资金账户流入，对手是外部付款方 | 资金账户和金额 | `income_account` |
| `transfer` | 两侧都是已配置的资产或负债账户 | 两个账户和金额 | 无 |
| `repayment` | 银行卡与信用卡还款记录形成唯一清算关系 | 两个账户和金额 | 无 |
| `refund` | 来源状态或退款关联 id 表明这是一笔冲回 | 资金账户和金额 | 可沿用原交易账户；缺失时再分类 |
| `fee` | 来源把该行标成手续费、利息或垫资费用 | 资金账户和金额 | 对应费用账户 |
| `unknown` | 方向、账户或证据互相冲突 | 不猜测 | 不调用 LLM |

`transfer` 和 `repayment` 的两侧账户都来自账单和用户配置。渲染器直接生成两条资产或负债 posting。LLM 不参与，也不能把它们改成消费。

`unknown` 不生成猜测分录。批次报告列出事件和冲突字段，Fava 预览里不出现一条伪造的支出。

## 6. LLM 语义分类

LLM 是费用账户和收入账户的分类器。它接收一条类型已经确定、角色尚未填上的事件，从用户账本里已经 `open` 的账户中选择一个。

请求只包含这些字段：

```json
{
  "event_id": "…",
  "kind": "expense",
  "role": "expense_account",
  "date": "2026-09-26",
  "amount": "-32.00",
  "currency": "CNY",
  "payee": "瑞幸咖啡",
  "narration": "生椰拿铁",
  "source_category": "餐饮美食",
  "source_types": ["bank", "alipay"],
  "allowed_accounts": ["Expenses:Food", "Expenses:Food:Coffee", "Expenses:Transport"],
  "examples": [
    {"payee": "瑞幸咖啡", "account": "Expenses:Food:Coffee"}
  ]
}
```

`allowed_accounts` 来自 Fava 传给 `extract()` 的现有账本，只保留与角色匹配的已打开账户。`examples` 来自账本里已有交易：优先同名 payee，其次相同平台分类，最多 8 条。账本就是个人分类习惯的记忆，研究阶段不另建规则库。

响应是固定 JSON：

```json
{
  "account": "Expenses:Food:Coffee",
  "uncertain": false,
  "reason": "商户和已有瑞幸交易一致"
}
```

校验全部通过后，建议才能进入渲染：

- `account` 属于这次请求的 `allowed_accounts`
- `kind`、金额、币种、日期和资金账户没有被模型改写
- 响应符合 schema，且没有额外的分录文本

任一校验失败、调用失败或 `uncertain: true` 时，使用用户配置的 suspense 账户，例如 `Expenses:Uncategorized` 或 `Income:Uncategorized`。交易仍然生成，metadata 写明 `classification: suspense` 和原因，用户在 Fava 里改账户。

平台给出的“餐饮美食”只作为 `source_category` 提示。研究阶段不维护一张不断增长的平台分类到 Beancount 账户的表。现有 CSV 原型的 `[categories]` 精确映射继续服务示例和测试；真实账单路径以 LLM 加账户允许列表为准。

调用配置显式给出 OpenAI 兼容 endpoint 和模型名。配置为空表示分类器关闭：原型仍走现有精确映射，缺少映射时保持现在的报错行为。程序不在 endpoint 失败后自动改连另一个公网模型。

温度设为 0。已通过校验的响应按 `模型 + prompt 版本 + 事件规范字段 + 允许账户列表` 做本地缓存，同一次导入重跑直接读缓存。缓存记录模型 id、账户和事件 id，不另存完整账单原文。

## 7. 最终输出

渲染器只消费已经确定的事件和已经校验的建议。简单支出或收入固定为两条 posting：资金账户保留事件金额，分类账户取相反数。转账和还款使用两侧已知账户，不经过分类器。

每条交易保留这些 metadata：

- `event_id`
- `source_id`，多条证据时保留全部 id
- `filename`、`lineno`
- `source_category`
- `classification`：`llm`、`suspense` 或 `structural`
- `model_id`，结构性交易为空

Fava Import 看到的是普通 Beancount Transaction。预览、修改账户、忽略重复项和保存都沿用 Fava。`insert-entry` 继续把结果写入专用文件，例如示例中的 `imported.bean`，主账文件只被 include。

用户在 Fava 里保存后的交易，就是下一次导入的 `examples`。研究阶段不从这次修改自动生成规则草稿。

## 8. 示例

同一批次里有四条来源记录：

| 来源 | 金额 | 对手 | 其他证据 |
| --- | --- | --- | --- |
| 银行 | -32.00 | 支付宝快捷支付 | 日期 D |
| 支付宝 | -32.00 | 瑞幸咖啡 | 资金方式为银行卡，日期 D |
| 银行 | -58.00 | 超市 | 无支付宝渠道证据 |
| 支付宝 | -18.00 | 午餐 | 资金方式为余额 |

归一化后得到三条事件：

1. `expense`，资金账户是银行，金额 -32.00，payee 为瑞幸咖啡。银行行和支付宝银行卡行都在 `evidence_ids` 中。LLM 在费用账户中选择，例如 `Expenses:Food:Coffee`。
2. `expense`，资金账户是银行，金额 -58.00，payee 为超市。没有配对行。LLM 选择费用账户。
3. `expense`，资金账户是支付宝余额，金额 -18.00，payee 为午餐。LLM 选择费用账户。

如果另有一条 -32.00 的银行卡支付宝记录也能对上同一条银行记录，第 1 条不合并。三条来源记录各自成为事件，并在 `link_candidates` 里互相引用。

## 9. 与当前代码的对应

| 现有代码 | 在新流水线中的位置 |
| --- | --- |
| `csv_source.py` | 分源提取的 CSV 适配器 |
| `models.SourceRecord` | 来源契约的起点；研究实现时补上来源类型、资金方式和定位信息 |
| `related_batch.py` | 双来源关联 demo；后续把匹配从直接生成 Transaction 挪到 `AccountingEvent` |
| `mapping.py` | 简单支出/收入的渲染规则；账户来源从固定 category 表扩展为“已校验建议” |
| `importer.py` | Fava 入口；`extract(existing)` 负责提供账户允许列表和历史样例 |
| `examples/fava/import_config.py` | 批次 importer 的注册位置 |

尚未存在、按下面的切片添加的部分：`AccountingEvent`、关联器、事件类型判断、`SemanticClassifier`、建议校验和响应缓存。

## 10. 研究切片

按这个顺序在 `dev` 上做。每一步都有测试，不改变“未启用分类器时，现有 CSV 行为保持不变”。

1. **领域契约。** 增加 `AccountingEvent` 和建议类型。单文件 CSV 先一对一变成事件，再用现有 category 映射渲染。Fava 输出与现在一致。
2. **分类器接口。** 用假的分类器覆盖允许账户、非法账户、不确定和调用失败。非法结果落入 suspense，交易仍平衡。
3. **可选真实 endpoint。** 配置写出后才调用；测试不访问网络。从 `existing` 账本收集允许账户和最多 8 条样例。
4. **关联器独立。** 把银行与支付宝的唯一匹配移到事件层。含糊匹配保留分行事件和 `link_candidates`，解析错误仍然失败整批。
5. **真实样本评估。** 用一份个人支付宝账单和对应银行账单记录：唯一匹配数、含糊匹配数、LLM 建议被接受的比例、suspense 比例、错误账户的类型。样本不进入仓库。

第 5 步的结果决定要不要继续加微信和更多银行适配器。在此之前不实现通用规则语言、规则草稿回放、独立审核 GUI 或 SQLite 工作流。

## 11. 不变量

- 原始行、source id 和文件定位能在最终交易的 metadata 里追回去。
- 金额使用 `Decimal`。适配器先统一符号，关联使用精确金额。
- 同一经济活动的多条证据只形成一个资金金额，不把银行扣款和支付平台记录相加。
- 事件类型和资金 posting 由代码确定。LLM 只填允许列表中的费用或收入账户。
- 分类器未配置时，现有原型继续使用精确 category 映射。
- 校验失败的建议变成 suspense 交易，并在 metadata 中标明。
- 主账文件不是 importer 的写入目标。保存由 Fava 按 `insert-entry` 路由到专用文件。

## 12. 实现前仍要拍板的配置

这些有默认答案，真实样本接入时再按账本调整：

- suspense 账户名由用户配置，并事先在账本中 `open`
- 日期窗口默认沿用 demo 的 2 天
- 历史样例最多 8 条
- 模型温度是 0
- 缓存放在账本目录旁的本地文件，不提交进本仓库
