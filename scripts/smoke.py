"""Fetch, hash-check and convert the real-world smoke set (TST-R9 to TST-R12).

The set is described by ``tests/corpus/smoke.toml``. Files are downloaded into a cache
outside git (default ``~/.cache/pdf2epub-corpus/``) and checked against their pinned
SHA-256; a cached file whose hash matches is reused. A download whose hash differs is kept
aside and reported as "upstream file changed"; the entry is skipped, on this run and later
ones, until someone reviews the new file and re-pins it (or deletes the kept copy to check
again). A network failure skips the entry with a message; neither is a smoke failure.
Derived entries (S15) are generated locally from their source entry.

``run`` then converts every available file with pdf2epub, as one batch with the test
passwords supplied through a password map, and compares each conversion with its
``expect``. Entries with ``expect_without_password`` are also run once more, in a second
batch with no passwords. Entries marked ``must_trust`` must have no page whose text layer
was rejected (TST-R4); every rejected page of every entry is listed either way.

Usage::

    uv run python scripts/smoke.py fetch [--only S1,S4]
    uv run python scripts/smoke.py run [--only S1,S4] [--out DIR] [-- PDF2EPUB-OPTIONS...]

``run`` exits 1 when a conversion does not meet its expectation (or pdf2epub fails to run),
else 0. Skipped entries never fail the run. The smoke workflow
(``.github/workflows/smoke.yml``) runs it by hand only; it never gates a pull request.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "tests" / "corpus" / "smoke.toml"
CACHE = Path.home() / ".cache" / "pdf2epub-corpus"
CHUNK = 1 << 20
NETWORK_TIMEOUT = 60
CONVERSION_TIMEOUT = 4 * 60 * 60
"""Seconds per conversion; the scanned books OCR hundreds of pages (pdf2epub's default is
30 minutes)."""
USER_AGENT = "pdf2epub-smoke (+https://github.com/Bezoar/pdf2epub)"


@dataclass(frozen=True)
class Expectation:
    outcome: str
    issues: tuple[str, ...] = ()
    ocr: bool = False

    def describe(self) -> str:
        parts = [self.outcome, *(f"with {issue}" for issue in self.issues)]
        if self.ocr:
            parts.append("with OCR")
        return " ".join(parts)


@dataclass(frozen=True)
class Entry:
    id: str
    url: str | None
    sha256: str | None
    derived_from: str | None
    fraction: float
    password: str | None
    expect: tuple[Expectation, ...]
    expect_without_password: str | None
    must_trust: bool

    @property
    def file_name(self) -> str:
        return f"{self.id}.pdf"


@dataclass
class Status:
    """What happened to one entry on this run."""

    entry: Entry
    path: Path | None = None
    skipped: str | None = None
    result: dict[str, Any] | None = None
    without_password: dict[str, Any] | None = None
    problems: list[str] = field(default_factory=list)


def load_manifest(path: Path) -> list[Entry]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    entries = []
    for raw in data["entries"]:
        expect = raw["expect"]
        alternatives = expect if isinstance(expect, list) else [expect]
        derived = raw.get("derived")
        entries.append(
            Entry(
                id=raw["id"],
                url=raw.get("url"),
                sha256=raw.get("sha256"),
                derived_from=None if derived is None else derived["from"],
                fraction=1.0 if derived is None else float(derived["fraction"]),
                password=raw.get("password"),
                expect=tuple(
                    Expectation(
                        outcome=alt["outcome"],
                        issues=tuple(alt.get("issues", ())),
                        ocr=bool(alt.get("ocr", False)),
                    )
                    for alt in alternatives
                ),
                expect_without_password=raw.get("expect_without_password"),
                must_trust=bool(raw.get("must_trust", False)),
            )
        )
    return entries


def say(text: str) -> None:
    print(text, flush=True)


# --- fetching ---------------------------------------------------------------------------


def fetch(entries: list[Entry], cache: Path) -> dict[str, Status]:
    """Download (or reuse) every entry and derive the derived ones, keyed by entry id."""
    cache.mkdir(parents=True, exist_ok=True)
    statuses = {entry.id: Status(entry) for entry in entries}
    for entry in entries:
        if entry.derived_from is None:
            fetch_one(statuses[entry.id], cache)
    for entry in entries:
        if entry.derived_from is not None:
            derive(statuses[entry.id], statuses.get(entry.derived_from), cache)
    return statuses


def fetch_one(status: Status, cache: Path) -> None:
    entry = status.entry
    assert entry.url is not None and entry.sha256 is not None
    cached = cache / f"{entry.sha256}.pdf"
    changed = cache / "changed" / f"{entry.sha256}.pdf"
    if cached.is_file() and sha256_of(cached) == entry.sha256:
        status.path = cached
        say(f"{entry.id}: cached")
        return
    if changed.is_file():
        status.skipped = (
            f"upstream file changed: it now has SHA-256 {sha256_of(changed)}, not the pinned "
            f"{entry.sha256}; review {changed} and re-pin the entry, or delete that file to "
            "check again"
        )
        say(f"{entry.id}: skipped, {status.skipped}")
        return
    partial = cache / f".{entry.sha256}.partial"
    try:
        digest = download(entry.url, partial)
    except (OSError, urllib.error.URLError, http.client.HTTPException) as error:
        partial.unlink(missing_ok=True)
        status.skipped = f"unreachable: {entry.url}: {describe_error(error)}"
        say(f"{entry.id}: skipped, {status.skipped}")
        return
    if digest != entry.sha256:
        changed.parent.mkdir(exist_ok=True)
        partial.replace(changed)
        status.skipped = (
            f"upstream file changed: it now has SHA-256 {digest}, not the pinned "
            f"{entry.sha256}; review {changed} and re-pin the entry"
        )
        say(f"{entry.id}: skipped, {status.skipped}")
        return
    partial.replace(cached)
    status.path = cached
    say(f"{entry.id}: downloaded")


def download(url: str, destination: Path) -> str:
    """Write ``url`` to ``destination``; return its SHA-256."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    with (
        urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response,
        destination.open("wb") as out,
    ):
        while chunk := response.read(CHUNK):
            digest.update(chunk)
            out.write(chunk)
    return digest.hexdigest()


