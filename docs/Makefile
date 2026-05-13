# Sphinx 文档的最小 Makefile
#

# 可以从命令行设置这些变量；前两个变量也可以从环境变量中读取。
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = source
BUILDDIR      = _build

# 放在最前面，让不带参数的 "make" 等同于 "make help"。
help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

.PHONY: help Makefile

# 兜底目标：把未知目标转发给 Sphinx 的 "make mode"。
# $(O) 是 $(SPHINXOPTS) 的快捷入口。
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
