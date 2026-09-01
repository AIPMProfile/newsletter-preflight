"""What the browser actually builds.

Every other test here checks Python, or greps the HTML the server sends. Neither
can see the page: the problem list is assembled by JavaScript after load, so a
function that throws on its first line leaves an empty panel and passes every
check in the suite. That happened - `title()` was undefined for a while and the
list rendered blank while the header still claimed seven problems.

Chrome's `--dump-dom` runs the page and prints the resulting DOM, which is
enough to assert the thing a creator would actually see. Skipped when Chrome is
absent, so CI stays green without it.
"""

import json
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

CHROME = next((p for p in [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
] if p and Path(p).exists()), None)

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chrome available")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def served() -> str:
    """The real app on a real socket - Chrome cannot talk to a TestClient."""
    import uvicorn

    from preflight.web.app import create_app

    port = _free_port()
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def _dom(url: str) -> str:
    out = subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--no-sandbox",
         "--virtual-time-budget=9000", "--dump-dom", url],
        capture_output=True, text=True, timeout=90,
    )
    return out.stdout


def _rows(dom: str) -> list[str]:
    # The script source contains the row template too; only count real elements.
    body = dom.split("<script>")[0]
    return re.findall(r'<span class="nm">([^<]*)</span>', body)


def test_the_problem_list_actually_renders(served):
    """A blank panel is indistinguishable from "nothing is wrong with your email"."""
    rows = _rows(_dom(served + "/"))
    assert rows, "the problem list rendered empty"
    assert any("dark mode" in r for r in rows), rows


def test_header_count_matches_the_rows_it_summarises(served):
    """"7 things to look at" over six rows means a real problem is invisible.

    It was: findings with nowhere to point - a missing preview line - were
    dropped from the list because they could not be highlighted.
    """
    dom = _dom(served + "/")
    head = re.search(r'id="ptitle"[^>]*>([^<]*)<', dom)
    assert head, "no header"
    claimed = int(re.match(r"\s*(\d+)", head.group(1)).group(1))
    assert claimed == len(_rows(dom)), f"{head.group(1)!r} but {len(_rows(dom))} rows"


def test_override_reasons_start_closed(served):
    """`display:flex` outranks the user-agent rule for [hidden].

    They were open on load, so every row shouted three choices nobody asked for.
    """
    dom = _dom(served + "/")
    body = dom.split("<script>")[0]
    for block in re.findall(r'<div class="reasons"[^>]*>', body):
        assert "hidden" in block, f"override reasons open by default: {block}"


def test_the_page_reports_no_script_errors(served):
    """An exception on load is why the panel was blank and nothing said so."""
    # Only the body: the guard's own source lives in the <script> tag.
    body = _dom(served + "/").split("<script>")[0].lower()
    assert "something went wrong showing these" not in body, "the render guard fired"
    assert "loading your broadcast" not in body, "the page never got past its loading state"
