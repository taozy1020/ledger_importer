# 人工验收步骤

这份文档给你自己动手验一遍用。每一步都写成「你在界面上做什么、应该看到什么」，不需要读代码。

一共十个场景，从零开始按顺序走完大约 45 分钟。前四个是核心，时间紧就只做这四个。

每一步的期望输出都是我实跑一遍抄下来的，不是推演的，所以数字对不上就是真的有问题。

每个场景都有一行 **✅ 通过条件** 和一行 **❌ 如果不是这样**，后者写明该怀疑哪里，方便你直接告诉我哪一步挂了。

---

## 准备：搭一个一次性的沙盒

不要拿你的真账本做这件事。

```sh
cd /path/to/ledger_importer
uv sync --group dev --extra fava

rm -rf /tmp/verify && mkdir -p /tmp/verify/statements
cp examples/prototype/{ledger.toml,accounts.bean,import_config.py} /tmp/verify/
cp examples/prototype/statements/*.csv /tmp/verify/statements/

cat > /tmp/verify/main.bean <<'EOF'
option "operating_currency" "CNY"

include "accounts.bean"

2000-01-01 custom "fava-option" "import-config" "import_config.py"
2000-01-01 custom "fava-option" "import-dirs" "."
EOF
```

> `main.bean` 里没有 `include "imported.bean"`，所以保存的交易会直接追加到 `main.bean` 末尾，方便你用文本编辑器直接看。真实使用时你会想加上 `insert-entry` 让它们单独成文件。

起 Fava：

```sh
uv run --extra fava fava /tmp/verify/main.bean
```

浏览器打开它提示的地址（默认 `http://127.0.0.1:5000`）。

**每次改了 `src/` 下的代码，都要重启 Fava**；只改账单或 `decisions.jsonl` 不用重启。

---

## 场景 1：第一次导入，系统什么都不替你决定

**你做什么**

1. 左边栏点 **Import**。
2. 看「Importable Files」这一段。
3. 点 `ledger.toml` 那一行右边的 **Continue**（鼠标悬停会显示 `Extract with importer Statement folder statements`）。
4. 弹窗出来后，点 **Next** 一路翻到底，最后一下按钮会变成 **Save**，点它。

**你应该看到什么**

- 可导入的条目**只有 `ledger.toml` 一条**。`statements/` 里那四个 CSV 都列在「Non-importable Files」下面。
- 弹窗标题是 `Entry 1 of 5 (5 to import):`。
- 五笔里有三笔的第二个账户是 `Expenses:Unknown`（咖啡、牛肉面、超市购物）。
- 另外两笔已经自己配平了，不带 `Expenses:Unknown`：`信用卡还款` 是 `Assets:Bank:BOC:Debit` → `Liabilities:CreditCard:BOC`，`零钱提现` 是 `Assets:WeChat:Balance` → `Assets:Bank:BOC:Debit`。它们的 `classification` 是 `structural`。
- 每一笔的 metadata 里都有 `event_id`，一长串十六进制。
- 现在**没有任何一笔带 `candidates`**——日志是空的，没历史可参考。

✅ **通过条件**：5 笔全部保存进 `/tmp/verify/main.bean`；三笔未定账户的落在 `Expenses:Unknown`；两笔转账自己配平了；没有 `candidates`。

❌ **如果不是这样**：如果 CSV 自己也出现在可导入列表里，是 `identify()` 的问题；如果转账那两笔也落到了 `Expenses:Unknown`，是 `normalize` 的跨来源配对没生效。

---

## 场景 2：标签不该存在（这是被实测推翻的一个设计）

**你做什么**

1. 用文本编辑器打开 `/tmp/verify/main.bean`。
2. 搜 `#needs-review`。
3. 回到 Fava，左边栏点 **Journal**，看刚导入的那几笔。

**你应该看到什么**

- 搜不到 `#needs-review`，一个都没有。
- Journal 页面里这些交易没有任何标签。

