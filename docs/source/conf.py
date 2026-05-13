# Sphinx 文档构建配置。
#
# 这里只保留本项目常用的配置项。完整配置说明见：
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- 路径配置 --------------------------------------------------------------

# 如果 autodoc 需要导入文档目录之外的模块，在这里把对应路径加入 sys.path。
#
import os
import sys

sys.path.insert(0, '../')
sys.path.insert(0, '../../')
sys.path.insert(0, '../../../')


# -- 项目信息 -----------------------------------------------------

project = 'Py Muti-Scrcpy'
copyright = '2021, Lengyue 2022, IanVzs'
author = 'IanVzs'


# -- 通用配置 ---------------------------------------------------

# 在这里添加 Sphinx 扩展模块。
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
    'sphinx.ext.todo',
    'sphinx.ext.napoleon',
    'myst_parser'
]

# 模板目录，路径相对于当前 source 目录。
templates_path = ['_templates']

# Sphinx 自动生成内容使用的语言。
#
# 如果后续使用 gettext 翻译目录，也会使用这个配置。
language = 'zh_CN'

# 查找源文件时需要忽略的路径模式。
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']


# -- HTML 输出配置 -------------------------------------------------

# HTML 文档主题。
#
html_theme = 'alabaster'
html_theme_options = {
    "show_powered_by": False,
    "github_user": "ianvzs",
    "github_repo": "py-muti-scrcpy",
    "github_banner": True,
    "show_related": False,
    "note_bg": "#FFF59C",
}

# 自定义静态文件目录，路径相对于当前 source 目录。
html_static_path = ['_static']


# -- 扩展配置 -------------------------------------------------

# -- todo 扩展配置 ----------------------------------------------

# 为 True 时，`todo` 和 `todoList` 会被输出到文档中。
todo_include_todos = True