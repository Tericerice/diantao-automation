# diantao (CodeBuddy 多模态全能改造版)

面向点淘与淘系 Android 自动化任务的多模态视觉驱动版本。  
**核心特性**：全面废弃传统本地/云端 OCR（PaddleOCR、EasyOCR、ddddocr），改由 **CodeBuddy 多模态大模型**（Flash、DeepSeek、V4.1、Claude Sonnet）直接对手机界面截屏进行语义理解、智能文字定位与图标识别。

---

## 一、改造核心亮点

1. **零本地 OCR 依赖，无中文路径报错**：
   - 彻底解决 Windows 中文路径下 PaddlePaddle C++ 底层崩溃、模型加载失败及环境冲突问题。
2. **多模态全能支持**：
   - **Flash（默认，极速）**：`glm-5.3-flash` / `gemini-3.7-flash`，快速提取屏幕所有文字块及物理中心点 `(cx, cy)`。
   - **DeepSeek（复杂逻辑与决策）**：`deepseek-v4-flash`，用于“猜价格”商品的数学二分策略、活动规则深度分析。
   - **V4.1 / Claude Sonnet（高阶视觉）**：`custom-local:antigravity/claude-sonnet-4-6`，复杂嵌套弹窗与图文辨析。
3. **语义图标定位能力（超越传统 OCR）**：
   - 能够准确定位无字图标（如右上角关闭“X”、返回箭头、气泡图标、直播间交互项），无需繁琐且易失效的 OpenCV 模板匹配。
4. **100% 契约兼容**：
   - `utils.get_ocr_text_blocks()`、`utils.find_text_by_paddleocr()`、`utils.paddle_ocr()` 完全兼容原有入参和返回格式，旧有业务脚本无感平滑升级。

---

## 二、定位优先级

`uiautomator2 原生控件 > CodeBuddy 多模态视觉定位 > 屏幕比例自适应坐标`

---

## 三、常用入口

| 文件或目录 | 用途 |
| --- | --- |
| `codebuddy_vision.py` | **CodeBuddy 多模态视觉驱动核心模块**（提供文字查找、按钮定位、状态分类、猜价格决策） |
| `赚钱卡.py` | **赚钱卡三大核心活动全自动化**（1. 直播 2. 浏览 3. 猜价格） |
| `任务选择器.py` | 图形界面任务选择器（勾选保存执行项） |
| `全部执行.py` | 按既有编排运行所有已勾选的多模态任务 |
| `签到赢元宝.py` | 每日签到与元宝活动流转 |
| `元宝中心小任务.py` | 元宝中心列表小任务遍历执行 |
| `打工得体力.py`、`打工加速.py` | 淘金币/打工相关体力活动 |
| `点淘购物赚钱.py`、`点淘鸭钻石任务.py` | 购物浏览与钻石活动 |
| `verify_all_tasks.py` | 端到端全功能多模态验证套件 |
| `utils.py` | 统一工具库（已全面升级为 CodeBuddy 多模态驱动） |
| `u2_scanner.py` | uiautomator2 页面扫描与多模态状态路由 |
| `task_config.json` | 自动化任务配置与启停清单 |

---

## 四、核心脚本调用示例

### 1. 运行点淘赚钱卡自动化（直播、浏览、猜价格）
```bash
python 赚钱卡.py
```

### 2. 运行全部已勾选日常任务
```bash
python 全部执行.py
```

### 3. 多模态视觉引擎单例调用
```python
from codebuddy_vision import vision_engine

# 精准寻找指定按钮或图标坐标 (cx, cy)
pos = vision_engine.find_target(screenshot, "去完成")
if pos:
    device.click(pos[0], pos[1])

# 语义判断当前页面状态
category = vision_engine.classify_screen(screenshot, ["点淘主页", "元宝中心", "直播间", "浏览页"])
```

### 4. 运行端到端验证
```bash
python verify_all_tasks.py
```

---

## 五、环境与安全说明

- 本机 Python 推荐路径：`C:\Users\星期五\AppData\Local\Programs\Python\Python310\python.exe`
- CodeBuddy 引擎调用通过工作区内部临时截图管理，避免无关路径权限泄露。
- 任务执行严格保留原有黑名单机制，拦截非预期的充值、购买或邀请动作。
