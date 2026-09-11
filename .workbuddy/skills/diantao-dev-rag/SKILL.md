---
title: "diantao-dev-rag"
summary: "修改 diantao 代码前，自动查 RAG 获取相关开发规范"
trigger_phrases:
  - 改diantao代码
  - 点淘脚本
  - diantao任务
  - 打工脚本
  - 签到脚本
  - 摇一摇
  - 钻石任务
  - 全部执行
  - 一键下滑
  - 白名单
  - 黑名单
  - utils.py
  - u2_scanner.py
  - rag_client.py
---

# diantao-dev-rag — 开发规范知识库辅助工作流

**核心规则：修改 diantao 项目代码前，必须先查 RAG 获取相关规范，再动手。**

---

## 1. 查询 RAG 获取规范

调用 `rag_client.query_rules()` 或 `rag_client.query()` 向本地 LightRAG
（http://127.0.0.1:9621）发起查询。

### 查询模板

| 场景 | query 内容 |
|------|-----------|
| 改白名单 / 黑名单 | `query_rules("白名单", "具体任务名")` |
| 新增或修改任务类型 | `"开发规范：{具体任务名} 相关规则和实现方式"` |
| 改返回逻辑 | `query_rules("返回规范")` |
| 新增脚本 | `"项目结构 开发规范 函数签名"` |
| 改浏览/直播逻辑 | `query_rules("任务类型", "浏览")` 或 `query_rules("任务类型", "直播")` |
| 点击3次 / 猜价格 | `query_rules("点击3次")` 或 `query_rules("猜价格")` |
| 不确定场景 | `query(f"开发规范：{改动描述}")`，问得宽一点让 RAG 返回相关段落 |

### 如果 RAG 查询失败

- 打印警告 `⚠️ RAG 不可用，跳过规范检查`
- **不阻塞执行**，继续基于现有代码判断

---

## 2. 启动前初始化（首次）

在 Skill 首次加载时，确认 RAG 中已有内容。如果知识库为空，自动上传当前
`开发规范.md`：

```python
from rag_client import upload_document
from pathlib import Path

spec_path = Path("D:/GitHub Program/diantao/开发规范.md")
if spec_path.exists():
    tid = upload_document(str(spec_path))
    print(f"  开发规范已上传到 RAG，track_id: {tid}")
```

仅在创建 Skill 时做一次，后续不需要重复上传（除非用户要求）。

---

## 3. 执行规范后再改代码

将 RAG 返回的规范内容作为参考，再执行后续的代码修改。参考标准：
- 所有 `press("back")` 的使用必须符合「单一返回路径」规范
- 白名单匹配使用子串匹配（`any(kw in name for kw in WHITELIST)`）
- 危险关键词（下单/购买/付款）优先级高于白名单
- 每个任务最多执行 MAX_CLICK 次（通常为 2）

---

## 4. 记录改动（可选但推荐）

修改完成后，将改动摘要写回 RAG 以便后续查询：

```python
from rag_client import insert_change_log
insert_change_log("修改了 xxx，原因：xxx")
```
