"""e-diantao-169：导航校验、直播 H5 拦截、下滑手势与错误页恢复的离线回归。

fixture 来自 `.runtime/workbench/diantao-swipe.log` 的关键事件序列：
  第 1 轮: OCR 点击【打工赚元宝】→ 4 次预期文字未命中 → 允许继续
          → 同包切到 com.taobao.live.h5.BrowserActivity
          → OCR 出现「同款好物」→ 停止本轮
本文件用同样的事件顺序验证新契约：未确认页面不得开始下滑，误入商品页
必须回退恢复（有界），恢复失败才判本轮失败。
"""
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWIPE = ROOT / "一键下滑.py"
DT_APP = "com.taobao.live"


def load_swipe_module(monkeypatch):
    """在不连接手机的前提下加载一键下滑.py 的纯函数。"""
    fake_device = types.SimpleNamespace(
        window_size=lambda: (1264, 2780),
        swipe=lambda *a, **kw: None,
        press=lambda *a, **kw: None,
        click=lambda *a, **kw: None,
        app_start=lambda *a, **kw: None)
    fake_u2 = types.ModuleType("u2_scanner")
    fake_u2.connect_device = lambda: fake_device
    fake_u2.DT_APP = DT_APP
    fake_utils = types.ModuleType("utils")
    fake_utils.get_ocr_text_blocks = lambda device: []
    fake_utils.get_current_app = lambda device: (DT_APP, "BrowserActivity")
    fake_popup = types.ModuleType("yuanbao_popup")
    fake_popup.handle_yuanbao_live_popups = lambda device: True
    fake_checkpoint = types.ModuleType("task_checkpoint")
    fake_checkpoint.run_step = lambda key, label, fn, *args, **kwargs: fn(*args, **kwargs)
    for name, module in (("u2_scanner", fake_u2), ("utils", fake_utils),
                         ("yuanbao_popup", fake_popup),
                         ("task_checkpoint", fake_checkpoint)):
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("swipe_guard_under_test", SWIPE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "swipe_guard_under_test", module)
    spec.loader.exec_module(module)
    return module


def block(text, cx=100, cy=100):
    return {"text": text, "cx": cx, "cy": cy}


def fake_clock(monkeypatch, module, times=(0, 0, 100)):
    """swipe_browse 用 time() 判断是否继续；默认允许 1 次滑动后退出。"""
    monkeypatch.setattr(module.time, "time", iter(times).__next__)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(module.random, "uniform", lambda a, b: 0)
    monkeypatch.setattr(module.random, "randint", lambda a, b: a)


def test_round_1_log_replay_missing_marker_is_not_reached(monkeypatch, capsys):
    """日志第 1 轮：4 次 OCR 未命中时，仍在点淘也不能算到达预期页。"""
    module = load_swipe_module(monkeypatch)
    monkeypatch.setattr(module, "get_current_app",
                        lambda device: (DT_APP, "com.taobao.live.h5.BrowserActivity"))
    monkeypatch.setattr(module, "get_ocr_text_blocks", lambda device: [])
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    assert module._expected_page_reached(
        None, ("打工赚元宝",), attempts=4) is False
    out = capsys.readouterr().out
    assert "直播 H5 容器内未命中本轮任务标记" in out
    assert "导航未到达目标页" in out


def test_marker_hit_confirms_expected_page(monkeypatch, capsys):
    module = load_swipe_module(monkeypatch)
    monkeypatch.setattr(module, "get_current_app",
                        lambda device: (DT_APP, "com.taobao.live.h5.BrowserActivity"))
    monkeypatch.setattr(module, "get_ocr_text_blocks",
                        lambda device: [block("打工赚元宝")])
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    assert module._expected_page_reached(None, ("打工赚元宝",), attempts=2) is True
    assert "OCR 确认预期页面" in capsys.readouterr().out


