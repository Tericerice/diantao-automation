# 双任务工作台

此入口只提供两个任务：

1. **淘金币双11能量**：`tools/taobao_energy.py`。
2. **点淘养优惠**：`养优惠.py`。

手机扫码连接、任务启动/停止、实时日志、墨绿/黑/白配色均集成在同一桌面窗口。
扫码连接只用于建立手机连接，不会自动启动任务。两项任务不会同时争抢同一台手机。

## 首次准备

适用环境：Windows 10/11；手机扫码配对需要 Android 11 或以上。

1. 下载完整仓库并解压，安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)。
2. 安装 Google 官方 [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools)。
   将其目录加入 `PATH`，或在根目录 `.env` 中填写 `DIANTAO_ADB_PATH`。
3. 把根目录 `.env.example` 复制为 `.env`，填写自己可用的 `DIANTAO_OCR_SERVER_URL`。
   地址应包含 `/predict_ocr` 路径；接口契约见 [`cloud_ocr.py`](../cloud_ocr.py)。
4. 双击根目录 **`启动工作台.cmd`**。首次启动会建立专用环境并下载依赖，需要联网；后续直接复用。

OCR 服务地址、ADB 路径和配对信息不随仓库分发。没有配置 OCR 服务时，仍可打开工作台和扫码连接，
但启动任务会提示先完成配置。本工作台不安装本地 OCR 大模型，也不要求独立显卡。

## 手机扫码

1. 手机和电脑连接同一 WiFi；访客网络的设备隔离会阻止连接。
2. 手机打开“开发者选项 → 无线调试 → 使用二维码配对设备”。
3. 点击工作台唯一的“扫码连接手机”入口，扫描显示的二维码。
4. 配对和连接成功后，关闭扫码窗口，选择一个任务启动。

不要使用微信或普通相机扫码。手机关闭无线调试、重启或网络变化后，可能需要重新开启无线调试。
若网络不支持 mDNS 发现，可使用 Android 官方的配对码方式在命令行配对，再返回工作台。

## 运行与停止

- 任务日志保存在本机 `.runtime/workbench/`；配色保存在本机 WebView 配置中。
- 任务使用同一个专用 Python 环境，点击任务时不再临时解析、下载依赖。
- 日志中的“运行中”表示进程存在；是否到账仍由各脚本的任务复查结果决定。
- 页面或授权状态不符合脚本要求时，脚本会停止并留下原因，不把未完成误报为成功。
- 点击“停止”会终止该任务的进程树；关闭桌面窗口也会停止它启动的任务。
- 仓库中的原 OCR 脚本仍保留；本次工作台没有切换到尚未完成实测的 AI 识别版本。

## 开发验证

```powershell
uv sync --project workbench --python 3.11
uv run --project workbench python -m pytest tests/test_workbench.py tests/test_yang_youhui.py tests/test_taobao_energy.py tests/test_energy_cloud_ocr.py -q
```

开发时可仅启动本机 Web 预览；不会自动执行手机任务：

```powershell
uv run --project workbench python -m uvicorn workbench.app:app --host 127.0.0.1 --port 9060
```
