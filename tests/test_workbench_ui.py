"""Browser checks for the desktop workbench; phone and process APIs are simulated."""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

import pytest

playwright = pytest.importorskip("playwright.sync_api")
HTML = (Path(__file__).resolve().parents[1] / "workbench" / "static" / "index.html").read_text(
    encoding="utf-8"
)


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as runtime:
        cached = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
        executables = list(cached.glob("chromium-*/chrome-win*/chrome.exe"))
        executable = max(
            executables,
            key=lambda p: int(p.parent.parent.name.split("-")[-1]),
            default=None,
        )
        options = {"executable_path": str(executable)} if executable else {}
        instance = runtime.chromium.launch(headless=True, **options)
        yield instance
        instance.close()


@pytest.fixture
def workbench(browser):
    page = browser.new_page(viewport={"width": 1280, "height": 820})
    state = {
        "apps": [
            {"id": "diantao-coupon", "name": "点淘养优惠",
             "category": "script", "status": "stopped",
             "description": "日常任务 → 双十一能量"},
            {"id": "taobao-double11-energy", "name": "淘金币双11赚能量", "category": "script",
             "status": "stopped", "description": "浏览任务并复查到账"},
            {"id": "web", "name": "旧 Web 应用", "category": "web", "status": "running"},
            {"id": "ai", "name": "旧 AI 任务", "category": "ai", "status": "running"},
            {"id": "tool", "name": "旧快捷工具", "category": "tool", "status": "running"},
        ],
        "actions": [], "cancelled": [], "paired": False, "connected": False,
    }
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script("""
        window.__streams = [];
        window.EventSource = class {
          constructor(url) { this.url = url; window.__streams.push(this); }
          close() { this.closed = true; }
        };
    """)

    def respond(route):
        path = urlsplit(route.request.url).path
        body = {}
        if path == "/":
            route.fulfill(content_type="text/html", body=HTML)
            return
        if path == "/api/apps":
            body = {"apps": deepcopy(state["apps"])}
        elif path == "/api/adb/status":
            body = {"installed": True, "devices": [
                {"serial": "phone", "status": "device"}
            ] if state["connected"] else []}
        elif path.startswith(("/api/start/", "/api/stop/")):
            action, task_id = path.split("/")[-2:]
            state["actions"].append((action, task_id))
            for task in state["apps"]:
                if task["id"] == task_id:
                    task["status"] = "running" if action == "start" else "stopped"
            body = {"ok": True, "message": "操作完成"}
        elif path.startswith("/api/logs/"):
            body = {"lines": ["历史任务记录"], "running": False}
        elif path == "/api/adb/qr-generate":
            body = {
                "session_id": "test-pairing",
                "qr_image": "data:image/svg+xml;base64,"
                            "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=",
                "password": "not-for-display",
            }
        elif path.startswith("/api/adb/qr-poll/"):
            body = {"status": "paired" if state["paired"] else "waiting"}
        elif path.startswith("/api/adb/qr-connect/"):
            state["connected"] = True
            body = {"ok": True, "message": "connected"}
        elif path.startswith("/api/adb/qr-cancel/"):
            state["cancelled"].append(path.rsplit("/", 1)[-1])
            body = {"ok": True}
        else:
            route.fulfill(status=404, body="not found")
            return
        route.fulfill(content_type="application/json", body=json.dumps(body))

    page.route("http://workbench.test/**", respond)
    page.goto("http://workbench.test/")
    playwright.expect(page.locator("#stat-total")).to_have_text("2")
    yield page, state
    assert errors == []
    page.close()


def test_only_python_tasks_are_visible_and_counted(workbench):
    page, state = workbench
    assert state["actions"] == []
    assert page.locator("#connect-phone").count() == 1
    assert page.get_by_role("dialog").is_hidden()
    playwright.expect(page.locator("#stat-running")).to_have_text("0")
    for name in ["旧 Web 应用", "旧 AI 任务", "旧快捷工具", "全部启动"]:
        assert name not in page.locator("body").inner_text()
    assert page.evaluate("window.__streams.length") == 0
    page.get_by_role("searchbox").fill("赚能量")
    playwright.expect(page.locator("#script-list")).to_contain_text("淘金币双11赚能量")
    assert page.locator("#featured-task").inner_text() == ""
    page.get_by_role("searchbox").fill("不存在")
    playwright.expect(page.locator("#script-empty")).to_be_visible()


