# Python MutiScrcpy Client
<p>
    <a href="https://pypi.org/project/muti-scrcpy-client/" target="_blank">
        <img src="https://img.shields.io/pypi/v/muti-scrcpy-client" />
    </a>
    <a href="https://github.com/IanVzs/py-muti-scrcpy/blob/main/.github/workflows/ci.yml" target="_blank">
        <img src="https://img.shields.io/github/workflow/status/ianvzs/py-muti-scrcpy/CI" />
    </a>
    <a href="https://app.codecov.io/gh/ianvzs/py-muti-scrcpy" target="_blank">
        <img src="https://img.shields.io/codecov/c/github/ianvzs/py-muti-scrcpy" />
    </a>
    <img src="https://img.shields.io/github/license/ianvzs/py-muti-scrcpy" />
    <a href="https://pepy.tech/project/muti-scrcpy-client" target="_blank">
        <img src="https://pepy.tech/badge/muti-scrcpy-client" />
    </a>
    <a href="https://github.com/Genymobile/scrcpy/releases/tag/v3.3.4" target="_blank">
        <img src="https://img.shields.io/badge/scrcpy-v3.3.4-violet" />
    </a>
</p>

This package allows you to view and control Android devices in realtime.

> **关于 “muti” 拼写**：PyPI 包名 `muti-scrcpy-client` 与类名 `MutiClient` 是项目首次发布时遗留的拼写错误（应为 `multi`）。包名一旦上线无法重命名，因此保留原样；新代码推荐使用拼写正确的别名 `from scrcpy import MultiClient`，旧名 `MutiClient` 仍然可用。

![demo png](https://raw.githubusercontent.com/ianvzs/py-muti-scrcpy/main/demo.png)  

Note: This gif is compressed and experience lower quality than actual.

## How to use

Install the core library if you only need Python access to scrcpy frames and control commands:

```shell
pip install muti-scrcpy-client
```

Install the `ui` extra if you want to run the PySide6 desktop interface:

```shell
pip install "muti-scrcpy-client[ui]"
```

Then start the desktop interface:

```shell
py-muti-scrcpy
```

The `py-muti-scrcpy` command requires the `ui` extra because it imports PySide6.

## Document
Here is the project documentation: [Documentation](https://ianvzs.github.io/py-muti-scrcpy/)
Also, you can check `scrcpy_ui/main.py` for a full functional demo.

## scrcpy v3.3.4 升级记录

项目内置的 `scrcpy-server.jar` 已从 scrcpy v1.20 升级到 [scrcpy v3.3.4](https://github.com/Genymobile/scrcpy/releases/tag/v3.3.4)，用于适配 Android 16 上 `SurfaceControl.createDisplay`、剪贴板监听等服务端 API 变化。

升级时同步做了这些客户端协议调整：

- 替换 `scrcpy/scrcpy-server.jar` 为官方 `scrcpy-server-v3.3.4`。
- 服务端启动参数从 v1.20 的位置参数改为 v3 的 `key=value` 参数。
- 显式关闭 audio：`audio=false`，保留 video/control 通道，避免旧客户端误读额外音频 socket。
- 保留 codec meta 读取视频宽高，关闭 frame meta，让 Python 解码器继续按裸 H.264 数据解码。
- 更新触摸、滚动、剪贴板、屏幕电源等控制消息格式以匹配 v3 协议。
- 增加视频 socket 关闭时的服务端日志读取，便于定位 Android 端 scrcpy-server 崩溃。
- 修复 Qt 显示非连续 `ndarray` 时的 `ndarray is not C-contiguous` 报错。
- 合并原先 `scrcpy_ui/scrcpy/` 重复实现：`MutiClient` 现在直接继承 `Client`，仅保留 `scrcpy/` 一份核心代码。

如果后续继续跟进 scrcpy 新版本，重点检查 `scrcpy/core.py`、`scrcpy/muti_core.py` 与 `scrcpy/control.py` 即可。

## Reference & Appreciation
- Core: [scrcpy](https://github.com/Genymobile/scrcpy)
- Borther: [py-scrcpy-client](https://github.com/leng-yue/py-scrcpy-client/)
- Idea: [py-android-viewer](https://github.com/razumeiko/py-android-viewer)
- CI: [index.py](https://github.com/index-py/index.py)
