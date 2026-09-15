from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

UI_PATH = Path(__file__).with_name("static") / "ui.html"


def ui_html() -> str:
    return UI_PATH.read_text(encoding="utf-8")


def mount_ui(app: FastAPI) -> None:
    def serve_ui() -> HTMLResponse:
        return HTMLResponse(ui_html())

    app.get("/", include_in_schema=False)(serve_ui)
    app.get("/ui", include_in_schema=False)(serve_ui)