**为什么要验这个**：早期版本给未定账户的交易打 `#needs-review` 标签。问题是标签是导入那一刻写进账本的，等你把账户改好之后它还在，于是「已处理」和「没处理」混在一起。实测时账本里有 12 笔带标签，实际只有 1 笔还没处理。

正确的筛法是账户本身，下一步就验它。

✅ **通过条件**：账本里完全搜不到 `needs-review`。

❌ **如果不是这样**：`core/render.py` 里的标签逻辑没删干净。

---

## 场景 3：待办清单就是 `Expenses:Unknown`

**你做什么**

1. 左边栏点 **Query**。
2. 在输入框里敲：

   ```
   SELECT count(*) WHERE account = 'Expenses:Unknown'
   ```

3. 点 **Submit**。
4. 再点左边栏 **Income Statement**，找到 `Expenses:Unknown` 那一行，点进去。

**你应该看到什么**

- 查询结果 `count(*)` = **3**。
- 点进 `Expenses:Unknown` 账户页，能看到那三笔交易，金额分别是 32.00、18.00、58.00。

✅ **通过条件**：3 笔，就是场景 1 里那三笔未定的。

---

## 场景 4：改过账户之后，重新导入还认得出来（最重要的一个）

这是实测里最严重的那个 bug，改过之后必须守住。

**你做什么**

1. 回到 **Import** 页，再点一次 **Continue**。
2. 只看弹窗标题，**先不要点 Next**。
3. 看完点右上角 **x** 关掉。

**你应该看到什么**

- 标题是 `Entry 1 of 5 (0 to import):` —— 括号里是 **0**。
- 右上角 `ignore duplicate` 复选框是**勾上的**。

**关键在下一步：改过账户之后再试一次。**

4. 关掉弹窗，左边栏点 **Editor**，把 `main.bean` 里那三笔 `Expenses:Unknown` 改成真实账户：
   - 瑞幸咖啡那笔 → `Expenses:Food:Quick`
   - 兰州拉面那笔 → `Expenses:Food:Quick`
   - 超市那笔先**留着不改**（后面场景 6 要用）
5. 保存（Editor 页面右上角 Save，或 `Ctrl+S`）。
6. 再回 **Import** 页点 **Continue**。

**你应该看到什么**

- 标题**仍然是** `Entry 1 of 5 (0 to import):`。

**为什么要验这个**：beangulp 默认按「账户 + 金额」判重，而审核这件事本身就是在改账户。第一次审核之后，你改过的每一笔都不再像它自己了，于是下个月把账单下载进同一个文件夹，它们会全部重新冒出来让你再审一遍。修复的办法是按 `event_id` 精确判重，这个 id 只由账单原始行算出，你在账本这边怎么改都不影响它。

✅ **通过条件**：改完账户之后，`(0 to import)` 里还是 0。

❌ **如果不是这样**：如果改完变成 `(2 to import)`，说明 `event_id` 判重没生效，去看 `src/bean_import/app/fava.py::mark_known_events`。这是最该抓住的回归。

---

## 场景 5：回收你的选择，并且报告要诚实

**你做什么**

在终端里（Fava 不用关）：

```sh
uv run bean-import-learn --config /tmp/verify/ledger.toml --ledger /tmp/verify/main.bean
```

**你应该看到什么**

```
检查 3 条提议，新结算 3 条，待定 0 条

记录 3 条，已结算 3 条，待定 0 条
提议了账户 0 条：保留 0，被改 0
未提议 3 条：你自己填了 2，仍留未知 1；另有拆分 0
覆盖率 0%（还没有提议过账户），已积累可学习样本 2 条
```

下面还有一张按账户的表。

**这几个数字分别是什么意思**

| 行 | 含义 |
| --- | --- |
| `提议了账户 0 条` | 里程碑 1 从不提议具体账户，所以是 0，这是对的 |
| `你自己填了 2` | 咖啡和牛肉面，你亲手填的，是白送的标注 |
| `仍留未知 1` | 超市那笔你没动 |
| `覆盖率 0%` | 一次都没敢开口，所以不谈命中率 |

