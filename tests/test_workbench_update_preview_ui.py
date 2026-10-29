"""Browser checks for the new shell embedding the real workbench."""
from pathlib import Path
import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
HTML = (Path(__file__).resolve().parents[1] / "workbench_update_preview" / "static" / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as runtime:
        cached = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
        executables = list(cached.glob("chromium-*/chrome-win*/chrome.exe"))
        executable = max(executables, key=lambda p: int(p.parent.parent.name.split("-")[-1]), default=None)
        options = {"executable_path": str(executable)} if executable else {}
        instance = runtime.chromium.launch(headless=True, **options)
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    tab = browser.new_page(viewport={"width": 1180, "height": 780})
    errors = []
    tab.on("pageerror", lambda error: errors.append(str(error)))
    update = {
        "status": "available", "current_version": "0.3.0",
        "latest_version": "0.3.1-demo", "progress": 0,
        "phase": "发现新版本", "message": "新版本已准备好。",
        "can_install": True, "can_cancel": False,
        "release_notes": ["新增真实管家嵌入的新看板。"],
    }

    def route(request):
        url = request.request.url
        if url == "http://preview.test/":
            request.fulfill(content_type="text/html", body=HTML)
        elif url.startswith("http://127.0.0.1:9060/"):
            request.fulfill(content_type="text/html; charset=utf-8", body="<meta charset='utf-8'><title>真实管家</title><h1>Tearice 自动化大管家</h1>")
        elif url.endswith("/api/upstream/status"):
            request.fulfill(content_type="application/json", body=json.dumps({"ok": True}))
        elif url.endswith("/api/update/status"):
            request.fulfill(content_type="application/json", body=json.dumps(update))
        elif "/api/update/" in url:
            name = url.rsplit("/", 1)[-1]
            if name == "install":
                update.update(status="installing", progress=35, phase="准备新版本",
                              message="仅模拟，不会覆盖当前管家。", can_install=False, can_cancel=True)
            elif name == "cancel":
                update.update(status="cancelled", phase="更新已取消", can_install=True, can_cancel=False)
            elif name == "reset":
                update.update(status="available", progress=0, phase="发现新版本", can_install=True, can_cancel=False)
            request.fulfill(content_type="application/json", body=json.dumps({"ok": True, "message": "完成", "update": update}))
        else:
            request.fulfill(status=404, body="not found")

    tab.route("**/*", route)
    tab.goto("http://preview.test/")
    playwright.expect(tab.frame_locator("#real-workbench").get_by_role("heading")).to_have_text("Tearice 自动化大管家")
    yield tab
    assert errors == []
    tab.close()


def test_new_shell_embeds_real_workbench_and_shows_update_entry(page):
    playwright.expect(page).to_have_title("Tearice · 自动化大管家")
    playwright.expect(page.locator("#upstream-status")).to_contain_text("真实管家已连接")
    playwright.expect(page.get_by_role("region", name="版本更新提示")).to_be_visible()
    playwright.expect(page.get_by_role("dialog")).to_be_hidden()
    assert page.locator("#real-workbench").get_attribute("src").startswith("http://127.0.0.1:9060/")


def test_update_dialog_remains_simulation_and_returns_focus(page):
    opener = page.get_by_role("button", name="查看更新")
    opener.click()
    playwright.expect(page.get_by_role("dialog")).to_be_visible()
    playwright.expect(page.get_by_role("button", name="关闭更新弹窗")).to_be_focused()
    page.get_by_role("button", name="开始模拟更新").click()
    playwright.expect(page.locator("#progress-box")).to_be_visible()
    playwright.expect(page.get_by_role("button", name="取消更新")).to_be_visible()
    page.get_by_role("button", name="取消更新").click()
    playwright.expect(page.locator("#phase")).to_have_text("更新已取消")
    page.get_by_role("button", name="关闭更新弹窗").click()
    playwright.expect(opener).to_be_focused()


@pytest.mark.parametrize("size", [(1180, 780), (700, 520), (390, 844)])
def test_shell_has_no_horizontal_overflow(page, size):
    page.set_viewport_size({"width": size[0], "height": size[1]})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
