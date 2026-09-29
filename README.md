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

**未定分类不是死胡同，是人做决定的时刻。** 每次导入都会把当时的情境和提议记进决策日志 `decisions.jsonl`；审核完之后跑 `bean-import-learn`，它按交易 metadata 里的 `event_id` 回到账本，看你最后写了什么，并把结果写回日志。原始账单这时可以删掉——学习信号不在账单里，而在「提议」和「你的决定」的差值里。

下一次遇到相似场合，未定账户的交易会带上候选，例如 `candidates: "Expenses:Food:Quick 0.36"`。账户仍然留空，系统只是把你自己以前的决定摆在眼前。修正的权重明显高于沉默接受，避免系统用自己的输出确认自己。想让它在证据足够时直接填上，把 `[advice].auto_accept_above` 调到 0 以上。

写进 metadata 的东西会被 Fava 一起存进账本、永久留下，所以 `[advice].metadata` 决定账本愿意留多少：`short`（默认）只留一行候选，`full` 连置信度和整句证据一起留，`none` 什么都不留。同样的理由，未定账户的交易**不打标签**——标签是导入那一刻写的，你改完账户之后它还在；筛选待办直接筛 `Expenses:Unknown` 账户。

**里程碑 2（可选）。** 语义分类在 `bean_import.core.ports.SemanticClassifier` 这一个接口后面，实现放在 `bean_import/semantic/`。生活分类说明写在 Markdown skill 里，例如 `examples/prototype/skills/food.md`：按外卖、简餐、买菜、餐厅大餐描述时间和生活场景，而不是按商户名做对照表。导入时抽出这笔交易的星期、钟点、金额和渠道，连同检索到的相似历史一起送给本地模型。配置见 `examples/prototype/ledger-with-model.toml`：加一张 `[semantic]` 表，Ollama 的 OpenAI 兼容地址是 `http://127.0.0.1:11434/v1`，本地模型不需要 API key。删掉这张表就退回里程碑 1。

```sh
uv run bean-import-batch \
  --config examples/prototype/ledger.toml \
  --output /tmp/prototype.bean

uv run bean-import-learn \
  --config examples/prototype/ledger.toml \
  --ledger examples/prototype/main.bean
```

导入不带文件参数就读 `[batch].folder`；也可以显式传文件或另一个文件夹。`bean-import-learn` 会分开统计两件事：**系统提议了账户、你保留或改掉**（这才算覆盖率和命中率），以及**系统弃权、你自己填了一个**（这是白送的标注）。里程碑 1 从不提议，所以它老实报「覆盖率 0%」并告诉你攒下了多少样本，而不是假装自己是个次次猜错的分类器。

把账单反复下载进同一个文件夹是安全的：重复判定按交易 metadata 里的 `event_id` 精确比对，而不是按账户和金额，所以你在 Fava 里改过账户、甚至把一笔拆成几个账户之后，它仍然认得出这是同一笔。

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

## 代码结构

每一层只能依赖它下面的层，这条规则由 `tests/test_architecture.py` 用 AST 检查，不是靠自觉。

| 目录 | 作用 | 依赖 |
| --- | --- | --- |
| `core/` | 领域模型、五个端口协议、归一化、渲染。没有文件 IO、网络和时钟 | 无 |
| `config/` | TOML → `CustomerConfig` | core |
| `sources/` | 账单文件 → `SourceRecord`，含文件头身份识别 | core, config |
| `journal/` | 决策日志：JSONL / 内存 / 空实现 | core |
| `advice/` | 从历史决策给候选账户与置信度 | core |
| `learning/` | 按 `event_id` 从账本回收人工决策，并评分 | core |
| `semantic/` | 可选的模型调用 | core |
| `clock/` | 唯一读系统时间的地方 | core |
| `app/` | 组装：`factory` / `pipeline` / `fava` / `cli` | 全部 |
| `csv_demo/` | 0.1 的 CSV 样例，自成一体 | core |

所有可替换的缝隙集中在 `core/ports.py`，每个协议都有一个简单到可以当 mock 用的实现（`NullAdvisor`、`InMemoryJournal`、`FixedClock` 等）。`import_files(..., components=...)` 接受任意一套实现，因此每个模块都能单独测。

建议从 `doc/prototype-review-guide.md` 开始读；`tests/app/test_learning_loop.py` 是一条完整闭环，从提议一直走到「下次给出候选」。

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
