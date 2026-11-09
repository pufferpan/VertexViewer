"""Convenience launcher: `python .` / `python __main__.py` from the project root."""

from __future__ import annotations

from app.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