def test_start_stream_filter_stop_and_history(workbench):
    page, state = workbench
    page.locator('#script-list [data-action="start"][data-id="taobao-double11-energy"]').click()
    playwright.expect(page.locator("#stat-running")).to_have_text("1")
    assert state["actions"] == [("start", "taobao-double11-energy")]
    page.wait_for_function("window.__streams.length === 1")
    assert page.evaluate("window.__streams[0].url") == "/api/logs/taobao-double11-energy/stream"
    page.evaluate("""window.__streams[0].onmessage({
        data: JSON.stringify({type:"log", text:"能量 +400 <script>unsafe</script>"})
    })""")
    playwright.expect(page.locator("#log-content")).to_contain_text("能量 +400")
    assert page.locator("#log-content script").count() == 0
    page.locator('[data-filter="running"]').click()
    assert page.locator("#featured-task").inner_text() == ""
    playwright.expect(page.locator("#script-list .task-row")).to_have_count(1)
    page.get_by_role("button", name="停止运行中任务").click()
    playwright.expect(page.locator("#stat-running")).to_have_text("0")
    assert state["actions"] == [("start", "taobao-double11-energy"), ("stop", "taobao-double11-energy")]
    assert page.evaluate("window.__streams[0].closed")
    page.locator('[data-filter="all"]').click()
    page.locator('#script-list [data-action="logs"][data-id="taobao-double11-energy"]').click()
    playwright.expect(page.locator("#log-content")).to_contain_text("历史任务记录")
    page.get_by_role("button", name="清空显示").click()
    playwright.expect(page.locator("#log-empty")).to_be_visible()


def test_qr_pairing_connects_and_returns_focus(workbench):
    page, state = workbench
    page.get_by_role("button", name="扫码连接手机", exact=True).click()
    playwright.expect(page.get_by_role("dialog")).to_be_visible()
    playwright.expect(page.locator("#adb-qr-image-area img")).to_be_visible()
    assert "not-for-display" not in page.locator("body").inner_text()
    state["paired"] = True
    playwright.expect(page.locator("#adb-qr-connect-btn")).to_have_text(
        "完成，返回工作台", timeout=10000
    )
    playwright.expect(page.locator("#device-badge")).to_have_text("已连接 1 台")
    page.get_by_role("button", name="完成，返回工作台").click()
    playwright.expect(page.get_by_role("dialog")).to_be_hidden()
    playwright.expect(page.locator("#connect-phone")).to_be_focused()
    assert state["cancelled"] == ["test-pairing"]


def test_closing_while_qr_is_loading_cancels_late_session(workbench):
    page, state = workbench
    page.evaluate("""() => {
      const original = window.fetch;
      window.fetch = async function(url, options) {
        const response = await original(url, options);
        if (url === "/api/adb/qr-generate") {
          await new Promise(resolve => { window.__releaseQr = resolve; });
        }
        return response;
      };
    }""")
    page.get_by_role("button", name="扫码连接手机", exact=True).click()
    page.wait_for_function("typeof window.__releaseQr === 'function'")
    page.keyboard.press("Escape")
    page.evaluate("window.__releaseQr()")
    page.wait_for_function("document.getElementById('adb-qr-modal').style.display === 'none'")
    page.wait_for_function("qrSession === null")
    page.wait_for_function("qrTimer === null")
    playwright.expect(page.get_by_role("dialog")).to_be_hidden()
    page.wait_for_function("""async () => {
        await fetch("/api/adb/status");
        return true;
    }""")
    assert state["cancelled"] == ["test-pairing"]


@pytest.mark.parametrize("theme,label", [("black", "黑色配色"), ("white", "白色配色")])
def test_monochrome_theme_persists_and_keeps_text_readable(workbench, theme, label):
    page, state = workbench
    page.get_by_role("button", name=label, exact=True).click()
    page.reload()
    playwright.expect(page.get_by_role("button", name=label, exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    page.get_by_role("button", name="扫码连接手机", exact=True).click()
    playwright.expect(page.get_by_role("dialog")).to_be_visible()
    colors = page.evaluate("""() => {
      const body = getComputedStyle(document.body);
      const dialog = getComputedStyle(document.querySelector(".dialog"));
      return {background: body.backgroundColor, text: body.color,
              dialogBackground: dialog.backgroundColor, dialogText: dialog.color};
    }""")

    def luminance(color):
        channels = [int(value) / 255 for value in re.findall(r"\d+", color)[:3]]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
                  for v in channels]
        return sum(v * weight for v, weight in zip(linear, [.2126, .7152, .0722]))

    for background, text in [("background", "text"), ("dialogBackground", "dialogText")]:
        values = sorted([luminance(colors[background]), luminance(colors[text])])
        assert (values[1] + .05) / (values[0] + .05) >= 4.5
    assert (luminance(colors["background"]) > .5) == (theme == "white")
    assert state["actions"] == []


@pytest.mark.parametrize("size", [(1280, 820), (900, 700), (700, 500), (390, 844)])
def test_workbench_has_no_horizontal_overflow(workbench, size):
    page, _ = workbench
    page.set_viewport_size({"width": size[0], "height": size[1]})
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    )
    playwright.expect(page.locator("#connect-phone")).to_be_visible()
    playwright.expect(page.locator("#log-filter")).to_be_visible()
