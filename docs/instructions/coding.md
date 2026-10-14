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
| Run all tests | `uv run pytest` |
| Run one test | `uv run pytest tests/api/test_passwords.py::test_wrong_password` |
| Tests with branch coverage | `uv run coverage run -m pytest && uv run coverage report` |
| Run the CLI from the checkout | `uv run pdf2epub --help` |
| Fetch the real-world smoke set | `uv run python scripts/smoke.py fetch` |

Before pushing, you must run lint, the format check, mypy and the full test suite locally, and all must pass.

## 3. Red-green cycle

Every behaviour change is test-first. For each acceptance criterion (AC) in the ticket:

1. Pick the next AC from the ticket.
2. Write **one** test at a seam listed in the seam catalogue of [`docs/plans/v1.md`](../plans/v1.md). Mark it `@pytest.mark.ac("<AC ID>")`, for example `@pytest.mark.ac("PWD-AC3")`.
3. Run it and see it fail **for the expected reason**: an assertion about the missing behaviour, not an import error, a typo or a fixture failure.
4. Write the least code that makes it pass.
5. Refactor only while every test is green.
6. Repeat until every AC in the ticket has a marked, passing test.

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
- The measured CI job runs on Linux with Python 3.12 and has Tesseract installed, so the OCR paths count.
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

  `PasswordProvider` tests live with the API tests that drive them.
- Tests that need the real Tesseract binary must be marked `@pytest.mark.tesseract`. Locally they skip with a visible reason when Tesseract is missing. In the CI coverage job a skipped `tesseract` test fails the job.
- Tests must not use the network. Real-world smoke-set files are never used by the regular suite; they run only in the manual smoke workflow ([testing spec](../specs/testing.md)).
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
6. There is no automated licence checker in v1. Check the licence on the package's PyPI page and in its repository.
