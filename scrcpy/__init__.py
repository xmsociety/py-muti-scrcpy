"""Python Scrcpy Client's core module.

新代码请优先使用拼写正确的 ``MultiClient`` —— ``MutiClient`` 是历史拼写
错误（PyPI 包名 ``muti-scrcpy-client`` 在发布后已无法重命名），保留为别名
以兼容存量调用方。
"""

from .const import *  # noqa: F401,F403
from .core import Client
from .muti_core import Client as MultiClient

# Backwards-compatible alias for existing imports.
MutiClient = MultiClient

__all__ = ["Client", "MultiClient", "MutiClient"]