**为什么要验这个**：第一版把「系统弃权、你自己填」也算成一次预测，于是里程碑 1 报出「覆盖率 85%、`Expenses:Unknown` 提议 11 修正 11」，看着像一个次次猜错的分类器，其实它一次都没猜过。

✅ **通过条件**：`提议了账户 0 条`、`覆盖率 0%`，并且**报告里不出现「命中率」三个字**。

❌ **如果不是这样**：如果这里就报出了命中率，说明弃权又被算成预测了。

---

## 场景 6：你的修正变成下个月的候选

**你做什么**

1. 造一份「十月账单」，放进同一个文件夹：

   ```sh
   cat > /tmp/verify/statements/wechat_oct.csv <<'EOF'
   微信支付账单明细
   微信昵称：[小明]
   交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号
   2026-10-02 12:15:00,商户消费,老王牛肉面,牛肉面套餐,支出,¥21.00,零钱,支付成功,W88
   2026-10-03 09:05:00,商户消费,瑞幸咖啡,拿铁,支出,¥30.00,零钱,支付成功,W89
   EOF
   ```

2. 回 Fava **Import** 页，点 **Continue**。
3. 翻到 `老王牛肉面` 那一笔，看它的 metadata。

**你应该看到什么**

- 标题变成 `Entry 1 of 7 (2 to import):` —— 七笔里只有两笔是新的。
- `老王牛肉面` 这一笔带上了 `candidates`，值类似 `Expenses:Food:Quick 0.24`。
- 账户**仍然是** `Expenses:Unknown`——候选只提示，不替你决定。
- metadata 里**没有** `candidate_evidence`，也没有 `confidence`。

**为什么要验这个**：两件事。第一，你只教过「兰州拉面」，「老王牛肉面」从没出现过，候选是靠中文二元组分词 + 同平台分类 + 金额相近泛化出来的。第二，写进 metadata 的东西会被 Fava 一起存进账本、**永久留下**，所以默认只留一行候选，不留那句几十字的中文证据。

✅ **通过条件**：`老王牛肉面` 有 `candidates`，账户仍是 `Expenses:Unknown`，没有 `candidate_evidence`。

❌ **如果不是这样**：如果完全没有 `candidates`，先确认场景 5 的回收跑过了（`/tmp/verify/decisions.jsonl` 里应该有 `"outcome"` 字段）；如果出现了 `candidate_evidence`，是 `[advice].metadata` 没起作用。

---

## 场景 7：想留详细证据的时候能留

**你做什么**

1. 编辑 `/tmp/verify/ledger.toml`，把 `[advice]` 里的 `metadata = "short"` 改成 `metadata = "full"`。
2. **重启 Fava**（配置是启动时读的）。
3. 再点一次 **Continue**，看 `老王牛肉面`。

**你应该看到什么**

多出三个字段：

```
confidence:            0.24
candidate_evidence:    1 笔相似记录；最近 2026-09-03；平台分类相同、中午、工作日、金额相当；如 兰州拉面
classification_reason: 未启用语义分类，按金额方向归入未知账户
```

第二句就是「只对这一次审核有用、却会永久留在账本里」的那段散文，第三句是每一行都一模一样的套话。默认 `short` 把这两样都省掉，只留 `candidates`。

验完把它改回 `short`，重启 Fava。

✅ **通过条件**：`full` 下三个字段都在，`short` 下只有 `candidates`，`none` 下一个都没有。

---

## 场景 8：攒够证据之后它敢自己填，并且说得出为什么

**你做什么**

