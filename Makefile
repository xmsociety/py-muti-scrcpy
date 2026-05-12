# 项目常用开发命令。
.PHONY: help code_check format build dist run ui

# 放在最前面，让不带参数的 "make" 等同于 "make help"。
help: ## 显示可用 make 命令及说明
	@echo "可用命令："
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_-]+:.*##/ { printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

code_check: ## 检查代码格式和静态问题，不修改文件
	isort --check --diff scrcpy tests scripts scrcpy_ui workers
	black --check --diff scrcpy tests scripts scrcpy_ui workers
	flake8 --ignore W503,E203,E501,E731,F403,F401 scrcpy tests scripts scrcpy_ui workers --exclude scrcpy_ui/ui_main.py,scrcpy_ui/ui_single.py,scrcpy_ui/ui_screen.py,scrcpy_ui/ui_config_edit.py

format: ## 自动格式化代码，并在格式化后运行 flake8
	isort scrcpy tests scripts scrcpy_ui workers
	black scrcpy tests scripts scrcpy_ui workers
	flake8 --ignore W503,E203,E501,E731,F403,F401 scrcpy tests scripts scrcpy_ui workers --exclude scrcpy_ui/ui_main.py,scrcpy_ui/ui_single.py,scrcpy_ui/ui_screen.py,scrcpy_ui/ui_config_edit.py
build: ## 安装当前项目（含 UI 和开发依赖）到当前 Python 环境
	python -m pip install --upgrade pip
	python -m pip install -e ".[ui,dev]"

dist: ## 构建可发布的 sdist + wheel 到 dist/
	python -m pip install --upgrade build
	python -m build
run: ## 运行本地测试脚本；也可按需切换为桌面入口
	python test.py 
	# py-muti-scrcpy

ui: ## 将 scrcpy_ui 下的 .ui 文件编译为 Python 文件
	cd scrcpy_ui && pyside6-uic single.ui -o ui_single.py
	cd scrcpy_ui && pyside6-uic mainwindow.ui -o ui_main.py
	cd scrcpy_ui && pyside6-uic screen.ui -o ui_screen.py
	cd scrcpy_ui && pyside6-uic config_edit.ui -o ui_config_edit.py
