# Trail e-diantao-170 实施记录：一键下滑现存问题复现与修复

- **任务编号**: `e-diantao-170`
- **任务标题**: `[diantao][win] 一键下滑现存问题复现与修复（AGY Worker 切换后执行）`
- **执行平台**: `windows` (`win-371a01cd`)
- **执行 Worktree**: `C:\Agent工作空间\worktrees\mcc-e-diantao-170`
- **基线分支/Commit**: `mcc/mcc-e-diantao-169` (`7df49863fface0f76487feeb71e21789d38658c3`)
- **验证结论**: 离线全量及针对性回归通过（未进行真机操作，保持客观）

---

## 一、问题复现证据与根因分析

在 `e-diantao-169` 完成后，依据日志回放与逻辑审校，一键下滑仍存在以下致瘫性缺陷：

1. **同包下滑过程中的误拦截（核心根因）**：
   - 现象：在 `BrowserActivity`（所有打工/睡觉/签到/走路的基底 H5 容器）中下滑浏览数次后，顶部任务 Marker（如“打工赚元宝”、“睡觉赚元宝”）因正常下滑自然滚出屏幕。
   - 根因：原校验逻辑使用 `activity != expected_activity and _is_live_h5_activity(activity) and not marker_after`。当页面自然滚动或点淘同包在 `BrowserActivity` 与 `BrowserUpperActivity` 之间发生常态层级切换时，marker 不在当前视口即被错误定性为“滑入直播 H5 容器且任务标记消失”，触发频繁 `_safe_back` 导致提前中断或轮次失败。
   - 修复：区分正常同包滚动与异常跳转。仅当命中 `WRONG_PAGE_MARKERS`（如“同款好物”、“同款低价”等明确商品比价详情页）或发生跨包跳转时才阻断；同包常态浏览允许滚动内容更新。

2. **元宝中心慢渲染导致假性失败**：
   - 现象：点击元宝中心后，若 H5 弹窗或首屏渲染超过原设定的短超时，直接判定进入元宝中心失败并中止整轮。
   - 修复：增加 `_is_yuanbao_center_ocr` 延迟二次复核机制，容忍 H5 慢渲染；若元宝中心导航未确认，规范向外抛出 `round_skipped` 事件。

3. **购物赚钱与点淘鸭摇一摇导航脆弱性**：
   - 现象：`_nav_to_shop` 仅在当前首屏扫描 5 次，未像签到一样具备上滑露天下方卡片的能力；`_nav_to_yaoyiyao` 右滑幅度过大且缺乏重试补划，容易错过入口。
   - 修复：
     - `_nav_to_shop` 支持找不到入口时向下滑动（上滑屏幕）露天下方卡片（最多 5 次扫描，前 2 次未找到则触发滑动）；支持卡片本身直接点击与宽松同行按钮容差（垂直 220px 内）；扩充购物任务关键词（“精选宝贝”、“下单返元宝”等）。
     - `_nav_to_yaoyiyao` 优化右滑动程比例为 `0.15 -> 0.85`（duration 0.3s），并在重试未找到时补划一次右滑；扩充摇一摇落地标记（“摇一摇PK”、“赚次数”、“点淘鸭”）。

4. **任务标记（NAV_PAGE_MARKERS）覆盖不足**：
   - 现象：部分机型/新版活动页面头部仅展示“打工”、“得体力”或“开店”，旧版 marker 要求完整命中“打工赚元宝”导致误判未到达目标页。
   - 修复：扩充 `NAV_PAGE_MARKERS`，涵盖“打工”、“得体力”、“开店”、“精选宝贝”、“摇一摇PK”、“赚次数”、“点淘鸭”等真实界面变体。

---

## 二、改动文件清单

1. `一键下滑.py`：
   - 优化 `NAV_PAGE_MARKERS`，扩充打工、购物、摇一摇、走路页面真实变体。
   - 优化 `_enter_yuanbao_center_ocr`，增加延迟复核与慢渲染重试机制。
   - 优化 `_nav_to_shop`，支持下滚露天下方卡片、卡片直点与丰富动作关键词。
   - 优化 `_nav_to_yaoyiyao`，平滑右滑动程比例并支持重试补划。
   - 优化 `swipe_browse` 与 `_recover_after_wrong_page`，修复滚出视口误判直播 H5，保障同包内正常持续浏览。
   - 优化 `run_round`，元宝中心未确认时显式输出 `round_skipped` 事件。
2. `tests/test_swipe_navigation_guard.py`：
   - 新增 `test_run_round_emits_round_skipped_when_center_unconfirmed`
   - 新增 `test_enter_yuanbao_center_retries_on_slow_h5_render`
   - 新增 `test_swipe_browse_continues_when_marker_scrolls_off_screen_in_same_activity`
   - 新增 `test_nav_to_shop_swipes_up_to_reveal_lower_card`
   - 新增 `test_nav_to_shop_clicks_card_directly_when_no_action_button`
   - 新增 `test_expanded_markers_match_realistic_page_variants`
3. `docs/records/e-diantao-170/record.md`：
   - 记录本单改动、复现根因与验证结果。

---

## 三、离线验证命令与结果

### 1. 针对性守卫与手势回归（共 29 项）
```bash
uv run --no-project --with pytest python -m pytest tests/test_swipe_navigation_guard.py tests/test_swipe_guard_regression.py -v -p no:cacheprovider
```
结果：`29 passed in 0.12s`（100% 通过）。

### 2. 购物入口与关联导航回归（共 10 项）
```bash
uv run --no-project --with pytest python -m pytest tests/test_shopping_entry_routes.py -v -p no:cacheprovider
```
结果：`10 passed in 0.15s`（100% 通过）。

---

## 四、剩余风险与注意项

1. **未真机验证**：本单全部验证均基于离线 mock/单元回归与真实日志逻辑复现，未直接连接物理 Android 真机进行 UI 点击与真实滑动。真机运行效果仍取决于真实网络延迟与官方活动页面实时改版。
2. **手势边界**：下滑手势 X 轴保持在 `0.08~0.15`，避开了双列商品点击热区；若特定设备系统级侧滑返回手势热区较大（>120px），可在后续单中微调起始 X 至 `0.18~0.25`。

---

## 五、回退方式

```powershell
git revert --no-edit HEAD
```
