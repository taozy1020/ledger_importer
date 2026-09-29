# Bean Import Prototype

一份用于学习和验证边界的本地优先 CSV → Beancount 原型。当前版本是实验性的 `v0.1.0-alpha`：包含单 CSV 映射和银行+支付宝 related-file batch demo；样例使用约定字段，不是支付宝/银行真实账单解析器，也不做模糊匹配。

项目重点是可追溯的来源记录、保守的跨文件匹配和 Fava 审核流程。当前代码还没有 LLM 分类和真实平台账单适配。`dev` 分支的后续路线见 [研究方向](doc/research-direction.md)：多来源账单先归一化为会计事件，事件类型由确定性代码判断，费用和收入账户由受限 LLM 建议。

## 环境

项目用 `uv` 管理 Python 与锁文件。需要 Python 3.12 或更新版本。

```sh
uv sync --group dev --extra fava
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

日常操作也可以直接使用 Make：

```sh
make help             # 查看所有目标
make sync             # 同步开发环境
make check            # 运行完整质量检查
make fava             # 启动示例 Fava
make install-global   # 构建并安装到全局 Fava tool
```

`beangulp` 使用 GPL-2.0。项目目前是研究原型，分发前需确认整体许可证策略。

## 许可证

本项目自有代码采用 Apache-2.0，见 [LICENSE](LICENSE)。Beancount 和 Beangulp 是运行时依赖，分别按照各自许可证分发；第三方依赖说明见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。项目名称和标识不随代码许可证授予商标权。

## 开发态启动 Fava

`uv sync` 在开发环境以 editable 方式安装本项目；使用 `uv run` 会选中项目虚拟环境中的 Fava、Beancount 和 Beangulp：

```sh
uv run fava examples/fava/main.bean
```

`uv run` 是开发入口，不是部署要求。系统 Fava 或编辑器插件如果在另一个 Python 环境启动，就看不到项目 `.venv` 中安装的包。

## Build 与部署

项目用 Hatchling 构建标准 wheel；部署时将 wheel 安装进现有 Fava uv tool 环境：

```sh
uv build --wheel --out-dir dist
uv export --locked --no-dev --extra fava --no-emit-project --format requirements.txt --output-file dist/runtime-requirements.txt
uv tool install --force --python 3.13 \
  --with "$PWD/dist/bean_import_prototype-0.1.0-py3-none-any.whl" \
  --with-requirements "$PWD/dist/runtime-requirements.txt" \
  --with-executables-from bean-import-prototype \
  fava==1.30.16
fava /path/to/my-ledger/main.bean
```

这会更新现有的 Fava tool：Fava 自带 `fava` 命令，Bean Import wheel 安装在同一个 Python 环境，并暴露 `bean-import-csv`。不会额外安装第二份 Fava，也不需要自定义 launcher。账本、`import_config.py` 和个人 mapping 仍保存在用户自己的 ledger 目录。

安装后检查：

```sh
uv tool list
command -v fava
fava --version
bean-import-csv --help
```

`examples/fava/import_config.py` 直接导入已安装的 `bean_import`。如果 Fava tool 使用另一个 Python 版本，请相应调整 `--python` 与 Fava 版本，并在目标环境验证 runtime requirements。

## 学习资料

- [部署指南](doc/deployment-guide.md)：从 wheel 构建到 uv tool 安装，并区分简单安装与锁定依赖部署。
- [Fava 操作指南](doc/usage-guide.md)：从上传/识别到审核和保存。
- [代码阅读指南](doc/code-reading-guide.md)：按文件、调用链和金额语义理解原型。
- [公开文档索引](doc/README.md)：产品、架构、部署和使用说明。
- [研究方向](doc/research-direction.md)：多来源归一化与 LLM 语义分类。
- [平台账单原型审阅指引](doc/prototype-review-guide.md)：原型的设计说明与逐阶段代码导读。

## 平台账单原型

微信、支付宝手机账单，以及中行借记卡/信用卡的表格适配器在 `examples/prototype/`。每个客户使用自己的 `ledger.toml`。

**账单放一个文件夹就行。** `[batch].folder` 指向下载目录，导入时读这个目录里所有能识别的账单，PDF、压缩包和其他文件会被跳过并列出来。配置平时不用改。

**一个平台账号一条 `[[sources]]`。** 有两个微信号就写两条，`identity` 填账单文件头里的身份：微信的 `微信昵称`、支付宝的 `支付宝账户` 或 `姓名`、中行的卡号或 `客户姓名`。程序从文件头读出身份再决定这份账单属于哪个账户；匹配不上或同时匹配多个就整批失败，不会把两个钱包混成一个。同一来源只配置一个账号时可以不写 `identity`。

**`[[cards]]` 写完整卡号。** 账单里只会出现后四位，所以匹配用后四位；两张卡后四位相同时配置直接报错，因为这种情况无法从账单里分辨。

**里程碑 1（当前默认，不需要模型）。** 配对、方向、转账和信用卡还款全部由确定性代码判断。分类无法从账单本身确定时，按金额方向落到 `[unknown]` 配置的账户：支出进 `Expenses:Unknown`，收入进 `Income:Unknown`，交易照常平衡，在 Fava 里改账户。`examples/prototype/ledger.toml` 就是这一层的完整配置。

**里程碑 2（可选）。** 语义分类在 `bean_import.classify.SemanticClassifier` 这一个接口后面，实现放在 `bean_import/semantic/`。生活分类说明写在 Markdown skill 里，例如 `examples/prototype/skills/food.md`：按外卖、简餐、买菜、餐厅大餐描述时间和生活场景，而不是按商户名做对照表。导入时抽出这笔交易的星期、钟点、金额和渠道，并从已有账本归纳每个账户的记忆，和 skill 一起送给本地模型。配置见 `examples/prototype/ledger-with-model.toml`：加一张 `[semantic]` 表，Ollama 的 OpenAI 兼容地址是 `http://127.0.0.1:11434/v1`，本地模型不需要 API key。删掉这张表就退回里程碑 1。