1. 编辑 `/tmp/verify/ledger.toml`，把 `auto_accept_above = 0.0` 改成 `auto_accept_above = 0.3`。
2. **重启 Fava**。
3. 先把场景 6 那两笔审掉：Import → Continue → 给 `老王牛肉面` 填 `Expenses:Food:Delivery`，给 `瑞幸咖啡` 填 `Expenses:Food:Quick` → Save。

   > 这两笔这时候还是 `Expenses:Unknown`：十月的置信度（0.24 / 0.26）还没越过 0.3，系统还不敢开口。

   > 改账户的时候注意：在账户输入框里输完之后按 **Tab** 键。按 Esc 会把输入框清空。

4. 终端里回收一次：

   ```sh
   uv run bean-import-learn --config /tmp/verify/ledger.toml --ledger /tmp/verify/main.bean
   ```

   这一轮应该还是 `提议了账户 0 条`、`你自己填了 4`、`覆盖率 0%`——十月它还没敢开口。

5. 再造一份「十一月账单」：

   ```sh
   cat > /tmp/verify/statements/wechat_nov.csv <<'EOF'
   微信支付账单明细
   微信昵称：[小明]
   交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号
   2026-11-02 09:20:00,商户消费,瑞幸咖啡,冰美式,支出,¥28.00,零钱,支付成功,W95
   2026-11-03 19:40:00,商户消费,海底捞,毛肚,支出,¥240.00,零钱,支付成功,W96
   2026-11-06 12:05:00,商户消费,老王牛肉面,牛肉面,支出,¥22.00,零钱,支付成功,W97
   EOF
   ```

6. Import → Continue，逐条看这三笔。

**你应该看到什么**

标题是 `Entry 1 of 10 (3 to import):`，三笔各不相同：

| 商户 | 账户 | `classification` | `candidates` |
| --- | --- | --- | --- |
| 瑞幸咖啡 | **`Expenses:Food:Quick`**（自动填好了） | `history` | `Expenses:Food:Quick 0.48 \| Expenses:Food:Delivery 0.11` |
| 老王牛肉面 | `Expenses:Unknown` | `unknown` | `Expenses:Food:Delivery 0.29 \| Expenses:Food:Quick 0.26` |
| 海底捞 | `Expenses:Unknown` | `unknown` | 无 |

这三行恰好把阈值的三种情形演全了：

- **瑞幸咖啡**攒了两个月证据，0.48 越过 0.3，系统自己填了，`model_id` 记成 `history`，并且写了一行 `classification_reason` 说明凭什么这么判。
- **老王牛肉面**只有一次修正记录，最高候选 0.29——**差 0.01 没够**。它把候选摆出来给你看，但不替你决定。这一条最能说明闸门是真的在起作用。
- **海底捞**第一次出现，连候选都没有。没见过就不猜。

注意 `classification_reason` 的规则：弃权的理由是每行都一样的套话，默认不写；**模型真的选了某个账户时的理由永远写**，那是你日后回头问「它当时凭什么这么判」的唯一线索。

7. 给 `海底捞` 填 `Expenses:Food:Delivery`，给 `老王牛肉面` 填 `Expenses:Food:Quick`，`瑞幸咖啡` 那笔**保持不动**（表示你认可它的判断），Save。
8. 回收：

```
提议了账户 1 条：保留 1，被改 0
未提议 7 条：你自己填了 6，仍留未知 1；另有拆分 0
覆盖率 12%，命中率 100%
```

系统只开口了一次，而且对了。

✅ **通过条件**：第三个月开始自动填账户；差一点点的不填；没见过的商户连候选都没有；报告开始出现命中率。

❌ **如果不是这样**：如果一直不填，把 `auto_accept_above` 调到 0.2 再试；如果连 `海底捞` 都被填了账户，那是阈值或白名单出问题了，要立刻告诉我。

---

## 场景 8b：推翻它一次，看混淆表

上一步命中率 100% 是因为只提议了一次。再走一个月，故意推翻它。

**你做什么**

