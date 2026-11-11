# 改动记录：e-diantao-172 复核并纠正一键下滑「元宝中心」进入逻辑

- **任务编号**: `e-diantao-172`
- **关联历史**: `e-diantao-171`, `e-diantao-170`, `e-diantao-169`, `e-diantao-163`, `e-diantao-151`
- **执行平台**: `windows` (`win-371a01cd`)
- **工作区**: `C:\Agent工作空间\worktrees\mcc-e-diantao-172`
- **现役仓**: `C:\My Github Program\diantao`
- **分支**: `trail/172-mcc-e-diantao-172` (基于 master `f02ba72`)

---

## 一、审计与根因分析（Gate / Git / 现场事实）

### 1. 现场日志真实物理根因
- 现场 12:50:57 运行日志显示：第 1 轮（打工）、第 2 轮（睡觉）、第 3 轮（签到）、第 5 轮（摇一摇）接连在 25s 内以 `round_skipped`（入口未找到）结束。
- **用户误判背景**：日志输出 `等待首页稳定 5s，再用 OCR 查找元宝中心…`，随后显示 `✅ 检查确认当前已在元宝中心`，用户误以为系统执行了“OCR 找元宝中心 → 点击元宝中心”导致逻辑出错。
- **真实根因**：代码**根本没有去点击元宝中心**！
  - Commit `f02ba72` (#170) 在 `_enter_yuanbao_center_ocr` 循环开头误加了 `if _is_yuanbao_center_ocr(device):`。
  - 点淘重启（`app_start(DT_APP, stop=True)`）冷启动必然落在点淘首页。
  - 点淘首页常驻有 `"领更多兑红包"`、`"提现"` 等营销挂件。
  - `_is_yuanbao_center_ocr` 的判断条件包含 `"兑红包"`，在首页发生假阳性误判，直接提前退出，跳过了随后的 `device.click` 真实点击！
  - 脚本停留在点淘首页，盲目搜寻元宝中心内部任务入口，因找不到入口而全部 25s 失败跳过。
  - 只有在第 4 轮购物赚钱重试时，偶发未命中首页营销词，真正执行了 `🎯 OCR 点击【元宝中心】@(1140,1227)`，随后立即成功找到了购物入口和【去完成】按钮。

### 2. Gate 与历史提交溯源
- **Gate 裁决查证**：`e-diantao-169`、`170`、`171` 的 review 次数均为 0（未被 Pi 审计过）；历史上没有任何 Gate 裁决要求“禁止点击元宝中心”。
- **提交演进（详见 `history-report.md`）**：
  - `9f6f740`：首次抽出 `_enter_yuanbao_center_ocr`，引入点击 `device.click`（L84）。
  - `d1d5611` (#151)：未确认时中断本轮，保持冷启动点击。
  - `0809fea` (#163)：拦截同款好物，元宝中心逻辑不变。
  - `62aac7e` (#169)：引入 `_ensure_yuanbao_center`（仅用于失败重试防重复点击），冷启动依然 100% 走点击。
  - `f02ba72` (#170)：**错误引入点**，在 `_enter_yuanbao_center_ocr` 开头加入 `_is_yuanbao_center_ocr` 拦截，导致冷启动点击被吃掉。

---

## 二、修复实现

### 1. `一键下滑.py` 最小修复
- **删除循环前置误判**：从 `_enter_yuanbao_center_ocr` 移除循环开头的 `if _is_yuanbao_center_ocr(device):`，确保冷启动回到首页后 100% 必须执行 OCR 检索并点击【元宝中心】。
- **加固中心判定 `_is_yuanbao_center_ocr`**：
  - 若屏幕视野内存在“元宝中心”入口文本，说明仍在首页入口处，直接返回 `False`；
  - 过滤“领更多”、“一键领”等首页营销文案干扰，避免子任务重试或慢渲染复核时将首页误判为元宝中心。
- **原文件备份**：`.scratch/backups/一键下滑.py.bak`。

### 2. `tests/test_swipe_navigation_guard.py`
- 新增 2 项专项场景回归测试：
  - `test_is_yuanbao_center_rejects_home_page_with_marketing_or_center_entry`：验证首页常驻“领更多兑红包”或存在“元宝中心”入口时绝对不误判为中心。
  - `test_enter_yuanbao_center_always_clicks_entry_even_with_home_red_packet`：验证重启点淘后即使首页有营销文本，也必须触发点击元宝中心入口，绝不提前跳过。

---

## 三、验证结果

1. **语法编译检查**：
   ```bash
   rtk python -m py_compile 一键下滑.py
   ```
   - 退出码：0。

2. **专项回归与新增测试**：
   ```bash
   rtk uv run --no-project --with pytest python -m pytest tests/test_swipe_navigation_guard.py tests/test_swipe_guard_regression.py -q -p no:cacheprovider
   ```
   - 结果：**31 passed in 0.13s**（基线 29 项 + 本单新增 2 项全绿）。

3. **全量仓库回归测试**：
   ```bash
   rtk uv run --no-project --with pytest --with numpy --with uiautomator2 --with opencv-python-headless --with pillow --with requests --with python-dotenv --with fastapi --with uvicorn --with httpx --with qrcode --with websockets --with python-multipart python -m pytest tests -q -p no:cacheprovider
   ```
   - 结果：**45 failed, 792 passed, 2 skipped in 54.59s**。
   - 对照基线（45 failed, 790 passed）：通过用例**净增 2 项**，失败用例保持 45 项，**新增失败 0 项**。

---

## 四、安全与回退声明

- **未真机验证声明**：本任务遵守安全边界，未操作或重启正在运行的生产点淘任务，未发真实 ADB 指令；所有结论均基于离线日志还原、历史 Git 审计与 mock 自动化回归验证。
- **回退方式**：
  ```bash
  git checkout -- 一键下滑.py tests/test_swipe_navigation_guard.py
  # 或从备份还原
  cp .scratch/backups/一键下滑.py.bak 一键下滑.py
  ```