def test_navigation_retries_after_validation_failure(monkeypatch, capsys):
    """落地校验失败必须先回退、回元宝中心，再重试导航；重试成功才继续。"""
    module = load_swipe_module(monkeypatch)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(module, "_is_yuanbao_center_ocr", lambda device: True)
    clicked = {"n": 0}
    backs = {"n": 0}

    def click_target(device):
        clicked["n"] += 1
        return True

    def ocr(device):
        return [block("打工赚元宝")] if clicked["n"] >= 2 else []

    def back(device):
        backs["n"] += 1
        return True

    monkeypatch.setattr(module, "get_ocr_text_blocks", ocr)
    monkeypatch.setattr(module, "get_current_app",
                        lambda device: (DT_APP, "BrowserActivity"))
    monkeypatch.setattr(module, "_safe_back", back)
    assert module._navigate_and_verify(None, "打工赚元宝", click_target) is True
    assert clicked["n"] == 2
    assert backs["n"] == 1
    assert "第 2/2 次重新导航" in capsys.readouterr().out


def test_navigation_gives_up_after_bounded_attempts(monkeypatch, capsys):
    module = load_swipe_module(monkeypatch)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(module, "_is_yuanbao_center_ocr", lambda device: True)
    monkeypatch.setattr(module, "get_ocr_text_blocks", lambda device: [])
    monkeypatch.setattr(module, "get_current_app",
                        lambda device: (DT_APP, "BrowserActivity"))
    clicks = {"n": 0}

    def click_target(device):
        clicks["n"] += 1
        return True

    assert module._navigate_and_verify(None, "打工赚元宝", click_target) is False
    assert clicks["n"] == module.NAV_ATTEMPTS_LIMIT
    assert "跳过本轮" in capsys.readouterr().out


def test_unconfirmed_page_never_calls_swipe(monkeypatch, capsys):
    """marker 缺失 + 仍在点淘 + BrowserActivity：不得调用 swipe。"""
    module = load_swipe_module(monkeypatch)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(module.random, "uniform", lambda a, b: 0)
    monkeypatch.setattr(module.random, "randint", lambda a, b: a)
    monkeypatch.setattr(module, "get_current_app",
                        lambda device: (DT_APP, "com.taobao.live.h5.BrowserActivity"))
    monkeypatch.setattr(module, "get_ocr_text_blocks", lambda device: [])
    swipes = []
    monkeypatch.setattr(module.d, "swipe", lambda *a, **kw: swipes.append((a, kw)))
    assert module.swipe_browse(0.01, ("打工赚元宝",)) is False
    assert swipes == []
    out = capsys.readouterr().out
    assert "下滑前页面不是本轮任务页" in out
    assert "下滑前错误页恢复失败" in out


def test_round_1_log_replay_same_goods_recovers_instead_of_ending_round(monkeypatch, capsys):
    """误入「同款好物」后先回退恢复；确认回到任务页则继续剩余下滑。"""
    module = load_swipe_module(monkeypatch)
    fake_clock(monkeypatch, module)
    texts = iter([
        "打工赚元宝",   # 下滑前确认任务页
        "同款好物",     # 滑动后误入商品页
        "同款好物",     # 第 1 次回退仍在错误页
        "打工赚元宝",   # 第 2 次回退恢复任务页
    ])
    monkeypatch.setattr(module, "get_ocr_text_blocks",
                        lambda device: [block(next(texts))])
    monkeypatch.setattr(module, "get_current_app",
                        lambda device: (DT_APP, "BrowserActivity"))
    swipes = []
    backs = []
    monkeypatch.setattr(module.d, "swipe", lambda *a, **kw: swipes.append((a, kw)))
    monkeypatch.setattr(module.d, "press", lambda *a, **kw: backs.append(a))
    assert module.swipe_browse(0.01, ("打工赚元宝",)) is True
    assert len(swipes) == 1
    assert len(backs) == 2
    out = capsys.readouterr().out
    assert "误入「同款好物」商品页，尝试回退任务页" in out
    assert "已回到任务页，继续剩余下滑" in out
    assert "停止本轮下滑" not in out


