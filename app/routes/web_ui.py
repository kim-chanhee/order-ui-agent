"""웹 셸 HTML과 정적 파일 경로.

`server.py`가 `STATIC_DIR`을 `/static`에 마운트하고,
`api.py`의 `/`가 `INDEX_HTML`을 그대로 돌려준다.
"""

from __future__ import annotations

from pathlib import Path


UI_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = UI_DIR / "templates"
STATIC_DIR = UI_DIR / "static"
INDEX_TEMPLATE = TEMPLATES_DIR / "index.html"


def load_index_html() -> str:
    """앱 셸 HTML을 읽는다. 기동 시 한 번만 불러 INDEX_HTML에 둔다."""

    return INDEX_TEMPLATE.read_text(encoding="utf-8")


INDEX_HTML = load_index_html()
