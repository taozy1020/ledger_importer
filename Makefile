.DEFAULT_GOAL := help

PYTHON ?= 3.13
FAVA_VERSION ?= 1.30.16
DIST_DIR := dist
RUNTIME_REQUIREMENTS := $(DIST_DIR)/runtime-requirements.txt

.PHONY: help sync check test build export-runtime package install-global fava clean

help: ## 显示可用命令
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_.-]+:.*## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync: ## 同步开发环境及 Fava 依赖
	uv sync --group dev --extra fava

check: ## 运行 Ruff、格式检查、Pyright 和测试
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	uv run pytest

test: ## 仅运行测试
	uv run pytest

build: ## 构建项目 wheel
	uv build --wheel --out-dir $(DIST_DIR)

export-runtime: ## 导出锁定的 Fava 运行时依赖
	uv export --locked --no-dev --extra fava --no-emit-project \
		--format requirements.txt --output-file $(RUNTIME_REQUIREMENTS)

package: build export-runtime ## 构建 wheel 并导出运行时依赖

install-global: package ## 将 Bean Import 安装到全局 Fava tool
	uv tool install --force --python $(PYTHON) \
		--with "$(DIST_DIR)"/bean_import_prototype-*.whl \
		--with-requirements "$(RUNTIME_REQUIREMENTS)" \
		--with-executables-from bean-import-prototype \
		fava==$(FAVA_VERSION)

fava: ## 启动示例 Fava
	uv run fava examples/fava/main.bean

clean: ## 删除构建产物和缓存
	rm -rf $(DIST_DIR) .pytest_cache .ruff_cache