1. 造十二月账单：

   ```sh
   cat > /tmp/verify/statements/wechat_dec.csv <<'EOF'
   微信支付账单明细
   微信昵称：[小明]
   交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号
   2026-12-02 09:10:00,商户消费,瑞幸咖啡,燕麦拿铁,支出,¥31.00,零钱,支付成功,W99
   EOF
   ```

2. Import → Continue。这笔应该又被自动填成 `Expenses:Food:Quick`，候选置信度涨到 `0.57`。
3. **把它改成 `Expenses:Food:Delivery`**，Save。
4. 回收。

**你应该看到什么**

```
提议了账户 2 条：保留 1，被改 1
覆盖率 22%，命中率 50%

最常见的误判：
  Expenses:Food:Quick -> Expenses:Food:Delivery × 1
```

✅ **通过条件**：命中率从 100% 掉到 50%，混淆表出现一行，方向是「我们说 Quick，你写了 Delivery」。

❌ **如果不是这样**：如果推翻了它但命中率没变，说明修正没被回收，先确认这一笔的 `event_id` 在账本里还在。

---

## 场景 9：重新导入不许给自己刷分（最隐蔽的一个）

**你做什么**

1. 再点两次 **Continue**，每次都直接 **x** 关掉，不要保存。（这一步在模拟「你又打开看了一眼」。）
2. 再回收一次：

   ```sh
   uv run bean-import-learn --config /tmp/verify/ledger.toml --ledger /tmp/verify/main.bean
   ```

3. 对比这次和上一次的输出。

**你应该看到什么**

- 第一行是 `新结算 0 条`。
- `提议了账户 2 条：保留 1，被改 1` 和 `覆盖率 22%，命中率 50%` 跟场景 8b 结束时**一字不差**。

**为什么要验这个**：重新导入会把整条流水线重跑一遍，而这时候顾问已经从你那次修正里学到了东西，于是它提议的正是你当初选的那个账户——可是没有任何人看过这条提议，因为那一行是 duplicate，不会再送到你眼前。如果让它覆盖原记录，就是在拿已经知道的答案给自己打分，而且**每重新导入一次分数就涨一点**。实测时这让命中率凭空变成 80%，而系统实际上一次都没提议过。

✅ **通过条件**：反复点开导入预览，报告数字纹丝不动。

❌ **如果不是这样**：如果命中率随着你点开次数上涨，`core/journal.py::merge` 的冻结逻辑坏了。这个 bug 方向是**系统性地高估自己**，如果看到了请一定告诉我。

---

## 附加检查：原始账单可以删

这条验的是「学习信号不依赖账单文件」。

```sh
mv /tmp/verify/statements /tmp/verify/statements.gone
uv run bean-import-learn --config /tmp/verify/ledger.toml --ledger /tmp/verify/main.bean
mv /tmp/verify/statements.gone /tmp/verify/statements
```

✅ **通过条件**：回收照常跑完，数字和上一次一致。连接点是账本里的 `event_id`，不是文件。

还有一条反向的：在 **Editor** 里删掉一笔已结算的交易（比如海底捞那笔），再回收，应该多出一行

```
注意：1 条已结算的记录在账本里找不到了。如果是你删掉了这些交易，它们仍在被当作学习样本；确认 --ledger 指向的是完整账本。
```

它不会悄悄抹掉你的决策（你可能只是 `--ledger` 指错了文件），但也不会装作没事。

---

## 收尾

```sh
rm -rf /tmp/verify
```

你自己的真账本从头到尾没被碰过。

---

## 反馈的时候怎么说

挂在哪一步，直接告诉我场景编号和你实际看到的东西就行，例如：

> 场景 4 挂了，改完账户之后标题变成 `Entry 1 of 5 (2 to import)`。

比「判重好像有问题」有用得多。另外这十个场景里有四个（2、4、5、9）对应的是**单元测试全绿但实际用起来是错的**那一类问题，所以如果你发现了新的类似情况，那很可能又是一个只有人在回路里才暴露得出来的 bug。
