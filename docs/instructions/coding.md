# Coding instructions

These rules apply to every change in this repository. They are instructions, not specification: what pdf2epub does is defined in [`docs/specs/`](../specs/main.md), and these rules govern how code and tests are written. "Must" and "must not" are binding; anything else is guidance.

## 1. Tooling

- Python ≥ 3.12. Source code lives in `src/pdf2epub/`; tests live in `tests/`.
- **uv** manages the environment, the lockfile (`uv.lock`, committed) and every tool run. You must not use bare `pip` or `python -m venv`.
- **hatchling** is the build backend.
- **ruff** lints and formats; **mypy** runs with `--strict`.
- **pytest** runs the tests; **hypothesis** is used for invariants (for example, "de-hyphenation never changes the number of non-hyphen letters").
- **coverage.py** measures branch coverage (`branch = true`, `fail_under = 75`).
- **pre-commit** runs ruff and mypy before each commit.

## 2. Commands

| Task | Command |
|---|---|
| Set up or refresh the environment | `uv sync` |
| Install the git hooks (once per clone) | `uv run pre-commit install` |
| Lint | `uv run ruff check .` |
| Check formatting | `uv run ruff format --check .` |
| Apply formatting | `uv run ruff format .` |
| Type-check | `uv run mypy` |
| Run all tests (in parallel, one pytest-xdist worker per CPU) | `uv run pytest` |
| Run one test (`-n 0`: in one process, without starting workers) | `uv run pytest -n 0 tests/api/test_passwords.py::test_wrong_password` |
| Tests with branch coverage | `uv run coverage run -m pytest && uv run coverage report` |
| Run the CLI from the checkout | `uv run pdf2epub --help` |
| Check runtime dependency licences ([§9](#9-dependencies)) | `uv run python scripts/licence_check.py` |
| Fetch the real-world smoke set | `uv run python scripts/smoke.py fetch` |
| Fetch, convert and check the smoke set (hours: the scans are OCR'd; `--only S4,S15` picks entries, pdf2epub options go after `--`) | `uv run python scripts/smoke.py run` |

Before pushing, you must run lint, the format check, mypy and the full test suite locally, and all must pass.

## 3. Red-green cycle

Every behaviour change is test-first. For each acceptance criterion (AC) in the ticket:

1. Pick the next AC from the ticket.
2. Write **one** test at a seam listed in the seam catalogue of [`docs/plans/v1.md`](../plans/v1.md). Mark it `@pytest.mark.ac("<AC ID>")`, for example `@pytest.mark.ac("PWD-AC3")`.
3. Run it and see it fail **for the expected reason**: an assertion about the missing behaviour, not an import error, a typo or a fixture failure.
4. Write the least code that makes it pass.
5. Refactor only while every test is green.
6. Repeat until every non-manual spec AC in the ticket has a marked, passing test, and remove those AC IDs from the pending-AC list `tests/ac_pending.txt` in the same PR ([TST-R20](../specs/testing.md#tst-r20)); the marker gate fails while a marked AC is still listed. Manual ACs are confirmed in the v1 acceptance ticket, and a ticket's local ACs (no spec ID) as the ticket describes.

Commit history does not have to show the red step; the rule is still binding.

A test may verify several ACs (one marker per AC), and an AC may have several tests. You must not add a test at a seam outside the catalogue. If one is needed, stop and escalate (see [github.md §5](github.md#5-escalation)): it needs a plan amendment.

## 4. Tests that don't count: tautological tests

A tautological test passes whatever the code does, so it proves nothing. You must not write one, and you must delete or rewrite any you find. A test is tautological if **any** of these is true:

- **(a)** Its expected value comes from the code under test, or from a copy of that code's logic.
- **(b)** It mocks or patches the unit under test. Fakes are allowed only at seams in the catalogue, for example a fake `OcrEngine` or a scripted `PasswordProvider`.
- **(c)** It only checks that a mock was called with the arguments the test itself passed in.
- **(d)** It has no assertion, or its only assertions are "no exception was raised", `is not None`, or a type check.
- **(e)** It compares against a snapshot or golden file that the code generated and nobody checked by hand.

Before opening the PR, ask this of every new test: **"Would this test fail if the behaviour it names broke?"** If you can't say yes and name the breakage, rewrite it.

Expected values come from the spec (exact issue codes, exit codes, event fields) or from fixtures whose ground truth is known independently (generated text, provenance-checked files).

## 5. Coverage

- Branch coverage is measured over **all** of `src/pdf2epub`, with nothing listed under `omit`.
- The measured CI job runs on Linux x86-64 with Python 3.13 and has Tesseract installed, so the OCR paths count.
- Coverage follows subprocesses: the xdist workers, the CLI and pdf2epub's own workers. The job moved from Python 3.12 to 3.13 by owner decision in [#73](https://github.com/Bezoar/pdf2epub/issues/73): under 3.12's `sys.settrace`, every measured process spent about 10 s importing pypdf's glyph table (0.7 s on 3.13), which made the job take over 45 minutes. For the same reason, prefer Python 3.13 for a local coverage run.
- The bar is a floor: `fail_under = 75`, with no ratchet. A PR may lower coverage as long as it stays at or above 75%.
- `# pragma: no cover` is allowed **only** on:
  - `if TYPE_CHECKING:` blocks;
  - the `if __name__ == "__main__":` guard;
  - `raise NotImplementedError` in protocol or abstract method bodies.

  Any other pragma must have a one-line justification comment on the same line, and the PR body must list it.

## 6. Test layout

- Tests are organised by seam:

  | Folder | Seam |
  |---|---|
  | `tests/api/` | Python API + event sink (`plan_batch` / `run_batch`); the default for most AC tests |
  | `tests/cli/` | the CLI as a subprocess (`--json` and human output, exit codes) |
  | `tests/ocr/` | the `OcrEngine` protocol (fake engine, and real Tesseract) |
  | `tests/epub/` | the EPUB on disk (read back, epubcheck) |
  | `tests/fixtures/` | fixture generators, committed fixtures, the public-domain sample and its `PROVENANCE.md` |
  | `tests/repo/` | repository and CI tooling: the AC-marker gate, workflow definitions, README and `--help` text, built package metadata, the smoke script |

  `PasswordProvider` tests live with the API tests that drive them.
- Tests that need the real Tesseract binary must be marked `@pytest.mark.tesseract`. Locally they skip with a visible reason when Tesseract is missing. In the CI coverage job a skipped `tesseract` test fails the job.
- Tests must not reach any external network. A loopback server bound to 127.0.0.1 and started by the test itself is allowed (for example, to exercise the smoke-set downloader). Real-world smoke-set files are never used by the regular suite; they run only in the manual smoke workflow ([testing spec](../specs/testing.md)).
- Fixtures are generated deterministically. The first ticket that needs a fixture creates it; later tickets reuse it without changing what it means (see the plan's fixture table).

## 7. Writing code

- Use the vocabulary in [`GLOSSARY.md`](../../GLOSSARY.md) for names in code, messages and docs. For example: `Conversion`, not `Job`; `Outcome`, not `Status`.
- Public functions and classes must be fully typed; mypy `--strict` must pass with no `type: ignore` unless it carries a justification comment.
- Password values must only ever be held in the `Secret` type ([api spec](../specs/api.md)). You must not call `Secret.reveal()` except at the point where the value is handed to the PDF library or written to the worker pipe.
- Free-text diagnostics go through `logging` to stderr. Anything a user must act on is an **issue**, never just a log line.
- No network access, no telemetry, and no PDF JavaScript execution anywhere in the code ([main spec](../specs/main.md#main-r18)).

## 8. Spec gaps

The specs are normative; tickets and PRs are not.

1. If the spec doesn't cover something you need, you may add a requirement or AC to the owning spec with a **new** ID (the next free number), plus a marked test. List it under **Spec changes** in the PR body.
2. You must never renumber, reuse or delete an existing ID.
3. If a change would alter the **meaning** of an existing requirement or AC, stop and escalate ([github.md §5](github.md#5-escalation)). Do not merge.

## 9. Dependencies

1. A new **runtime** dependency must be MIT-compatible: MIT, BSD, Apache-2.0, ISC, PSF, HPND (Pillow's licence), or MPL-2.0 used unmodified.
2. Anything else must stop the session and escalate before the dependency is added. That includes GPL, LGPL, AGPL, OpenRAIL or other use-restricted model licences, unlicensed model weights, and anything with no licence.
3. **Dev-only** dependencies follow the same list, except that LGPL is allowed, because dev dependencies are never distributed.
4. Name every new runtime dependency, with its licence, in the PR body.
5. Add dependencies with `uv add` (or `uv add --dev`), so `pyproject.toml` and `uv.lock` change together.
6. Check the licence on the package's PyPI page and in its repository, then run `uv run python scripts/licence_check.py`. The **Dependency licences** CI job runs the same script on every PR. It walks every runtime dependency, direct or transitive (never the dev group), lists each one's declared licence and fails on any licence outside the allowlist:
   - SPDX identifiers `MIT`, `MIT-0`, `MIT-CMU`, `HPND`, `0BSD`, `BSD-2-Clause`, `BSD-3-Clause`, `Apache-2.0`, `ISC`, `PSF-2.0`, `Python-2.0` and `MPL-2.0`. An SPDX expression passes when it can be satisfied with these alone: every part of an `AND`, at least one side of an `OR`.
   - For a package with no SPDX expression, the matching `License :: OSI Approved :: …` trove classifiers.
7. A package whose declared licence is unknown, unclear or not an SPDX expression, or that combines an allowlisted licence with another permissive one, needs an **exception**: an entry in `EXCEPTIONS` in `scripts/licence_check.py` giving the exact licence text the package declares and a comment saying what the package and anything it bundles are licensed under, and why that is MIT-compatible. An exception covers only that text, so a release that declares a different licence fails the check again. Adding or changing an exception follows rules 1 and 2: name it in the PR body, and escalate anything outside the list in rule 1.
