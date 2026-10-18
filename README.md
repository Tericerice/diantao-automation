# diantao — 点淘 / 淘系 Android 自动化任务框架

基于 **Android UIAutomator2 + 多模态视觉/OCR 双通道** 的淘系（点淘、淘宝、天猫、支付宝等）日常任务自动化框架。
核心思路：**原生控件优先、视觉/OCR 兜底、比例坐标保底**，在任务执行过程中只判断「任务是否完成」，异常场景保留现场。

> 本仓库为当前「淘金币双11赚能量」等任务的可运行版本快照。

---

## 一、技术栈

| 层 | 技术 | 用途 |
| --- | --- | --- |
| 设备控制 | **Android UIAutomator2 (u2)** + ADB | 点击、滑动、返回、启动 App、`dump_hierarchy` 控件树、`watch_context` 弹窗监控 |
| 设备连接 | Wi-Fi ADB（`connect_with_retry`） | 断线重连，兼容单机/多机 `--serial` |
| 视觉识别 A（主） | **CodeBuddy 多模态大模型**（`codebuddy_vision.py`） | 语义定位文字/按钮/图标，直接返回物理坐标 `(cx, cy)`，可识别无字图标（关闭 X、返回箭头、红包等） |
| 视觉识别 B（备） | **云端 PaddleOCR v4**（HTTP 服务） | 全屏 OCR 文本块，返回 `{"text","cx","cy","conf"}` |
| 视觉识别 C（兜底） | 屏幕比例坐标 / 固定坐标 | 已知稳定入口的快速点击 |
| 图像处理 | OpenCV (`cv2`) + Pillow (`PIL`) | 截图裁剪、缩放、JPEG 压缩（降低 Token / 带宽） |
| 运行时 | Python 3.10、`uv`（`uv run --no-project`） | 独立环境运行，无需预装依赖 |
| OCR 兼容服务 | FastAPI + Pydantic + PaddleOCR | 把新版 PaddleOCR 结果转换为旧版 `predict_ocr` 契约 |
| 测试 | pytest / unittest | 契约测试、路由测试、计时守卫测试 |

**定位优先级**：`uiautomator2 原生控件 > CodeBuddy 多模态视觉 > 云端 PaddleOCR > 屏幕比例/固定坐标`

---

## 二、URL 与外部服务

| 名称 | 地址 / 标识 | 说明 |
| --- | --- | --- |
| OCR 服务地址 | 环境变量 `DIANTAO_OCR_SERVER_URL` | 云端 PaddleOCR 服务根地址（含 `/predict_ocr` 路径）。**不在代码中硬编码**，运行时注入 |
| OCR 接口 | `POST {DIANTAO_OCR_SERVER_URL}` | 表单字段 `image`（JPEG），返回 `{"code":200,"data":[{"text","score","center":{"x","y"}}]}` |
| OCR 兼容服务（本地/自建） | `tools/ocr_compat_server.py`，`uvicorn ... --port 8888` | 提供 `POST /predict_ocr`、`GET /health` |
| RAG 知识库 | `http://127.0.0.1:9621`（LightRAG，本地） | 开发规范检索，`rag_client.py` / `lightrag_helper.py` |
| 设备 | Wi-Fi ADB，如 `192.168.x.x:<port>` | 真机；脚本内通过 `--serial` 或默认单机选择 |
| 应用包名 | `com.taobao.live`（点淘）、`com.taobao.taobao`（淘宝）、`com.tmall.wireless`（天猫）、`com.eg.android.AlipayGphone`（支付宝） | — |

> 配置示例（PowerShell）：
> ```powershell
> $env:DIANTAO_OCR_SERVER_URL = "http://<your-ocr-host>:8888/predict_ocr"
> ```

---

## 三、OCR / 视觉识别管线

**1. 采集**：`device.screenshot()`（必要时 `adb exec-out screencap -p` 绕过 u2 覆盖层关闭问题）。

**2. 压缩**：截图等比缩放（全屏建议宽 632~720px），存 JPEG（质量 65~85），降低带宽与 Token。

