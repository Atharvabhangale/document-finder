"""Manual lexical-search CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .lexical import search_lexical


def main() -> int:
    parser = argparse.ArgumentParser(description="Search the local document-finder FTS5 index.")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    print(json.dumps(search_lexical(args.query, args.limit, args.database), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