def describe_error(error: BaseException) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"HTTP {error.code} {error.reason}"
    if isinstance(error, urllib.error.URLError):
        return str(error.reason)
    return str(error) or type(error).__name__


def derive(status: Status, source: Status | None, cache: Path) -> None:
    entry = status.entry
    if source is None or source.path is None:
        status.skipped = f"its source {entry.derived_from} is not available"
        say(f"{entry.id}: skipped, {status.skipped}")
        return
    data = source.path.read_bytes()
    folder = cache / "derived"
    folder.mkdir(exist_ok=True)
    path = folder / f"{source.entry.sha256}-{entry.fraction}.pdf"
    path.write_bytes(data[: int(len(data) * entry.fraction)])
    status.path = path
    say(f"{entry.id}: derived from {source.entry.id}")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


# --- converting -------------------------------------------------------------------------


def convert(statuses: dict[str, Status], out: Path, timeout: int, extra: list[str]) -> int | None:
    """Run the batch and the no-password batch; return the first batch's exit code (None if
    there was nothing to convert)."""
    ready = [s for s in statuses.values() if s.path is not None]
    if not ready:
        return None
    for folder in ("inputs", "no-password", "epub"):
        shutil.rmtree(out / folder, ignore_errors=True)
        (out / folder).mkdir(parents=True)
    passwords = out / "passwords.toml"
    lines = [
        f"{json.dumps('inputs/' + s.entry.file_name)} = {json.dumps(s.entry.password)}"
        for s in ready
        if s.entry.password is not None
    ]
    passwords.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    passwords.chmod(0o600)
    for status in ready:
        assert status.path is not None
        place(status.path, out / "inputs" / status.entry.file_name)
    say(f"\nConverting {len(ready)} file(s) as one batch into {out / 'epub'}")
    code, results = run_pdf2epub(
        [
            "--password-map",
            str(passwords),
            "--report",
            str(out / "report.json"),
            "-o",
            str(out / "epub"),
            str(out / "inputs"),
        ],
        timeout,
        extra,
    )
    for status in ready:
        status.result = results.get(status.entry.file_name)
    locked = [s for s in ready if s.entry.expect_without_password is not None]
    if locked:
        for status in locked:
            assert status.path is not None
            place(status.path, out / "no-password" / status.entry.file_name)
        say(f"\nConverting {len(locked)} file(s) again with no password")
        _, results = run_pdf2epub(
            ["-o", str(out / "epub"), str(out / "no-password")], timeout, extra
        )
        for status in locked:
            status.without_password = results.get(status.entry.file_name)
    return code


def place(source: Path, destination: Path) -> None:
    """Put ``source`` at ``destination`` as a hard link, or a copy across file systems."""
    try:
        os.link(source, destination)
    except OSError:
        shutil.copyfile(source, destination)


def run_pdf2epub(
    arguments: list[str], timeout: int, extra: list[str]
) -> tuple[int, dict[str, dict[str, Any]]]:
    """Run pdf2epub with ``--json``; return its exit code and each conversion's result,
    keyed by its source file's name."""
    command = [
        sys.executable,
        "-m",
        "pdf2epub",
        "--json",
        "--overwrite",
        "--timeout",
        str(timeout),
        *extra,
        *arguments,
    ]
    results: dict[str, dict[str, Any]] = {}
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True, encoding="utf-8") as proc:
        assert proc.stdout is not None
        for event in events(proc.stdout):
            if event.get("type") == "conversion_finished":
                name = Path(event["source"]).name
                results[name] = event
                issues = ", ".join(issue_label(i) for i in event["issues"]) or "no issues"
                say(f"  {name}: {event['outcome']} in {event['duration']:.0f} s ({issues})")
    return proc.returncode, results