**3. 识别（三级回退）**：
- **CodeBuddy 多模态**：`vision_engine.find_target(img, "去完成")` → `(cx, cy)`；`get_text_blocks()` → 文本块；`classify_screen()` → 页面语义分类；`analyze_guess_price()` → 猜价格决策。
- **云端 PaddleOCR**：`_cloud_ocr(img)` → `[{"text","cx","cy","conf"}]`（置信度 < 0.4 过滤）。
- **比例坐标**：`(0.90*sw, 0.42*sh)` 这类稳定入口。

**4. 坐标换算**：视觉模型常输出相对百分比或压缩图坐标，统一换算回**设备原始分辨率**（1264×2780）后再点击。

**5. 契约兼容**：`utils.get_ocr_text_blocks()` / `find_text_by_paddleocr()` / `paddle_ocr()` 保持旧入参与返回格式，旧脚本零改动即可切换后端。

**WebView 说明**：点淘部分活动页为 Canvas/Themis WebView，`dump_hierarchy` 无文本甚至长时间等待，此时直接走 OCR（`scan()` 中按 Activity 判断，Themis 页面用空树跳过 U2）。

---

## 四、面向对象设计

### 1. `CodeBuddyVision`（`codebuddy_vision.py`）
封装多模态视觉引擎，内部通过子进程调用本地 CodeBuddy CLI（`node codebuddy.js -p ... --tools Read`），把「自然语言目标」转为「屏幕物理坐标」。

| 方法 | 作用 | 返回 |
| --- | --- | --- |
| `find_target(image, target_description, region=None)` | 语义定位任意元素（文字/按钮/图标）中心点 | `(cx, cy)` / `None` |
| `get_text_blocks(image, min_conf=0.5)` | 全量文字块（兼容 PaddleOCR 格式） | `[{"text","cx","cy","conf"}]` |
| `paddle_ocr(image)` | 全图文字拼接 | `str` |
| `classify_screen(image, candidates)` | 页面语义分类 | 分类名 |
| `analyze_guess_price(image)` | 猜价格：识别商品/高低提示/出价框，给出下次出价 | `dict` |
| `_prepare_image_file / _invoke_cli / _extract_json`（私有） | 压缩落盘、调用 CLI、提取 JSON | — |

全局单例 `vision_engine = CodeBuddyVision()`；模块级兼容函数 `codebuddy_ocr / find_text_by_codebuddy / paddle_ocr_cb`。

### 2. `SmartNavigator`（`smart_navigator.py`）
两层状态机导航器：**先异常过滤，再极速定位**。

| 方法 | 作用 |
| --- | --- |
| `capture_screen(prefix)` | 截图并压缩到宽 720 / 质量 65 |
| `query_vision_fast(img_path, prompt)` | 单轮调用视觉模型 |
| `check_and_handle_exceptions()` | 第一层：识别遮罩/弹窗/关闭 X 并自动消除 |
| `locate_target(target_name)` | 第二层：按百分比定位目标 `(cx, cy)` |
| `enter_target(target_name)` | 组合：异常处理 → 定位 → 点击进入；失败保留现场截图 |
| `_load_rules()` | 加载 `nav_rules.json` 素材/规则库 |

### 3. `diantao_1024_auto.py`（2048/1024 数字合成游戏 AI）
经典 OOP 分层，职责单一：

- `Config`：校准参数加载（`load_calibration`）。
- `ADBController`：`screenshot / swipe / tap / get_screen_size / get_device_info` 底层 ADB 操作。
- `BoardRecognizer`：`crop_board / crop_cell / _cloud_ocr / recognize_board / visualize`，把棋盘截图识别为 4×4 数字矩阵（OCR 坐标按缩放比例映射回原图）。
- `GameEngine`：纯函数式棋盘规则（`move_left/right/up/down`、`is_game_over`、`empty_cells`、`max_value`）。
- `GameAI`：`expectimax` 期望最大搜索（`evaluate / decide / decide_fast`）。
- `AutoPlayer`：`calibrate / run_single_game / run / _summary`，串联识别→决策→操作。

