# Py Muti-Scrcpy 文档

Py Muti-Scrcpy 是一个基于 [scrcpy](https://github.com/Genymobile/scrcpy) 的 Python 客户端封装。它可以通过 ADB 连接 Android 设备，实时接收设备屏幕的 H.264 视频流，将其解码为 OpenCV/Numpy 可处理的图像帧，并通过控制通道发送触摸、按键、文本、滚动等操作。

本项目在基础 scrcpy 客户端能力之外，还提供了面向多设备场景的 `MultiClient`（旧名 `MutiClient` 作为别名保留）、PySide6 桌面界面、worker 进程/线程以及 UDP 图像转发示例，适合用来做设备预览、自动化控制、多机管理和后续的图像处理流程。

## 内容

### 使用指南
```{eval-rst}
.. toctree::
   :maxdepth: 4

   guide
```

### API 参考
```{eval-rst}
.. toctree::
   :maxdepth: 4

   scrcpy
```

## 索引
```{eval-rst}
- :ref:`genindex`

- :ref:`modindex`
- :ref:`search`
```