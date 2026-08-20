"""Command-line entry point for upgrading a portable local save."""

from __future__ import annotations

import argparse

from .persistence import SaveError, migrate_save_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate a Blood Bound local save to the current schema.")
    parser.add_argument("source", help="existing .json or .gz save")
    parser.add_argument("target", help="destination .json or .gz save")
    arguments = parser.parse_args()
    try:
        migrate_save_file(arguments.source, arguments.target)
    except SaveError as error:
        parser.error(f"{error.code}: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
