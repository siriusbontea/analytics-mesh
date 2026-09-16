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
    getting_started = page.locator("#help-getting-started")
    expect(getting_started).to_be_visible()
    expect(getting_started).to_contain_text("Getting started")
    page.locator('[data-help-nav="concepts"]').click()
    concepts = page.locator("#help-concepts")
    expect(concepts).to_be_visible()
    expect(concepts).to_contain_text("Concepts")

    page.locator("#helpClose").click()
    expect(drawer).to_be_hidden()

    help_btn.click()
    expect(drawer).to_be_visible()
    page.keyboard.press("Escape")
    expect(drawer).to_be_hidden()


def test_run_top_products_shows_preview_and_receipt(page: Page, live_node: str) -> None:
    page.goto(f"{live_node}/ui", wait_until="domcontentloaded")
    expect(page.locator("#askWrap")).to_be_visible()
    page.locator("#advancedWrap").locator("summary").click()
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


def test_upload_zone_visible_and_csv_becomes_table(page: Page, live_node: str, tmp_path) -> None:
    page.goto(f"{live_node}/ui", wait_until="domcontentloaded")
    zone = page.locator("#uploadZone")
    browse = page.locator("#uploadBrowse")
    expect(zone).to_be_visible()
    expect(browse).to_be_visible()
    expect(browse).to_have_text("Browse")
    expect(page.locator("#tip-upload")).to_contain_text("selected node")

    csv_path = tmp_path / "upload_demo.csv"
    csv_path.write_text("item,qty\napple,3\n", encoding="utf-8")
    page.locator("#uploadFile").set_input_files(str(csv_path))
    expect(page.locator("#uploadStatus")).to_contain_text("upload_demo", timeout=20_000)
    expect(page.locator("#connectorsList")).to_contain_text("upload_demo", timeout=15_000)


def test_run_control_has_accessible_description(page: Page, live_node: str) -> None:
    page.goto(f"{live_node}/ui", wait_until="domcontentloaded")
    page.locator("#advancedWrap").locator("summary").click()
    run = page.locator("#runBtn")
    expect(run).to_have_attribute("aria-describedby", "tip-run")
    run.focus()
    tip = page.locator("#tip-run")
    expect(tip).to_be_visible()
    expect(tip).to_contain_text("receipt")


def test_ask_mode_is_default_and_model_chip_none(page: Page, live_node: str) -> None:
    page.goto(f"{live_node}/ui", wait_until="domcontentloaded")
    expect(page.locator("#askWrap")).to_be_visible()
    expect(page.locator("#question")).to_be_visible()
    expect(page.locator("#askBtn")).to_be_visible()
    expect(page.locator("#askBtn")).to_have_text("Ask")
    expect(page.locator("#confirmSqlBtn")).to_be_visible()
    expect(page.locator("#confirmSqlBtn")).to_be_disabled()
    expect(page.locator("#proposedSqlView")).to_be_hidden()
    expect(page.locator("#advancedWrap")).to_be_visible()
    expect(page.locator("#advancedWrap")).not_to_have_attribute("open", "")
    expect(page.locator("#runBtn")).to_be_hidden()
    chip = page.locator("#modelChip")
    expect(chip).to_be_visible()
    expect(chip).to_have_text("None")
    expect(page.locator("#tip-ask")).to_contain_text("never auto-exec")
    expect(page.locator("#tip-confirm")).to_contain_text("Confirm")
    expect(page.locator("#tip-proposed-sql")).to_contain_text("SQL")
    expect(page.locator("#tip-model-chip")).to_contain_text("node-with-grok.yaml")


def test_ask_matching_analytic_confirm_runs(page: Page, live_node: str) -> None:
    page.goto(f"{live_node}/ui", wait_until="domcontentloaded")
    expect(page.locator("#analytic").locator("option[value='top_products']")).to_have_count(1, timeout=15_000)
    page.locator("#question").fill("what are the top products?")
    page.locator("#askBtn").click()
    expect(page.locator("#analyticMatch")).to_be_visible()
    expect(page.locator("#analyticMatch")).to_contain_text("top_products")
    expect(page.locator("#proposedSqlView")).to_be_hidden()
    expect(page.locator("#confirmSqlBtn")).to_be_enabled()
    page.locator("#confirmSqlBtn").click()
    expect(page.locator("#runStatus")).to_have_text("Succeeded.", timeout=30_000)
    preview = page.locator("#resultTable").inner_text().lower()
    assert any(name in preview for name in ("gadget", "widget", "sprocket")), preview


def test_ask_without_match_shows_configure_models(page: Page, live_node: str) -> None:
    page.goto(f"{live_node}/ui", wait_until="domcontentloaded")
    page.locator("#question").fill("how many rows are in sales?")
    page.locator("#askBtn").click()
    expect(page.locator("#askEmpty")).to_be_visible()
    expect(page.locator("#askEmpty")).to_contain_text("node-with-models.yaml")
    expect(page.locator("#askEmpty")).to_contain_text("node-with-grok.yaml")
    expect(page.locator("#confirmSqlBtn")).to_be_disabled()


def test_ask_propose_then_confirm_with_stubbed_assist(page: Page, live_node: str) -> None:
    page.route(
        "**/assist/nl2sql",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"used":true,"confirmed":false,"question":"how many rows are in sales?","sql":"SELECT product, SUM(amount) AS total FROM sales GROUP BY product","message":"Proposed SQL only. Confirm explicitly before running; this endpoint never executes SQL.","model_provider":"local","model_id":"stub-sql"}',
        ),
    )
    page.goto(f"{live_node}/ui", wait_until="domcontentloaded")
    page.locator("#question").fill("how many rows are in sales?")
    page.locator("#askBtn").click()
    expect(page.locator("#proposedSqlView")).to_be_visible()
    expect(page.locator("#proposedSqlView")).to_contain_text("FROM sales")
    expect(page.locator("#confirmSqlBtn")).to_be_enabled()
    expect(page.locator("#askEmpty")).to_be_hidden()
    page.locator("#confirmSqlBtn").click()
    expect(page.locator("#runStatus")).to_have_text("Succeeded.", timeout=30_000)
    expect(page.locator("#resultTable").locator("tbody tr")).to_have_count(3, timeout=15_000)
