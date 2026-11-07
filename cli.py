#!/usr/bin/env python3
"""Command line version of Yomitan CSS Dedup, for use without the add-on.

Close Anki first. Run with Anki's own Python so the `anki` package matches:
    ~/.local/share/AnkiProgramFiles/.venv/bin/python cli.py          # dry run
    ~/.local/share/AnkiProgramFiles/.venv/bin/python cli.py --apply  # write
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from anki.collection import Collection  # noqa: E402

from dedup import apply_plan, plan_notetype  # noqa: E402


def anki_running() -> bool:
    try:
        return subprocess.run(["pgrep", "-x", "anki"], capture_output=True).returncode == 0
    except FileNotFoundError:  # no pgrep (Windows): rely on the user having closed Anki
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--collection", default=str(Path.home() / ".local/share/Anki2/User 1/collection.anki2"))
    ap.add_argument("--notetype", action="append", help="note type to process (repeatable, default: Yomitan)")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--no-vacuum", action="store_true")
    args = ap.parse_args()

    path = Path(args.collection)
    if args.apply and anki_running():
        sys.exit("Anki is running. Close it first.")
    if args.apply and not args.no_backup:
        backup = path.with_name(f"collection.before-yomitan-css-dedup-{time.strftime('%Y%m%d-%H%M%S')}.anki2")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")

    size_before = path.stat().st_size
    col = Collection(str(path))
    try:
        for name in args.notetype or ["Yomitan"]:
            notetype = col.models.by_name(name)
            if notetype is None:
                sys.exit(f"Note type {name!r} not found")
            plan = plan_notetype(col, notetype)
            print(plan.summary())
            if args.apply and plan.has_changes:
                apply_plan(col, plan)
                css_copy = path.with_name(f"yomitan-css-dedup-{name}.css")
                css_copy.write_text(plan.extracted_css(), encoding="utf-8")
                print(f"Copy of the extracted CSS: {css_copy}")
        if not args.apply:
            print("Dry run, nothing written. Re-run with --apply.")
        elif not args.no_vacuum:
            col.optimize()
    finally:
        col.close(downgrade=False)

    if args.apply:
        print(f"collection.anki2: {size_before / 1e6:.1f} MB -> {path.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
