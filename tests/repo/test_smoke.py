"""The real-world smoke set: its manifest (TST-R9, TST-R12, TST-R13) and ``scripts/smoke.py``
run against a loopback HTTP server started by the test (TST-R10). No test here touches
the real network or a real smoke-set file."""

import hashlib
import http.server
import re
import socket
import subprocess
import sys
import threading
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "tests" / "corpus" / "smoke.toml"
SMOKE = REPO / "scripts" / "smoke.py"
TESTING_SPEC = REPO / "docs" / "specs" / "testing.md"
FIXTURES = REPO / "tests" / "fixtures"
PASSWORDS = {"S10": "view", "S11": "master", "S12": "openpassword"}


def manifest_entries() -> list[dict[str, Any]]:
    entries = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))["entries"]
    assert isinstance(entries, list)
    return entries


def spec_table() -> dict[str, dict[str, str]]:
    """TST-R12's table, keyed by entry id: each row's fetch URL and SHA-256 cells, with the
    surrounding backticks removed."""
    text = TESTING_SPEC.read_text(encoding="utf-8")
    section = text.split('<a id="tst-r12">', 1)[1].split('<a id="tst-r13">', 1)[0]
    rows: dict[str, dict[str, str]] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and re.fullmatch(r"S\d+", cells[0]):
            rows[cells[0]] = {"url": cells[3].strip("`"), "sha256": cells[5].strip("`")}
    return rows


@pytest.mark.ac("TST-AC5")
def test_manifest_has_the_fifteen_entries_with_their_required_fields() -> None:
    entries = manifest_entries()
    assert [entry["id"] for entry in entries] == [f"S{n}" for n in range(1, 16)]
    for entry in entries:
        assert entry["license"], entry["id"]
        assert entry["expect"], entry["id"]
        if "derived" in entry:
            assert "url" not in entry and "sha256" not in entry, entry["id"]
        else:
            assert re.fullmatch(r"https://\S+", entry["url"]), entry["id"]
            assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]), entry["id"]


@pytest.mark.ac("TST-AC5")
def test_manifest_urls_and_hashes_match_the_spec_table() -> None:
    table = spec_table()
    assert sorted(table) == sorted(f"S{n}" for n in range(1, 16))
    for entry in manifest_entries():
        row = table[entry["id"]]
        if "derived" in entry:
            # S15 is the first 60% of the bytes of S4 (TST-R12); it has no URL or hash.
            assert row == {"url": "—", "sha256": "— (derived)"}
            assert entry["derived"] == {"from": "S4", "fraction": 0.6}
        else:
            assert (entry["url"], entry["sha256"]) == (row["url"], row["sha256"])


@pytest.mark.ac("TST-AC5")
def test_only_the_three_encrypted_entries_have_passwords() -> None:
    found = {entry["id"]: entry["password"] for entry in manifest_entries() if "password" in entry}
    assert found == PASSWORDS


@pytest.mark.ac("TST-AC8")
def test_no_manifest_url_uses_a_forbidden_source() -> None:
    for entry in manifest_entries():
        if "url" not in entry:
            continue
        host = (urlsplit(entry["url"]).hostname or "").lower()
        for forbidden in ("hathitrust.org", "books.google.com"):
            assert host != forbidden and not host.endswith("." + forbidden), entry["url"]
        assert "omnidocbench" not in entry["url"].lower(), entry["url"]


# --- scripts/smoke.py against a loopback server -------------------------------------------


@dataclass
class Server:
    """A loopback HTTP server serving ``files`` (path → bytes) and logging each request."""

    files: dict[str, bytes]
    requests: list[str] = field(default_factory=list)
    port: int = 0

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"


@pytest.fixture
def server() -> Iterator[Server]:
    state = Server(files={})

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state.requests.append(self.path)
            body = state.files.get(self.path)
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()


def refused_url() -> str:
    """A loopback URL on a port nothing listens on, so connecting is refused."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/gone.pdf"


def run_smoke(
    manifest: Path, cache: Path, out: Path, *extra: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SMOKE),
            "run",
            "--manifest",
            str(manifest),
            "--cache",
            str(cache),
            "--out",
            str(out),
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.mark.ac("TST-AC6")
def test_smoke_script_caches_verifies_and_skips_changed_and_unreachable_files(
    server: Server, tmp_path: Path
) -> None:
    good = (FIXTURES / "born-digital" / "two-pages.pdf").read_bytes()
    pinned = (FIXTURES / "born-digital" / "blank-page.pdf").read_bytes()
    changed = (FIXTURES / "born-digital" / "novel.pdf").read_bytes()
    server.files = {"/good.pdf": good, "/changed.pdf": changed}
    manifest = tmp_path / "smoke.toml"
    manifest.write_text(
        f"""
