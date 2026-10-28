"""Browser checks for the standalone update-preview experience."""
from pathlib import Path
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from workbench_update_preview import app as preview

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
def page(browser, monkeypatch):
    monkeypatch.setattr(preview, "_STATE", preview.UpdateState(duration=60))
    client = TestClient(preview.app)
    tab = browser.new_page(viewport={"width": 1180, "height": 780})
    errors = []
    tab.on("pageerror", lambda error: errors.append(str(error)))

    def route(request):
        path = request.request.url.replace("http://preview.test", "")
        if path == "/":
            request.fulfill(content_type="text/html", body=HTML)
            return
        response = client.request(request.request.method, path)
        request.fulfill(status=response.status_code,
                        content_type=response.headers.get("content-type", "application/json"),
                        body=response.content)

    tab.route("http://preview.test/**", route)
    tab.goto("http://preview.test/")
    playwright.expect(tab.locator("#task-grid .task")).to_have_count(3)
    yield tab
    assert errors == []
    tab.close()
    client.close()


def test_preview_shows_version_non_intrusive_banner_and_safety_boundaries(page):
    playwright.expect(page).to_have_title("Tearice · 自动更新预览")
    playwright.expect(page.locator("#top-version")).to_have_text("v0.2.1")
    playwright.expect(page.locator("#update-banner")).to_be_visible()
    assert page.get_by_role("dialog").is_hidden()
    body = page.locator("body").inner_text()
    for text in ["预览模式 · 未连接手机", "手机与 ADB", "未调用", "仅在内存"]:
        assert text in body


def test_update_dialog_focus_progress_cancel_and_reset(page):
    opener = page.get_by_role("button", name="查看更新")
    opener.click()
    dialog = page.get_by_role("dialog")
    playwright.expect(dialog).to_be_visible()
    playwright.expect(page.get_by_role("button", name="关闭更新弹窗")).to_be_focused()
    page.get_by_role("button", name="开始安全更新").click()
    playwright.expect(page.locator("#progress-box")).to_be_visible()
    playwright.expect(page.get_by_role("button", name="取消更新")).to_be_visible()
    assert int(page.locator("[role=progressbar]").get_attribute("aria-valuenow")) >= 0
    page.get_by_role("button", name="取消更新").click()
    playwright.expect(page.locator("#phase")).to_have_text("更新已取消")
    page.get_by_role("button", name="关闭更新弹窗").click()
    playwright.expect(dialog).to_be_hidden()
    playwright.expect(opener).to_be_focused()

    opener.click()
    page.evaluate("window.action('reset')")
    page.get_by_role("button", name="开始安全更新").click()
    preview._STATE.started_at -= 120
    page.wait_for_timeout(350)
    playwright.expect(page.get_by_role("button", name="重新预览")).to_be_visible()


@pytest.mark.parametrize("size", [(1180, 780), (700, 520), (390, 844)])
def test_preview_has_no_horizontal_overflow_and_keeps_focus_visible(page, size):
    page.set_viewport_size({"width": size[0], "height": size[1]})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.get_by_role("button", name="查看更新").focus()
    outline = page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
    assert outline != "none"
