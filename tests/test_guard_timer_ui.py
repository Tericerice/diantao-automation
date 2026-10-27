"""Browser regressions for guardian coexistence and live countdowns."""
import time

import pytest

from test_workbench_ui import browser, workbench, playwright


def add_guard(page, state, *, running=False):
    state["apps"].append({
        "id": "diantao-work-guard", "name": "打工任务", "category": "script",
        "status": "running" if running else "stopped",
        "timer": {"active": True, "phase": "waiting", "server_time": time.time(),
                  "work_at": time.time() + 3600, "energy_at": time.time() + 120},
    })
    page.evaluate("refreshTasks()")
    page.wait_for_selector("#guard-countdown")


def test_guard_can_start_during_foreground_and_foreground_during_guard(workbench):
    page, state = workbench
    state["apps"][0]["status"] = "running"
    add_guard(page, state)
    guard_row = page.get_by_role("listitem").filter(has_text="打工任务")
    playwright.expect(guard_row.get_by_role("button", name="启动", exact=True)).to_be_enabled()
    playwright.expect(page.get_by_role("listitem").filter(
        has_text="淘金币双11赚能量").get_by_role("button", name="启动", exact=True)).to_be_disabled()
    state["apps"][0]["status"] = "stopped"
    state["apps"][-1]["status"] = "running"
    page.evaluate("refreshTasks()")
    playwright.expect(page.get_by_role("listitem").filter(
        has_text="点淘养优惠").get_by_role("button", name="启动", exact=True)).to_be_enabled()
    playwright.expect(guard_row.get_by_role("button", name="立即校准")).to_be_visible()


def test_countdown_ticks_and_calibration_requests_rescan(workbench):
    page, state = workbench
    add_guard(page, state, running=True)
    countdown = page.locator("#guard-countdown")
    playwright.expect(countdown).to_contain_text("后台计时")
    before = countdown.inner_text()
    page.wait_for_function(
        "text => document.getElementById('guard-countdown').textContent !== text", arg=before)
    calls = []

    def calibrate(route):
        calls.append(route.request.method)
        route.fulfill(content_type="application/json", body='{"ok":true,"message":"已请求校准"}')

    page.route("**/api/work-guard/refresh", calibrate)
    page.get_by_role("button", name="立即校准").click()
    playwright.expect(page.locator("#toast-container")).to_contain_text("已请求校准")
    assert calls == ["POST"]


@pytest.mark.parametrize("width", [390, 700, 1280])
def test_guard_controls_fit_with_both_timers(workbench, width):
    page, state = workbench
    page.set_viewport_size({"width": width, "height": 844})
    add_guard(page, state, running=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    playwright.expect(page.get_by_role("button", name="立即校准")).to_be_visible()