[[entries]]
id = "A"
url = "{server.url("/good.pdf")}"
sha256 = "{hashlib.sha256(good).hexdigest()}"
license = "test"
expect = {{ outcome = "converted" }}

[[entries]]
id = "B"
url = "{server.url("/changed.pdf")}"
sha256 = "{hashlib.sha256(pinned).hexdigest()}"
license = "test"
expect = {{ outcome = "converted" }}

[[entries]]
id = "C"
url = "{refused_url()}"
sha256 = "{"0" * 64}"
license = "test"
expect = {{ outcome = "converted" }}
""",
        encoding="utf-8",
    )
    cache, out = tmp_path / "cache", tmp_path / "out"

    first = run_smoke(manifest, cache, out)

    assert first.returncode == 0, first.stdout + first.stderr
    assert sorted(server.requests) == ["/changed.pdf", "/good.pdf"]
    assert (cache / f"{hashlib.sha256(good).hexdigest()}.pdf").read_bytes() == good
    assert (out / "epub" / "A.epub").is_file()
    lines = first.stdout.splitlines()
    assert "  A: ok (converted)" in lines
    assert any(line.startswith("  B: SKIPPED (upstream file changed") for line in lines)
    assert any(line.startswith("  C: SKIPPED (unreachable") for line in lines)
    assert not (out / "epub" / "B.epub").exists()

    second = run_smoke(manifest, cache, out)

    assert second.returncode == 0, second.stdout + second.stderr
    assert sorted(server.requests) == ["/changed.pdf", "/good.pdf"], "the second run downloaded"
    lines = second.stdout.splitlines()
    assert "A: cached" in lines
    assert "  A: ok (converted)" in lines
    assert any(line.startswith("  B: SKIPPED (upstream file changed") for line in lines)
    assert any(line.startswith("  C: SKIPPED (unreachable") for line in lines)


def test_smoke_script_fails_a_missed_expectation_and_a_rejected_must_trust_layer(
    server: Server, tmp_path: Path
) -> None:
    # The comparison half of TST-R10, and the smoke-set check of TST-R4: a conversion that
    # misses its `expect`, and a `must_trust` file whose text layer is rejected, fail the run.
    good = (FIXTURES / "born-digital" / "two-pages.pdf").read_bytes()
    garbled = (FIXTURES / "must-reject" / "garbled-layer.pdf").read_bytes()
    server.files = {"/good.pdf": good, "/garbled.pdf": garbled}
    manifest = tmp_path / "smoke.toml"
    manifest.write_text(
        f"""
[[entries]]
id = "D"
url = "{server.url("/good.pdf")}"
sha256 = "{hashlib.sha256(good).hexdigest()}"
license = "test"
expect = [{{ outcome = "failed" }}, {{ outcome = "converted", issues = ["repaired_pdf"] }}]

[[entries]]
id = "E"
url = "{server.url("/garbled.pdf")}"
sha256 = "{hashlib.sha256(garbled).hexdigest()}"
license = "test"
expect = {{ outcome = "converted" }}
must_trust = true
""",
        encoding="utf-8",
    )
    cache, out = tmp_path / "cache", tmp_path / "out"

    # `--ocr never` after `--` goes to pdf2epub: the rejected pages become page images
    # without running Tesseract.
    proc = run_smoke(manifest, cache, out, "--", "--ocr", "never")

    assert proc.returncode == 1, proc.stdout + proc.stderr
    lines = proc.stdout.splitlines()
    assert "  D: FAIL (converted)" in lines
    assert any(
        line.startswith("      expected failed or converted with repaired_pdf; got converted")
        and line.endswith("missing repaired_pdf")
        for line in lines
    ), proc.stdout
    assert "  E: FAIL (converted)" in lines
    assert any(
        line.startswith("      must-trust text layer rejected: ") and "pages [1, 2, 3, 4]" in line
        for line in lines
    ), proc.stdout
