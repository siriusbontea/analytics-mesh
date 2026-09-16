from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.ui


def test_help_drawer_open_and_dismiss(page: Page, live_node: str) -> None:
    page.goto(f"{live_node}/ui", wait_until="domcontentloaded")
    help_btn = page.locator("#helpBtn")
    drawer = page.locator("#helpDrawer")
    expect(help_btn).to_be_visible()
    expect(help_btn).to_have_text("Help")
    expect(drawer).to_be_hidden()

    help_btn.click()
    expect(drawer).to_be_visible()
    expect(page.locator("#help-getting-started")).to_contain_text("Getting started")
    expect(page.locator("#help-concepts")).to_contain_text("Concepts")
    expect(page.locator('[data-help-nav="getting-started"]')).to_be_visible()

    page.locator("#helpClose").click()
    expect(drawer).to_be_hidden()

    help_btn.click()
    expect(drawer).to_be_visible()
    page.keyboard.press("Escape")
    expect(drawer).to_be_hidden()


def test_run_top_products_shows_preview_and_receipt(page: Page, live_node: str) -> None:
    page.goto(f"{live_node}/ui", wait_until="domcontentloaded")
    analytic = page.locator("#analytic")
    expect(analytic.locator("option[value='top_products']")).to_have_count(1, timeout=15_000)
    analytic.select_option("top_products")

    page.locator("#runBtn").click()
    expect(page.locator("#runStatus")).to_have_text("Succeeded.", timeout=30_000)

    table = page.locator("#resultTable")
    expect(table.locator("tbody tr")).to_have_count(3, timeout=15_000)
    preview = table.inner_text().lower()
    assert any(name in preview for name in ("gadget", "widget", "sprocket")), preview
    expect(page.locator("#resultMeta")).to_contain_text("receipt")

    summary = page.locator("#receiptSummary")
    expect(summary).to_contain_text("Receipt")
    expect(summary.locator("dd.mono").first).not_to_be_empty()
    expect(page.locator("#copyReceiptBtn")).to_be_enabled()


def test_run_control_has_accessible_description(page: Page, live_node: str) -> None:
    page.goto(f"{live_node}/ui", wait_until="domcontentloaded")
    run = page.locator("#runBtn")
    expect(run).to_have_attribute("aria-describedby", "tip-run")
    run.focus()
    tip = page.locator("#tip-run")
    expect(tip).to_be_visible()
    expect(tip).to_contain_text("receipt")