def events(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            say(f"  (not an event: {line.rstrip()})")
            continue
        if isinstance(event, dict):
            yield event


def issue_label(issue: dict[str, Any]) -> str:
    reason = issue.get("reason")
    return f"{issue['code']}:{reason}" if reason else str(issue["code"])


# --- comparing --------------------------------------------------------------------------


def compare(status: Status) -> None:
    """Fill ``status.problems`` with every way the conversions missed their expectations."""
    entry, result = status.entry, status.result
    if status.skipped is not None:
        return
    if result is None:
        status.problems.append("pdf2epub reported no result for it")
        return
    misses = [miss for alt in entry.expect if (miss := mismatch(alt, result))]
    if len(misses) == len(entry.expect):
        wanted = " or ".join(alt.describe() for alt in entry.expect)
        status.problems.append(f"expected {wanted}; {'; '.join(misses)}")
    rejected = rejected_pages(result)
    if entry.must_trust and rejected:
        status.problems.append(f"must-trust text layer rejected: {format_rejected(rejected)}")
    if entry.expect_without_password is not None:
        bare = status.without_password
        codes = [] if bare is None else [str(i["code"]) for i in bare["issues"]]
        if (
            bare is None
            or bare["outcome"] != "failed"
            or entry.expect_without_password not in codes
        ):
            got = "no result" if bare is None else f"{bare['outcome']} with {codes}"
            status.problems.append(
                f"without a password expected failed with {entry.expect_without_password}; "
                f"got {got}"
            )


def mismatch(expected: Expectation, result: dict[str, Any]) -> str | None:
    """Why ``result`` does not meet ``expected``, or None if it does."""
    labels = {issue_label(issue) for issue in result["issues"]}
    codes = {str(issue["code"]) for issue in result["issues"]}
    if result["outcome"] != expected.outcome:
        return f"got {result['outcome']} ({', '.join(sorted(labels)) or 'no issues'})"
    missing = [i for i in expected.issues if i not in (labels if ":" in i else codes)]
    if missing:
        return f"missing {', '.join(missing)}"
    if expected.ocr and result.get("ocr") is None:
        return "OCR did not run"
    return None


def rejected_pages(result: dict[str, Any]) -> dict[str, list[int]]:
    """The pages whose text layer was rejected, by reason."""
    return {
        str(issue["reason"]): list(issue["pages"])
        for issue in result["issues"]
        if issue["code"] == "text_layer_rejected"
    }


def format_rejected(rejected: dict[str, list[int]]) -> str:
    return "; ".join(f"{reason} on pages {pages}" for reason, pages in sorted(rejected.items()))


def report(statuses: dict[str, Status]) -> int:
    say("\nSmoke set results")
    failed = 0
    for status in statuses.values():
        compare(status)
        entry = status.entry
        if status.skipped is not None:
            say(f"  {entry.id}: SKIPPED ({status.skipped})")
            continue
        verdict = "FAIL" if status.problems else "ok"
        failed += bool(status.problems)
        outcome = "-" if status.result is None else status.result["outcome"]
        say(f"  {entry.id}: {verdict} ({outcome})")
        for problem in status.problems:
            say(f"      {problem}")
        if status.result is not None and (rejected := rejected_pages(status.result)):
            say(f"      text layer rejected: {format_rejected(rejected)}")
    skipped = sum(s.skipped is not None for s in statuses.values())
    checked = len(statuses) - skipped
    say(f"\n{checked - failed} of {checked} checked entries met expectations; {skipped} skipped")
    return 1 if failed else 0


# --- command line -----------------------------------------------------------------------


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--manifest", type=Path, default=MANIFEST, help="the smoke manifest")
    common.add_argument("--cache", type=Path, default=CACHE, help=f"the cache (default {CACHE})")
    common.add_argument("--only", help="comma-separated entry ids to use (default: all)")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fetch", parents=[common], help="download and check the files only")
    run = commands.add_parser("run", parents=[common], help="fetch, convert as one batch, compare")
    run.add_argument(
        "--out", type=Path, help="the folder for inputs, EPUBs and the report (default: CACHE/run)"
    )
    run.add_argument(
        "--timeout",
        type=int,
        default=CONVERSION_TIMEOUT,
        help=f"seconds per conversion (default {CONVERSION_TIMEOUT})",
    )
    run.add_argument("extra", nargs="*", help="more pdf2epub options, after --")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_arguments(argv)
    entries = load_manifest(args.manifest)
    if args.only:
        wanted = {name.strip() for name in args.only.split(",")}
        unknown = wanted - {e.id for e in entries}
        if unknown:
            say(f"unknown entries: {', '.join(sorted(unknown))}")
            return 2
        needed = wanted | {e.derived_from for e in entries if e.id in wanted and e.derived_from}
        entries = [e for e in entries if e.id in needed]
    else:
        wanted = {e.id for e in entries}
    statuses = fetch(entries, args.cache)
    if args.command == "fetch":
        return 0
    chosen = {key: status for key, status in statuses.items() if key in wanted}
    code = convert(chosen, args.out or args.cache / "run", args.timeout, args.extra)
    result = report(chosen)
    if code not in (None, 0, 1):
        say(f"pdf2epub exited with code {code}")
        return 1
    return result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