```sh
uv run bean-import-batch \
  --config examples/prototype/ledger.toml \
  --output /tmp/prototype.bean
```

不带文件参数就导入 `[batch].folder`；也可以显式传文件或另一个文件夹。

Fava 示例：

```sh
uv run fava examples/prototype/main.bean
```

导入页只有一个条目，就是 `ledger.toml` 本身，名字是 `Statement folder statements`。选它会导入整个文件夹：支付宝银行卡消费和中行借记卡清算合并成一笔，信用卡还款和微信提现识别为结构性交易，不送给分类器。

## 跑通最小例子

```sh
uv run bean-import-csv \
  --config examples/mapping.toml \
  examples/transactions.csv \
  /tmp/imported.bean
```

例子把 CSV 的 `amount` 当作银行账户视角的带符号金额：支出为负，收入为正。映射器对每条记录生成两条 posting：银行账户 posting 保留 CSV 金额，类别对应的费用/收入 posting 取相反数，因此分录平衡。类别没有映射时会报错，不会猜账户。CSV 导出的 `.bean` 是分录片段，目标账户需要已在账本中 `open`；独立运行 `bean-check` 时需提供相应账户定义。

## 核心代码怎么走

- `models.py` 定义来源行 `SourceRecord`，原始 CSV 字段也一并保留。
- `csv_source.py` 只负责文件解析、字段校验、日期/金额转换和稳定来源 ID，不负责分类或会计决策。
- `mapping.py` 是核心纯转换：`SourceRecord + CsvImportConfig -> Beancount Transaction`。金额使用 `Decimal`，并保留来源 ID、文件行和原始内容供追溯。
- `importer.py` 把上述逻辑包装成 Beangulp importer 接口，因此可以由 Fava Import 调用。
- `related_batch.py` 由一个 JSON manifest 引用两份 CSV；只在一对一证据充分时合并银行与支付宝记录，并单独导入余额支付。
- `cli.py` 提供独立、可重复运行的 CSV 到 `.bean` 转换入口，便于观察输出和做测试。

建议按 `tests/test_mapping.py` 里的支出/收入例子跟读金额符号；测试刻意覆盖未知类别拒绝推测。

## CSV 字段与映射

默认列名为 `id,date,amount,payee,narration,category`，列名可在 `examples/mapping.toml` 的 `[columns]` 中改。日期使用 ISO `YYYY-MM-DD`；金额使用点号小数，不含千位分隔符。没有 `id` 时，程序用整行原始字段生成 SHA-256 回退 ID。

`[categories]` 把输入类别精确映射到账户。用户需确保目标账户已经在 ledger 中打开，并为收入类别映射到 `Income:*` 账户。

## Fava Import

`examples/fava/main.bean` 是最小账本，`import_config.py` 暴露 Beangulp 所需的 `CONFIG` 和 `HOOKS`，并注册 Bank/Wallet profiles 与 related-batch importer。`imported.bean` 是专用写入文件。要试用：

1. 从项目根目录运行 `uv run fava examples/fava/main.bean`。
2. `transactions.csv` 同时匹配 Bank/Wallet profiles，可观察多候选选择和默认重复标记。
3. `merge-demo.merge.json` 选择 `Bank + Alipay related batch`。它读取 `related/bank.csv` 与 `related/alipay.csv`，演示银行消费富化、普通银行消费保留和支付宝余额独立入账。
4. `insert-entry` 是匹配账户名的正则；Fava 把该选项所在文件作为目标，所以示例把它放在已 include 的 `imported.bean` 中。

批次只在银行记录包含支付宝关键词，且金额完全一致、日期在配置窗口内并唯一匹配时合并。未匹配/多匹配的银行卡支付宝记录、未知支付方式、重复 source ID 或 sidecar 路径越界都会拒绝整批，不输出部分 entries。示例窗口为两天，金额使用精确 `Decimal` 匹配。

Fava/Beangulp 的具体选项语法随所用版本查看 Fava 自带 Import 帮助。Fava Import 适合审核已生成的 Beancount entries，不负责跨来源事件关联或在 UI 中浏览所有原始来源字段。

## 当前明确不做

- 账单 PDF、EML 容器和 OCR。微信、支付宝手机 CSV，以及中行表格 CSV 已有原型。
- 跨平台模糊匹配、退款/转账/拆分事件推断。
- 通用规则语言、规则草稿回放，以及由模型直接提交主账。LLM 语义分类是研究方向，尚未在当前代码中实现。

后续实现应逐个替换 adapter/mapping/provider，而不是把 Beancount directive 当作内部原始数据模型。
