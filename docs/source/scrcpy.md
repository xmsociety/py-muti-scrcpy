# API 参考

本页列出 `scrcpy` 包对外暴露的主要模块、类和常量。自动生成的 API 内容来自源码中的类型、类和函数定义。

## 模块总览

`scrcpy` 包导出基础客户端 `Client`、生成器式多设备客户端 `MutiClient`，以及事件名、按键码、触摸动作、屏幕方向锁定等常量。

```{eval-rst}
.. automodule:: scrcpy
   :members:
   :undoc-members:
   :show-inheritance:
```

## 子模块

### `scrcpy.core` 模块

`scrcpy.core` 提供基础 `Client`。它负责部署 scrcpy 服务端、建立视频和控制连接、解码 H.264 画面流，并通过 `EVENT_INIT`、`EVENT_FRAME` 等事件通知监听器。

```{eval-rst}
.. automodule:: scrcpy.core
   :members:
   :undoc-members:
   :show-inheritance:
```

### `scrcpy.muti_core` 模块

`scrcpy.muti_core` 提供 `MutiClient` 的实现。该客户端更适合 worker 场景：调用 `start()` 后可以逐帧 `yield` 画面，便于在循环中处理多设备图像。

```{eval-rst}
.. automodule:: scrcpy.muti_core
   :members:
   :undoc-members:
   :show-inheritance:
```

### `scrcpy.control` 模块

`scrcpy.control` 提供 `ControlSender`，用于通过控制 socket 向设备发送触摸、按键、文本、滚动、剪贴板、屏幕电源和旋转等控制指令。

```{eval-rst}
.. automodule:: scrcpy.control
   :members:
   :undoc-members:
   :show-inheritance:
```

### `scrcpy.const` 模块

`scrcpy.const` 定义事件名、触摸动作、控制消息类型、Android 按键码、屏幕方向锁定和电源模式等常量。

```{eval-rst}
.. automodule:: scrcpy.const
   :members:
   :undoc-members:
   :show-inheritance:
```