def test_same_goods_recovery_exhausted_fails_round(monkeypatch, capsys):
    module = load_swipe_module(monkeypatch)
    fake_clock(monkeypatch, module)
    texts = iter(["打工赚元宝", "同款好物", "同款好物", "同款好物"])
    monkeypatch.setattr(module, "get_ocr_text_blocks",
                        lambda device: [block(next(texts))])
    monkeypatch.setattr(module, "get_current_app",
                        lambda device: (DT_APP, "BrowserActivity"))
    swipes = []
    backs = []
    monkeypatch.setattr(module.d, "swipe", lambda *a, **kw: swipes.append((a, kw)))
    monkeypatch.setattr(module.d, "press", lambda *a, **kw: backs.append(a))
    assert module.swipe_browse(0.01, ("打工赚元宝",)) is False
    assert len(swipes) == 1
    assert len(backs) == module.WRONG_PAGE_MAX_RECOVERIES
    out = capsys.readouterr().out
    assert "错误页恢复失败达到上限" in out
    assert "恢复失败" in out


def test_live_h5_without_marker_after_swipe_is_treated_as_wrong_page(monkeypatch, capsys):
    """滑动后切到 BrowserUpperActivity 且任务标记消失：按错误页恢复。"""
    module = load_swipe_module(monkeypatch)
    fake_clock(monkeypatch, module)
    apps = iter([
        (DT_APP, "BrowserActivity"),        # 下滑前
        (DT_APP, "BrowserUpperActivity"),   # 滑动后
        (DT_APP, "BrowserActivity"),        # 恢复后
        (DT_APP, "BrowserActivity"),        # 恢复后
        (DT_APP, "BrowserActivity"),        # 继续下滑前刷新
    ])
    texts = iter([
        "打工赚元宝",      # 下滑前 marker
        "热卖推荐",        # 滑动后无 marker（直播 H5 容器）
        "打工赚元宝",      # 回退恢复 marker
    ])
    monkeypatch.setattr(module, "get_current_app", lambda device: next(apps))
    monkeypatch.setattr(module, "get_ocr_text_blocks",
                        lambda device: [block(next(texts))])
    assert module.swipe_browse(0.01, ("打工赚元宝",)) is True
    out = capsys.readouterr().out
    assert "滑入直播 H5 容器且任务标记消失" in out
    assert "已回到任务页，继续剩余下滑" in out


def test_swipe_uses_left_safe_band_and_long_duration(monkeypatch, capsys):
    module = load_swipe_module(monkeypatch)
    fake_clock(monkeypatch, module)
    monkeypatch.setattr(module, "get_current_app",
                        lambda device: (DT_APP, "BrowserActivity"))
    monkeypatch.setattr(module, "get_ocr_text_blocks",
                        lambda device: [block("打工赚元宝")])
    swipes = []
    monkeypatch.setattr(module.d, "swipe", lambda *a, **kw: swipes.append((a, kw)))
    assert module.swipe_browse(0.01, ("打工赚元宝",)) is True
    args, kwargs = swipes[0]
    assert int(0.08 * 1264) <= args[0] <= int(0.15 * 1264)
    assert args[2] == args[0]
    assert kwargs["duration"] >= 0.8
    assert "round_failed" not in capsys.readouterr().out


def test_ocr_click_target_logs_evidence(monkeypatch, capsys):
    module = load_swipe_module(monkeypatch)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    blocks = [
        block("打工赚元宝", 480, 2396),
        block("去完成", 480, 2520),
        block("每日开店赚元宝", 900, 2350),
    ]
    monkeypatch.setattr(module, "get_ocr_text_blocks", lambda device: blocks)
    clicks = []
    monkeypatch.setattr(module.d, "click",
                        lambda x, y: clicks.append((x, y)))
    assert module._ocr_click_target(module.d, "打工赚元宝", attempts=1) is True
    assert clicks == [(480, 2396)]
    out = capsys.readouterr().out
    assert "点击证据" in out
    assert "去完成" in out
