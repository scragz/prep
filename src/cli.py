#!/usr/bin/env python3
"""prep — Rekordbox music library preparation pipeline.

Usage:
    prep [--root ROOT] [--dry-run] <command> [opts]

Commands:
    audit     Scan library and report formats/tags
    convert   FLAC→MP3 320 CBR (parallel)
    rename    Normalize dir and track filenames
    tags      Fix ID3 tags from dir name / label lookup
    bitrate   Quarantine <192 kbps, flag 192-319 kbps as LQ
    dedupe    Find duplicate tracks (report only)
    run       Full pipeline: convert → rename → tags → bitrate
    import    Process ROOT/_import/, promote to library

Default ROOT is the Rekordbox folder three levels above this file
(i.e. /…/Rekordbox/_prep/prep/cli.py → /…/Rekordbox/).
Override with --root or PREP_ROOT env variable.
"""

import argparse
import multiprocessing
import os
from pathlib import Path

# Default to current working directory so `prep` works from any music folder.
# Override with --root or PREP_ROOT env var.
_DEFAULT_ROOT = Path.cwd()


def _root_from(args) -> Path:
    env = os.environ.get("PREP_ROOT")
    if env:
        return Path(env)
    return Path(args.root)


def main():
    parser = argparse.ArgumentParser(
        prog="prep",
        description="Rekordbox library pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root", default=str(_DEFAULT_ROOT), help="Library root (default: %(default)s)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing"
    )

    sub = parser.add_subparsers(dest="cmd", metavar="command")
    sub.required = True

    def _add_dir(p):
        """Optional positional dir arg — overrides --root if given."""
        p.add_argument(
            "dir", nargs="?", default=None, help="Target directory (overrides --root)"
        )

    p_audit = sub.add_parser("audit", help="Scan library")
    _add_dir(p_audit)

    p_rename = sub.add_parser("rename", help="Normalize dir and filenames")
    _add_dir(p_rename)

    p_tags = sub.add_parser("tags", help="Fix ID3 tags")
    p_tags.add_argument(
        "--force", action="store_true", help="Re-process files already stamped as done"
    )
    _add_dir(p_tags)

    p_dedupe = sub.add_parser("dedupe", help="Find duplicate tracks")
    _add_dir(p_dedupe)

    p_convert = sub.add_parser("convert", help="FLAC→MP3 (parallel)")
    p_convert.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Parallel workers (default: cpu_count, max 16)",
    )
    p_convert.add_argument(
        "--purge-ogg",
        action="store_true",
        help="Delete OGG files before converting FLACs",
    )
    _add_dir(p_convert)

    p_bitrate = sub.add_parser("bitrate", help="Quarantine/flag low-quality files")
    _add_dir(p_bitrate)

    p_run = sub.add_parser("run", help="Full pipeline: convert→rename→tags→bitrate")
    p_run.add_argument("--workers", type=int, default=0)
    p_run.add_argument(
        "--force",
        action="store_true",
        help="Re-process already-stamped files in tags step",
    )
    _add_dir(p_run)

    args = parser.parse_args()
    # positional dir overrides --root
    root = Path(args.dir) if getattr(args, "dir", None) else _root_from(args)
    dry = args.dry_run

    if args.cmd == "audit":
        from cmd_audit import run

        run(root)

    elif args.cmd == "convert":
        from cmd_convert import run

        workers = args.workers or min(multiprocessing.cpu_count(), 16)
        run(root, dry_run=dry, workers=workers, purge_ogg=args.purge_ogg)

    elif args.cmd == "rename":
        from cmd_rename import run

        run(root, dry_run=dry)

    elif args.cmd == "tags":
        from cmd_tags import run

        run(root, dry_run=dry, force=getattr(args, "force", False))

    elif args.cmd == "bitrate":
        from cmd_bitrate import run

        run(root, dry_run=dry)

    elif args.cmd == "dedupe":
        from cmd_dedupe import run

        run(root)

    elif args.cmd == "run":
        workers = args.workers or min(multiprocessing.cpu_count(), 16)
        from cmd_bitrate import run as do_bitrate
        from cmd_convert import run as do_convert
        from cmd_rename import run as do_rename
        from cmd_tags import run as do_tags

        print("=== STEP 1/4: convert ===")
        do_convert(root, dry_run=dry, workers=workers)
        print("=== STEP 2/4: rename ===")
        do_rename(root, dry_run=dry)
        print("=== STEP 3/4: tags ===")
        do_tags(root, dry_run=dry, force=getattr(args, "force", False))
        print("=== STEP 4/4: bitrate ===")
        do_bitrate(root, dry_run=dry)


if __name__ == "__main__":
    main()
