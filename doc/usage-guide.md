# 操作指南：用 Fava 导入 CSV

**适用范围：** 当前 CSV 映射原型，Python 3.12+，Beancount 3、Beangulp 0.2、Fava 1.x。  
本指南描述的是项目示例，不代表支付宝/微信原始账单已经支持。

## 1. 启动环境

在项目根目录安装依赖并启动 Fava：

```sh
uv sync --group dev --extra fava
uv run fava examples/fava/main.bean
```

在浏览器打开 [http://127.0.0.1:5000](http://127.0.0.1:5000)。Fava 使用示例账本、账户定义和 importer 配置；本地操作仅作用于 `examples/fava/`，不要换成个人主账本来第一次试验。

开发调试使用 `uv run fava ...`。部署时用 `uv tool install --with fava --with-executables-from fava <wheel>` 安装，然后运行标准命令 `fava examples/fava/main.bean`。稳定部署流程见根目录 README 的“Build 与部署”。

## 2. 在 Fava 中审核

1. 打开侧栏的“导入”。示例账单位于 `examples/fava/imports/transactions.csv`。Bank 与 Wallet 两个 profile 使用相同 CSV schema，因此 Fava 会识别出两个候选。
2. 文件条目下会显示 `Bank CSV profile` 与 `Wallet CSV profile` 两个选项。按其中一个的“导出”（Fava 对 Extract 的中文翻译）开始提取；用户每次只选一个，Fava 不会自动把两种结果都导入。单击文件名只会显示原始文件预览。
3. 提取窗口逐条显示交易，可检查/修改日期、payee、narration、账户、金额和 metadata；底部显示对应 CSV 原始行。用“下一个”/“上一个”检查批次，默认启用“忽略重复项”。
4. 确认后按“保存”。Fava 显示 `Stored N entries.`，并将 entries 插入 Fava 配置所指定的 Beancount 文件。
5. 打开“日记账”检查交易，再查看 `examples/fava/imported.bean` 确认写入目标。

两个 profile 使用相同 CSV schema 是刻意的：它让 Fava 同时列出两个候选。选择 Bank profile 时，资金账户和已有交易一致，Beangulp 默认相似度比较器会标记重复；预览里的“忽略重复项”默认启用，保存时该记录会被跳过。选择 Wallet profile 时资金账户不同，即便日期和金额相同，也不会因此自动与银行交易合并。Wallet 是用于观察映射差异的教学 profile，不表示同一笔消费应该重复入账。

Fava 对同一文件列出多个 importer 时，由用户选择一个。Beangulp CLI 的 `identify()` helper 遇到多匹配会报歧义，不会随机挑选或自动全跑；参见 `tests/test_importer.py::test_two_profiles_can_match_but_cli_rejects_the_ambiguity`。

当前工作区的 `examples/fava/imported.bean` **已经包含两笔演示交易**（咖啡、地铁），这是刚才实际走完 Fava 操作后的状态。再次导入时 Fava/Beangulp 会尝试标记重复项；如果要从干净状态重演，先把示例目录复制到临时位置，再只编辑副本中的 `fava/imported.bean`，保留 `fava-option "insert-entry"` 行并移除其中的交易，绝不要为了重演清空工作区里已有的文件。

## 2.1 Related files：银行账单 + 支付宝明细

这是用于观察多文件安全合并的独立演示，不要求手工逐个上传 sidecar：

1. 在同一个 Import 页面选择 `merge-demo.merge.json` 的 importer `Bank + Alipay related batch`。
2. Manifest 指向 `examples/fava/related/bank.csv` 和 `examples/fava/related/alipay.csv`。这两个 sidecar 放在 Fava `import-dirs` 外，因此不会被当作两份独立账单导入。
3. 预览应有 3 条：支付宝关键词银行行与支付宝银行卡明细合并为一条（使用银行账户、支付宝商户/摘要/分类，保留双方 source ID）；普通银行购物行独立保留；支付宝余额午餐独立记入 `Assets:Alipay:Balance`。
4. 合并项日期取银行日期，支付宝日期允许相差最多 2 天；金额和币种必须完全相同。可查看来源 metadata 和 Fava 原始来源预览，再决定是否保存。

**安全规则：** 每条银行渠道支付宝明细必须找到唯一的一行银行记录。找不到、同时匹配多行、多个支付宝明细争用同一银行记录、source ID 重复、资金方式未知或 manifest 路径越出示例根目录时，整个 batch 报错，不返回部分交易。不要为让导入“成功”而放宽金额条件；应先核实账单语义，再调整配置/算法。

想试验异常路径时，在副本目录中修改 bank/alipay CSV：删去对应银行行可触发“无匹配”；复制同金额、近日期且带支付宝关键词的银行行可触发“多匹配”。错误会阻止 Fava 生成可保存的 entries。现有工作区示例账单不要直接改坏。

## 3. CSV 映射的含义

示例 CSV 默认列为 `id,date,amount,payee,narration,category`，映射在 `examples/mapping.toml`：

- `amount` 是银行账户视角的带符号金额：支出负数、收入正数。
- 银行 posting 保留输入符号，费用/收入 posting 取反，因此两条 posting 的总和为零。
- `category` 必须在 `[categories]` 有精确映射；未知类别会报错，不会猜账户。
- `id` 作为 Beancount metadata `source_id` 保留；没有 ID 时以原始行内容生成稳定回退 hash。
- `__source__` 向 Fava 预览提供原始行；Fava 保存时会移除以下划线开头的临时 metadata。

示例中的 `Assets:Bank:Checking`、`Expenses:*`、`Income:*` 已在 `examples/fava/accounts.bean` 打开。CLI 输出 `/tmp/imported.bean` 是交易片段；直接 `bean-check` 片段会因账户尚未 open 而报错，校验时要把片段放进包含账户定义的 ledger 中。

## 4. 不修改账本的 CLI 预览

若只想观察映射结果而不进入 Fava：

```sh
uv run bean-import-csv \
  --config examples/mapping.toml \
  examples/transactions.csv \
  /tmp/imported.bean
```

这条路径直接调用相同的 `read_records()` 和 `map_record()`，只写输出文件，不写 Fava ledger。

## 5. Fava 文件路由

`examples/fava/main.bean` include `accounts.bean` 和 `imported.bean`。`imported.bean` 中的 `fava-option "insert-entry"` 用正则匹配 posting 账户；**选项写在哪个 Beancount 文件，Fava 就将匹配的 entry 插入哪个文件**。因此该选项放在专用的 `imported.bean` 中，主 `main.bean` 不会被插入交易。

操作后检查两点：`main.bean` 仍只含 include/configuration，交易出现在 `imported.bean`。若改变 Fava 选项语法，先看当前安装版本的 Fava 内置 Import 帮助。

## 6. 常见问题

| 现象 | 检查 |
| --- | --- |
| 文件没有出现在可导入列表 | 检查 `import-dirs` 路径、CSV header 是否有配置中的列、`CONFIG` 是否包含 importer。 |
| 提取报日期或金额错误 | 当前日期要求 ISO `YYYY-MM-DD`；金额须是 `Decimal` 可解析的点号格式，不含千位分隔符。 |
| 未知 category | 在 `examples/mapping.toml` 的 `[categories]` 增加精确映射，账户应与账本账户树一致。 |
| `bean-check` 报 unknown account | 被检查的文件是片段且未 include `accounts.bean`；将输出放入示例完整 ledger 校验。 |
| 重复导入似乎未被拦截 | 当前使用 Beangulp 默认的启发式去重，不是按 `source_id` 做精确幂等。检查预览里的重复标记；精确 source-ID 去重仍是后续实现任务。 |
| 保存后交易出现在意外文件 | 检查 `insert-entry` 的账户正则及选项所在的 Beancount 文件；匹配目标来自 Fava 选项，而不是 CSV importer。 |
