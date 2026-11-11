# Trail e-diantao-167-fix-1 改动记录

- **任务**：`e-diantao-167-fix-1` — [Review Fix from #167 by pi] 点淘一键任务收口：睡觉赚元宝拉黑 + 能量任务剔除（活动结束）
- **关联原单**：`e-diantao-167`
- **执行平台**：Windows (`win-371a01cd`)
- **工作目录**：`C:\Agent工作空间\worktrees\mcc-e-diantao-167-fix-1`

---

## 一、审计整改背景

在 `e-diantao-167` 完成睡觉赚元宝黑名单屏蔽与淘金币双11能量一键入口剔除后，Reviewer Pi 提交了后置异步审计，提出 4 项整改意见（2 should + 2 nit）。本单作为关联修复单对该 4 项审计意见进行闭环修正。

---

## 二、整改项与具体改动

### 1. [should] 修正 workbench OCR 门禁测试 (`tests/test_workbench.py`)
- **原问题**：原 `test_one_click_entry_does_not_require_cloud_ocr` 断言 `diantao-one-click-tasks` 在未配置 `DIANTAO_OCR_SERVER_URL` 时返回 200，但该入口在 `workbench/tasks.py` 中 `requires_ocr` 默认为 `True`，因此确定性返回 400 失败。
- **改动**：
  - 新增 `test_one_click_entry_requires_cloud_ocr`：断言 `diantao-one-click-tasks` 在未配置 `DIANTAO_OCR_SERVER_URL` 时返回 400，并提示配置 URL。
  - 新增 `test_entry_without_cloud_ocr_requirement_can_start`：将任务动态设置为 `requires_ocr=False`，断言在无 OCR 配置时可正常启动返回 200。
  - 测试覆盖两种分支，真实通过。

### 2. [should] 纳入 `.runtime` 运行时脚本版本控制
- **原问题**：`.runtime/head-tasks.py` 和 `.runtime/head-all-in-one.py` 在 worktree 中为未跟踪文件，常规提交可能遗漏导致运行时副本不同步。
- **改动**：
  - 显式 `git add` 将 `.runtime/head-tasks.py` 和 `.runtime/head-all-in-one.py` 纳入版本控制与本单提交。

### 3. [nit] 睡觉赚元宝签到分支改为跳过并继续扫描 (`睡觉赚元宝.py`)
- **原问题**：签到分支原本执行点击后 `return False`，而在 `scan_and_collect` 中 `do_bubble_task(...) is False` 会触发 `return total`，导致单个签到气泡即提前中止整轮扫描。
- **改动**：
  - `do_bubble_task` 中签到分支改为打印跳过并 `return "skip"`。
  - `scan_and_collect` 中增加 `if status == "skip": continue` 处理，避免中止整轮扫描，且不记入完成计数、不调用 `log_task_completed`。

### 4. [nit] 看板任务条目数量硬编码具体数值 (`tests/test_workbench.py`)
- **原问题**：第 52 行使用 `assert len(tasks) == len(desktop.TASKS)` 为恒真断言，失去了条目数量变化的回归保护。
- **改动**：
  - 明确断言 `assert len(tasks) == 22`（剔除 `diantao-sleep`、`taobao-double11-energy`、`taobao-double11-workbuddy` 3项后实际看板条目数为 22）。

---

## 三、验证记录

1. **JSON 语法校验**：
   - `python -m json.tool task_config.json`：通过。
2. **Python 语法编译**：
   - `python -m py_compile` 编译 22 个相关 Python 文件（含 `.runtime/head-*.py`、`workbench/tasks.py`、`睡觉赚元宝.py` 等）：全部通过无报错。
3. **黑名单函数断言验证**：
   - `is_blocked_task_file("睡觉赚元宝.py")` == True
   - `is_blocked_task_file("C:/x/睡觉赚元宝.py")` == True
   - `is_blocked_task_file("走路赚元宝.py")` == False
   - `is_blocked_sleep_task_name("查看３个精选")` == True
   - `is_blocked_sleep_task_name("看直播 30秒")` == False
   - `is_blocked_sleep_task_name("签到")` == False
4. **一键执行任务清单**：
   - `一键全部执行.py` 之 `ALL_TASKS` 长度为 21，不含 `睡觉赚元宝.py` 和 `tools/taobao_energy.py`。
5. **自动化测试**：
   - `tests/test_workbench.py`：22 项全量通过（100%）。
   - `tests/test_sleep_progress.py`、`tests/test_sleep_whitelist.py`、`tests/test_blocked_three_click_tasks.py`、`tests/test_blocked_boutique_tasks.py`：143 项全量通过（100%）。
   - `tests/test_register_all_in_one.py`、`tests/test_register_one_click.py`：6 项全量通过（100%）。
