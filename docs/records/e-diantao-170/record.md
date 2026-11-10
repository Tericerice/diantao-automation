# 改动记录：e-diantao-170 一键下滑现存问题复现与修复

- **任务编号**: `e-diantao-170`
- **关联历史**: `e-diantao-169` (READY), `e-diantao-163`, `e-diantao-151`, `e-diantao-100`
- **执行平台**: `windows` (`win-371a01cd`)
- **工作区**: `C:\Agent工作空间\worktrees\mcc-e-diantao-170`
- **现役仓**: `C:\My Github Program\diantao`
- **分支**: `trail/170-mcc-e-diantao-170` (接管 `mcc/mcc-e-diantao-169` commit `7df4986`)

---

## 一、复现证据与根因分析

通过研读现役代码、`mcc-e-diantao-169` 报告及近期真实运行日志（`.runtime/workbench/diantao-swipe.log`、`diantao-all-in-one.log`），查明 169 离线测试全绿但真机依然报错的核心原因如下：

1. **同包长下滑中标题滚出屏幕被误杀（核心缺陷）**：
   - 点淘的打工、睡觉、签到、走路等页面均运行在 `com.taobao.live.h5.BrowserActivity` / `BrowserUpperActivity` 容器中。
   - 在 230s~240s 的长下滑过程中，页面自然向下滚动，顶部的页面标题（如“打工赚元宝”、“走路赚元宝”）在 1~2 次滑动后必然滚出屏幕上边缘。
   - 169 在 `swipe_browse` 中加入了 `(_is_live_h5_activity(activity) and not marker_after)`。由于 activity 始终是 `BrowserActivity`，一旦标题滚出屏幕（`marker_after is None`），就会被误判为“滑入直播 H5 容器且任务标记消失”，进而主动触发 `_safe_back` 试图恢复，导致正常浏览的页面被自我毁灭式退出。
   - 169 离线测试中 mock 的 OCR 恒定返回包含标题 marker 的静态数据，掩盖了真实页面滚动的物理事实。

2. **误入商品页恢复逻辑二次误退**：
   - `_recover_after_wrong_page` 在从“同款好物”按 Back 返回后，要求视野内必须抓到 `expected_markers`。
   - 但此时页面处于下滑滚动的中间位置，顶部 marker 不在视野内，且任务页本身就是 `BrowserActivity`，导致逻辑判定为“未回到任务页”，进而触发第 2 次 Back 彻底关闭了已恢复的任务页。

3. **进入元宝中心慢渲染无重试与缺少事件契约**：
   - 在 `diantao-all-in-one.log` 中，第 2 轮（睡觉）、第 3 轮（签到）、第 4 轮（购物）连续出现 `⚠️ 未确认回到元宝中心，停止当前导航`。
   - 根因：点击【元宝中心】后，若 H5 首帧渲染缓慢（OCR 耗时仅 0.55s 无元宝中心文本），`handle_yuanbao_live_popups` 立即判负退出，外层未进行延迟复核与重试；且 `run_round` 在 Step 2 失败时直接 `return False`，未输出任何 `round_skipped` 或 `round_failed` 的结构化 JSON 事件，破坏了调度契约。

4. **购物赚钱入口查找缺少滑动推进**：
   - 在 `diantao-swipe.log` 中，第 4 轮连续 5 次 OCR 未找到购物入口。
   - 根因：元宝中心购物卡片通常位于首屏偏下方，`_nav_to_shop` 原地重试 5 次而不进行任何滑动；且仅支持卡片与动作按钮严格在同一行（`<=180px`），不支持直接点击购物卡片本身。

5. **点淘鸭家园右滑手势与重试不匹配**：
   - 第 5 轮摇一摇在点淘鸭家园中使用了 `0.55s` 的慢滑动，容易被 H5/Canvas 识别为拖拽而非翻页；且未找到去摇一摇按钮时缺乏补偿滑动。

---

## 二、修复实现

### 1. `一键下滑.py`
- **错误标记扩充**：`WRONG_PAGE_MARKERS` 补充 `"心仪好物"`、`"长按可搜低价同款"`，提升商品页拦截覆盖度。
- **元宝中心慢渲染保护与重试**：`_enter_yuanbao_center_ocr` 在点击后若首次弹窗检测未通过，等待后复核 `_is_yuanbao_center_ocr`；若仍未通过则执行 `_safe_back` 并进入外层有限重试循环。
- **Step 2 事件契约补齐**：`run_round` 在 `_enter_yuanbao_center_ocr` 未确认时，明确输出 `round_skipped` 事件（`reason="第 X 轮【XXX】元宝中心导航未确认"`），消灭事件盲区。
- **购物入口滑动与卡片自点击支持**：`_nav_to_shop` 在前 2 次未找到入口时，执行微幅上滑露天下方卡片；支持卡片单独命中时的直接点击与区域容差放大（`<=220px`）。
- **摇一摇手势优化**：`_nav_to_yaoyiyao` 改用 `0.3s` 快速横滑手势（与 `点淘鸭摇一摇.py` 对齐），并在未找到按钮时执行补偿横滑。
- **同包下滑标题滚出保护**：`swipe_browse` 明确限定仅在 `activity != expected_activity and _is_live_h5_activity(activity) and not marker_after`（即真正跳入新的直播 H5 容器）时才判错；正常同包下滑中标题滚出屏幕不触发跳页。

### 2. `tests/test_swipe_navigation_guard.py`
- 新增 5 项专项离线回归测试：
  - `test_run_round_emits_round_skipped_when_center_unconfirmed`
  - `test_enter_yuanbao_center_retries_on_slow_h5_render`
  - `test_swipe_browse_continues_when_marker_scrolls_off_screen_in_same_activity`
  - `test_nav_to_shop_swipes_up_to_reveal_lower_card`
  - `test_nav_to_shop_clicks_card_directly_when_no_action_button`

---

## 三、验证结果

1. **专项守卫与回归测试**：
   ```bash
   uv run --no-project --with pytest python -m pytest tests/test_swipe_navigation_guard.py tests/test_swipe_guard_regression.py -q -p no:cacheprovider
   ```
   - 结果：**29 passed in 0.15s**（169 基线 23 项 + 本单新增 5 项 + 既有回归全绿）。

2. **全量仓库回归测试**：
   ```bash
   uv run --no-project --with pytest --with numpy --with uiautomator2 --with opencv-python-headless --with pillow --with requests --with python-dotenv --with fastapi --with uvicorn --with httpx --with qrcode --with websockets --with python-multipart python -m pytest tests -q -p no:cacheprovider
   ```
   - 结果：**45 failed, 790 passed, 2 skipped, 85 subtests passed in 61.39s**。
   - 对照 169 基线（47 failed, 782 passed），通过用例**净增 8 项**，失败用例**净减 2 项**，**新增失败 0 项**。

---

## 四、边界与声明

- **未真机验证声明**：本任务遵守安全边界，未连接真机、未发真实 ADB 点击/滑动；所有改动均基于日志回放、代码审计与离线 mock 回归测试完成。
- **回退方式**：
  ```bash
  git revert <本提交Hash>
  ```
