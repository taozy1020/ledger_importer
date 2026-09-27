# 部署指南：wheel + uv tool + 标准 Fava

**验证日期：** 2026-09-27  
**本机部署记录：** Fava 已由 1.30.12 升级到 1.30.16；`command -v fava` 仍为 `~/.local/bin/fava`，由 uv tool 管理，Python 3.13。`bean-import-csv` 与 Fava 安装在同一 tool 环境。

本方案保持使用标准 `fava` 命令，不提供自定义 Fava launcher。发布的项目 wheel 是 importer/CLI package；Fava 是同一个 uv tool 环境里的主程序。

## 1. 三个阶段

| 阶段 | 做什么 | Python 代码来自哪里 |
| --- | --- | --- |
| 开发 | `uv sync`、`uv run`、pytest | checkout；editable 安装，改代码可立刻运行。 |
| 构建 | `uv build --wheel` | 从 `src/bean_import` 生成 wheel。 |
| 部署 | 将 wheel 安装到已有/新建的 Fava uv tool 环境 | 已安装的 wheel；不需要 checkout 或 `PYTHONPATH`。 |

这里借用现有 Fava tool，而不是另装一个同名 Fava 或额外包装启动器。uv tool 的隔离环境负责把 Fava、Bean Import、Beancount 和 Beangulp 放在同一 Python 运行环境中。

## 2. 发布前检查

在项目根目录同步锁文件并运行门禁：

```sh
uv sync --group dev --extra fava
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

记录并确认现有 Fava 安装，避免误更新到另一个 Python：

```sh
uv tool list
command -v fava
fava --version
```

本机本次部署前记录为 Fava 1.30.12，入口 `~/.local/bin/fava`，对应 uv 管理的 Python 3.13 tool。升级只针对这个 `fava` uv tool，不修改系统 Python 或其他 uv tools。

## 3. 构建 wheel 和锁定运行依赖

构建发行包：

```sh
uv build --wheel --out-dir dist
```

为可复现安装，从 `uv.lock` 导出 Fava extra 及所有运行时依赖的固定版本/hash：

```sh
uv export \
  --locked \
  --no-dev \
  --extra fava \
  --no-emit-project \
  --format requirements.txt \
  --output-file dist/runtime-requirements.txt
```

当前 wheel 是 `dist/bean_import_prototype-0.1.0-py3-none-any.whl`。Wheel 提供 `bean-import-csv` 命令；不再提供 `bean-import-fava`，Fava 命令由 Fava 自己提供。

## 4. 先在临时 uv tool 环境预演

对现有全局 Fava 做 force install 前，先在 `/tmp` 建隔离工具目录预演相同依赖组合：

```sh
UV_TOOL_DIR=/tmp/fava-primary-check \
UV_TOOL_BIN_DIR=/tmp/fava-primary-check/bin \
uv tool install \
  --python 3.13 \
  --with dist/bean_import_prototype-0.1.0-py3-none-any.whl \
  --with-requirements dist/runtime-requirements.txt \
  --with-executables-from bean-import-prototype \
  fava==1.30.16
```

`fava` 是这个 tool 的主程序；`--with` 加入本地 wheel，`--with-requirements` 固定 Fava/Beancount/Beangulp 及传递依赖，`--with-executables-from bean-import-prototype` 暴露 `bean-import-csv`。

在临时环境验证命令和导入：

```sh
/tmp/fava-primary-check/bin/fava --version
/tmp/fava-primary-check/bin/bean-import-csv --help
head -n 1 /tmp/fava-primary-check/bin/fava
```

Fava shebang 会显示它实际使用的 Python 路径。使用该路径检查 wheel 安装位置，并让 Fava 加载一份 ledger 副本：

```sh
/tmp/fava-primary-check/fava/bin/python -c '
import bean_import
from pathlib import Path
from fava.core import FavaLedger
ledger = FavaLedger(str(Path("/path/to/copied-ledger/main.bean").resolve()))
assert not ledger.ingest.errors, ledger.ingest.errors
print(bean_import.__file__)
'
```

输出的 `bean_import.__file__` 应位于 uv tool 的 `site-packages`，不能指向仓库 `src/`。

## 5. 更新本机已有 Fava tool

临时预演通过后，用同样配置更新已记录的用户级 `fava` tool：

```sh
uv tool install --force \
  --python 3.13 \
  --with "$PWD/dist/bean_import_prototype-0.1.0-py3-none-any.whl" \
  --with-requirements "$PWD/dist/runtime-requirements.txt" \
  --with-executables-from bean-import-prototype \
  fava==1.30.16
```

这是明确的升级操作：`--force` 会替换原 Fava tool 的环境，由锁定配置安装 Fava 1.30.16 和 Bean Import wheel。`~/.local/bin/fava` 命令名保持不变；同时 tool 会安装 `bean-import-csv`。

检查升级结果：

```sh
uv tool list
command -v fava
fava --version
bean-import-csv --help
```

预期 Fava 从 1.30.12 更新到 1.30.16。启动自己的 ledger：

```sh
fava /path/to/my-ledger/main.bean
```

Fava Import 配置应能从同环境中的 `site-packages` 导入 `bean_import`。个人 `import_config.py`、账户树和 mapping 留在个人 ledger 目录；不复制进 wheel。工作区 `examples/fava/main.bean` 是演示 ledger，不要用它替代自己的主账本路径。

## 6. 版本升级与卸载

今后项目发布新版本时，重新构建 wheel、导出对应 `runtime-requirements.txt`，先在临时 uv tool 环境验证，再以相同命令替换 wheel 版本并更新 Fava 版本。更新前备份 ledger 与 mapping。

卸载这个用户级 Fava tool 会同时移除其中的 Bean Import wheel：

```sh
uv tool uninstall fava
```

这不会删除 ledger 文件、账单、manifest 或本地源码 checkout。

## 7. 本次实际部署记录

本次已验证并完成：

1. 升级前 Fava：1.30.12，uv tool 管理，Python 3.13，命令为 `~/.local/bin/fava`。
2. 用 uv.lock 构建 wheel，并导出锁定的 Fava extra 运行依赖。
3. 在临时 tool 环境安装 Fava 1.30.16 + wheel；Fava 能读取不含仓库 `src/` 的 ledger 副本，Import 页面识别 related manifest 并提取三类 entries。
4. 使用同一安装命令更新本机 `fava` uv tool 到 1.30.16；更新后确认 `uv tool list` 同时列出 `fava` 与 `bean-import-csv`，并验证 Import 页面。

Beangulp 依赖声明 GPL-2.0；向其他用户分发前仍需评估整体许可证义务。
