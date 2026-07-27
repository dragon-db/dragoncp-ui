#!/usr/bin/env python3
"""
Collapse stored rsync progress lines in existing transfer logs.

New transfers collapse progress lines as they are written, but rows created
before that still hold every tick rsync printed - typically 90% of their log.
This applies the same rule to what is already stored: consecutive progress
lines are reduced to the newest one, and every other line is left untouched.

Nothing else about a transfer is modified. Progress figures are already held in
their own columns, so no information is lost that the UI reads.

Usage:
    python scripts/compact_transfer_logs.py                 # report only
    python scripts/compact_transfer_logs.py --apply         # rewrite the rows
    python scripts/compact_transfer_logs.py --apply --db /path/to/dragoncp.db

Always taken against a backup:
    python scripts/compact_transfer_logs.py --apply --backup
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from services.transfer_service import parse_rsync_progress  # noqa: E402


def collapse(logs):
    """Reduce runs of progress lines to their newest line."""
    kept = []
    previous_was_progress = False
    for line in logs:
        is_progress = parse_rsync_progress(line) is not None
        if is_progress and previous_was_progress and kept:
            kept[-1] = line
        else:
            kept.append(line)
        previous_was_progress = is_progress
    return kept


def human(num_bytes):
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024 or unit == "GB":
            return f"{num_bytes:,.1f} {unit}"
        num_bytes /= 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=os.path.join(REPO_ROOT, "dragoncp.db"),
                        help="path to dragoncp.db (default: this checkout's)")
    parser.add_argument("--apply", action="store_true",
                        help="write the compacted logs back (default is a report only)")
    parser.add_argument("--backup", action="store_true",
                        help="copy the database aside before writing")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"Database not found: {args.db}")
        return 1

    if args.apply and args.backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = f"{args.db}.pre_log_compaction_{stamp}"
        shutil.copy2(args.db, destination)
        print(f"Backup written: {destination}")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("SELECT transfer_id, folder_name, logs FROM transfers").fetchall()

    lines_before = lines_after = bytes_before = bytes_after = 0
    changed = []

    for row in rows:
        raw = row["logs"] or "[]"
        try:
            logs = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not logs:
            continue

        kept = collapse(logs)
        new_raw = json.dumps(kept)

        lines_before += len(logs)
        lines_after += len(kept)
        bytes_before += len(raw)
        bytes_after += len(new_raw)

        if len(kept) != len(logs):
            changed.append((row["transfer_id"], row["folder_name"],
                            len(logs), len(kept), new_raw))

    print(f"transfers scanned : {len(rows):,}")
    print(f"rows to compact   : {len(changed):,}")
    print(f"log lines         : {lines_before:,} -> {lines_after:,}"
          f"   ({(1 - lines_after / max(lines_before, 1)) * 100:.1f}% less)")
    print(f"log column size   : {human(bytes_before)} -> {human(bytes_after)}"
          f"   ({(1 - bytes_after / max(bytes_before, 1)) * 100:.1f}% less)")

    if changed:
        worst = max(changed, key=lambda item: item[2] - item[3])
        print(f"biggest saving    : {worst[1]}  {worst[2]:,} -> {worst[3]:,} lines")

    if not args.apply:
        print("\nReport only. Re-run with --apply (and --backup) to rewrite the rows.")
        conn.close()
        return 0

    with conn:
        for transfer_id, _folder, _before, _after, new_raw in changed:
            conn.execute("UPDATE transfers SET logs = ? WHERE transfer_id = ?",
                         (new_raw, transfer_id))

    # Reclaim the freed pages, otherwise the file stays the same size
    print("\nRunning VACUUM to reclaim space...")
    size_before = os.path.getsize(args.db)
    conn.execute("VACUUM")
    conn.close()
    size_after = os.path.getsize(args.db)

    print(f"database file     : {human(size_before)} -> {human(size_after)}")
    print(f"compacted {len(changed):,} transfer log(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
