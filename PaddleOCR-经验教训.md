# PaddleOCR 踩坑记录 & 开发守则

> 撰写日期：2026-06-30
> 适用项目：自动化大管家 (automation-butler)、芭芭农场类 (coin11-tb)、点淘项目 (diantao)、及其他使用 PaddleOCR 的脚本

---

## 一、血泪教训（4 个坑）

### ❌ 坑1：不要「覆盖」用户已有的正确改动

**现象**：用户已经把 `easyocr` 改成了 `PaddleOCR`，我接手时没读代码直接改回了 easyocr。

**原因**：没看代码就动手，默认「我认为对的」就是对的。

**规则**：
- 任何 Python 脚本的 OCR 引擎已统一为 **PaddleOCR 2.8.1**
- 永远先读 import 和关键函数，确认当前状态再修改
- 不确定就 grep 一下 `import.*ocr` / `easyocr` / `paddleocr`

---

### ❌ 坑2：不要在「假环境」中验证

**现象**：在 Bash 工具中运行 `PaddleOCR init OK` 通过，但实际运行时崩溃。

**原因**：WorkBuddy 的 Bash 工具悄悄设置了 `USERPROFILE=C:\ProgramData\WorkBuddy\users\...`，导致模型下载到「藏起来」的路径。脚本运行时环境变量不同，模型就找不到了。

**规则**：
- 验证脚本时，**必须模拟真实启动条件**
- 环境变量以 Windows 系统默认值为准：`USERPROFILE=C:\Users\用户名`
- 通过启动器运行时，子进程会**继承**启动器的环境变量，要注意
- 验证命令示例（PowerShell）：
  ```powershell
  $env:USERPROFILE = 'C:\Users\星期五'
  $env:HOME = 'C:\Users\星期五'
  & 'C:\Users\星期五\AppData\Local\Programs\Python\Python310\python.exe' -c "..."
  ```

---

### ❌ 坑3：文件「存在」不等于「可用」

**现象**：`Cannot open file inference.pdmodel`，文件确实存在（166KB），但反复重新下载无济于事。

**原因**：第一时间判断「文件损坏」，走了弯路。实际文件格式正常（protobuf），是路径编码问题。

**规则**：
- `Cannot open file` + 文件存在 → **先怀疑路径/编码**，不要急着重新下载
- 验证文件完整性：用 `file` 命令看类型，用 `xxd` / `head -c` 检查文件头
- Windows 上含中文的路径（`C:\Users\星期五\`）是 Paddle 的已知问题

---

### ❌ 坑4：Windows 中文路径 = PaddlePaddle 的「死穴」

**现象**：`C:\Users\星期五\.paddleocr\whl\det\ch\ch_PP-OCRv4_det_infer\inference.pdmodel`，文件存在、格式正确，但 `inference.create_predictor()` 始终报错。

**原因**：PaddlePaddle 的 C++ 底层在 Windows 上使用 `ifstream` 打开文件，**对中文字符路径支持不良**。`星期五` 三个字直接让 Paddle 崩溃。

**规则**：
- Windows 下使用 PaddlePaddle（含 PaddleOCR）时，**模型路径必须全英文**
- 禁止使用默认的 `~/.paddleocr`（会解析到 `C:\Users\中文用户名`）
- 强制方案：在脚本最顶部设置环境变量，**必须在 `from paddleocr import PaddleOCR` 之前**
  ```python
  import os
  os.environ['HOME'] = r'D:\paddleocr_models'       # 英文路径！
  os.environ['USERPROFILE'] = r'D:\paddleocr_models'  # 英文路径！
  from paddleocr import PaddleOCR
  ```

---

## 二、开发守则（必须遵守）

### 守则A：PaddleOCR 配置标准

```python
# ─── 固定写法 ───
import os
os.environ['HOME'] = r'D:\paddleocr_models'
os.environ['USERPROFILE'] = r'D:\paddleocr_models'

from paddleocr import PaddleOCR

ocr = PaddleOCR(
    use_angle_cls=True,   # 必须！启用文字方向分类
    lang='ch',            # 简体中文
    show_log=False,       # 关闭控制台日志
)
```

### 守则B：PaddleOCR 版本锁定

| 包 | 版本 | 说明 |
|----|------|------|
| `paddleocr` | `==2.8.1` | v3.x 依赖 paddlex，模型加载有 bug |
| `paddlepaddle` | `==2.6.2` | 配套 2.x 系列 |
| `paddlex` | **不要安装** | 与 paddleocr 3.x 绑定，废弃状态 |

安装命令：
```bash
pip install paddlepaddle==2.6.2 paddleocr==2.8.1
```

### 守则C：模型缓存管理

- 模型缓存位置（环境变量生效后）：`D:\paddleocr_models\.paddleocr\`
- 缓存包含三个子模型：
  - `det/ch/ch_PP-OCRv4_det_infer/` — 文本检测（~5MB）
  - `rec/ch/ch_PP-OCRv4_rec_infer/` — 文字识别（~11MB）
  - `cls/ch_ppocr_mobile_v2.0_cls_infer/` — 方向分类（~2MB）
- 首次初始化自动下载，后续复用
- 如果模型损坏 → 删除对应目录 → 重新运行脚本自动下载

### 守则D：验证流程（五步法）

```
Step 1: 确认 Python 版本 → 使用正确解释器
Step 2: 确认 pip list → paddleocr==2.8.1, paddlepaddle==2.6.2
Step 3: 模拟真实环境 → 环境变量与启动器一致
Step 4: 测试导入 → `from paddleocr import PaddleOCR`
Step 5: 测试初始化 → `PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)`
```

---

## 三、排查 CheckList

当 `PaddleOCR` 报错时，按此顺序排查：

- [ ] **版本对吗？** → `pip show paddleocr` → 必须 `2.8.1`
- [ ] **paddlex 装了吗？** → `pip show paddlex` → 必须 `not found`
- [ ] **路径有中文吗？** → 查看报错的路径 → 含中文就走守则A
- [ ] **模型文件存在吗？** → 检查 `D:\paddleocr_models\.paddleocr\whl\` 下三个目录
- [ ] **环境变量设了吗？** → 代码顶部是否有 `os.environ['HOME'] = 'D:\\paddleocr_models'`
- [ ] **缓存脏了吗？** → 删除 `.paddleocr` 目录重试