### 4. `tools/ocr_compat_contract.py` + `tools/ocr_compat_server.py`（OCR 兼容服务）
- `ocr_compat_contract.py`：纯转换层，`OcrCenter / OcrBlock`（`@dataclass(frozen=True, slots=True)`）、`normalize_paddle_result()` 把新版 PaddleOCR 的 `rec_texts / rec_scores / rec_boxes|dt_polys` 转为旧契约，并用 `_center_from_box()` 兼容「四点框 / 扁平分值」两种坐标格式。
- `ocr_compat_server.py`：FastAPI 应用，`create_app(engine)` 依赖注入 OCR 引擎，提供 `POST /predict_ocr`、`GET /health`；`Protocol`（`PaddleEngineLike / PaddleResultLike`）+ Pydantic 响应模型（`OcrResponse / OcrBlockResponse / CenterResponse`）保证类型契约；`OcrInputError / OcrInferenceError` 区分输入与推理错误。

### 5. 任务执行函数库（`u2_scanner.py` / `utils.py`）
以函数式为主，按「扫描 → 路由 → 执行 → 复核」拆分：
- `scan_page` / `_ocr_nodes` / `u2_find_task_buttons`：扫描任务列表。
- `execute_live_task` / `execute_video_task` / `execute_browse_task`：三类任务执行器（直播每 15s 上滑 `-10s`；视频按次数+最低停留；浏览匀速微滑）。
- `handle_guess_price_game`：猜价格二分/重试。
- `back_to_task` / `wait_completion` / `is_blacklisted`：返回、等待、黑名单。
- `setup_global_watcher`：Android 系统权限弹窗监控（页面弹窗交给 OCR，避免 U2 读 WebView）。

---

## 五、常用入口

| 文件 | 用途 |
| --- | --- |
| `run_taobao_energy.cmd` | **淘金币双11赚能量**入口：`run / enter / scan / auto / browse` |
| `tools/taobao_energy.py` | 赚能量核心：U2+OCR 扫描、三梯队（淘宝→支付宝→其他应用）、逐项浏览并复核 |
| `一键下滑_新.py` / `一键下滑_AI.py` | 打工、睡觉、签到、购物、摇一摇、走路 六轮下滑 |
| `签到赢元宝.py` / `签到赢元宝_AI.py` | 每日签到与里程碑 |
| `打工得体力.py` / `睡觉赚元宝.py` / `走路赚元宝.py` | 对应任务 |
| `点淘鸭钻石任务.py` / `点淘鸭摇一摇.py` / `赚钱卡.py` / `点淘购物赚钱.py` | 对应活动 |
| `全部执行.py` / `任务选择器.py` | 按 `task_config.json` 批量执行 / GUI 勾选 |
| `verify_all_tasks.py` | 端到端验证套件 |

运行示例：
```powershell
# 淘金币双11赚能量（需先设置 DIANTAO_OCR_SERVER_URL）
.\run_taobao_energy.cmd run --repeat 30

# 通用任务
py -3.10 打工得体力.py
```

---

## 六、环境与依赖

- Python 3.10；`uiautomator2`、`opencv-python`、`Pillow`、`requests`、`rapidocr-onnxruntime`（赚能量本地 OCR）、`fastapi`/`uvicorn`（兼容服务）、`pytest`。
- 真机需开启 USB/Wi-Fi 调试；脚本使用 Wi-Fi ADB 地址连接。
- 云端 OCR 通过 `DIANTAO_OCR_SERVER_URL` 注入；未设置时云端 OCR 自动跳过（不会崩溃）。

## 七、安全与边界

- **黑名单**：`下单 / 购买 / 付款 / 充值 / 元宝商城 / 邀请 / 分享 / 蚂蚁庄园 / 饿了么 / 消消乐` 等一律跳过，不产生真实资金支出与社交骚扰。
- **跨应用**：只点系统「仅本次允许 / 打开」，不改长期权限；未安装应用只查看入口后返回，不下载、不安装。
- **风控**：检测到登录/账号异常立即停止；操作间隔拟人化。
- **现场保留**：未知页面/授权/登录障碍保留截图，交由人工检查。
- **凭据**：仓库不含任何 API Key / Token / 密码；OCR 服务地址通过环境变量注入。
