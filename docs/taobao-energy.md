# 淘金币双11赚能量

运行入口：`run_taobao_energy.cmd`。复用现有 `device_connection.connect_with_retry`，不启动旧点淘任务调度器。

```powershell
# 从淘宝首页“领淘金币”或活动主页面进入赚能量列表
.\run_taobao_energy.cmd enter

# 检查当前屏幕和文字坐标
.\run_taobao_energy.cmd scan

# 逐项处理当前屏幕内已确认的免费浏览任务，最多30轮
.\run_taobao_energy.cmd auto --repeat 30

# 指定一个任务；每轮返回复查累计次数是否增加
.\run_taobao_energy.cmd browse 好物随心逛 --repeat 3
```

- 首页优先沿用原农场库的 U2 `领淘金币` 控件选择方式。此次活动 Themis WebView 实测没有可用文本，直接用本地 RapidOCR；截图不发送到云端。
- 任务会动态改名、换序，每轮重新定位任务和同一行的“去完成”。搜索任务从专用搜索页点击可见推荐词，再滑动浏览。
- 自动模式仅处理白名单浏览任务及“看看#”推荐主题，领取列表顶部已经解锁的累计任务奖励。只处理当前可见任务，需下滑检查更多任务。
- 支付宝和其他应用跳转、答题、提醒订阅及其他未知任务留给人工检查。跳转其他应用或累计任务次数不增加时停止，保留现场。
- 升级赛车、趣味小游戏、积分兑换、拍立淘、购买、邀请等不进入自动浏览白名单。`tap`、`back`、`swipe`、`text` 是供已检查截图后的逐步操作使用的低层命令。
- 当前授权截止时间默认为 **2026-10-19 00:00（北京时间）**，到期拒绝继续操作。后续再次取得授权才可通过 `--deadline` 指定新的含时区截止时间。
- 多设备连接时用 `--serial` 明确选择设备。仅连接一台时自动选择。

最近一次截图和 OCR 坐标保存在 `screenshots/taobao_energy/current.png`、`current.json`；`browse.png` 是返回前的浏览页。
