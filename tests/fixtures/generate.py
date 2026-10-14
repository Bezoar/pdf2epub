"""Regenerate the synthetic fixtures: ``uv run python tests/fixtures/generate.py [OUT_DIR]``.

With no argument the committed fixtures under ``tests/fixtures/`` are rewritten in place.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from fixturegen import generate_all  # noqa: E402


def main(argv: list[str]) -> int:
    out_dir = Path(argv[0]) if argv else HERE
    for path in generate_all(out_dir):
        print(path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
