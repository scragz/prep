#!/usr/bin/env python3
"""cmd_import — Process ROOT/_import/ staging dir and promote to library.

Drop new/replacement album dirs into ROOT/_import/, then run:
    prep import

For each dir in _import/:
  1. Convert any FLACs to MP3 320 CBR
  2. Rename dir and files to canonical form
  3. Fix ID3 tags
  4. Bitrate check: quarantine <192 kbps files, flag 192-319 as LQ
  5. Move dir to ROOT/ (merge if dir name already exists)

Already-processed files (TXXX:RB_PROCESSED) are skipped in steps 3+.
"""

import shutil
import multiprocessing
from pathlib import Path
from datetime import datetime


def _log(root: Path, msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    line = '[%s] %s' % (ts, msg)
    print(line)
    with open(root / 'operations.log', 'a') as f:
        f.write(line + '\n')


def _process_import_dir(album_dir: Path, root: Path, dry_run: bool, workers: int):
    """Run full pipeline on a single dir, then promote to root."""
    from prep.cmd_convert import convert_flac
    from prep.cmd_rename  import _normalize_dir, _normalize_tracks, _audio_files_in
    from prep.cmd_tags    import fix_mp3_tags
    from prep.cmd_bitrate import _check, QUARANTINE_BELOW, FLAG_BELOW
    from prep.utils       import parse_dir_name, mark_low_quality

    _log(root, '--- IMPORT: %s ---' % album_dir.name)

    # 1. Convert FLACs
    flac_files = list(album_dir.rglob('*.flac')) + list(album_dir.rglob('*.FLAC'))
    if flac_files:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        args = [(str(f), dry_run) for f in flac_files]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for fut in as_completed([pool.submit(convert_flac, a) for a in args]):
                res = fut.result()
                if res[0] == 'error':
                    _log(root, 'CONVERT ERROR: %s' % (res[2] if len(res) > 2 else ''))

    # 2. Rename dir + files
    new_dir = _normalize_dir(album_dir, root, dry_run)
    dir_parsed = parse_dir_name(new_dir.name)
    _normalize_tracks(new_dir, dir_parsed, root, dry_run)

    # 3. Fix tags
    for mp3 in sorted(list(new_dir.glob('*.mp3')) + list(new_dir.glob('*.MP3'))):
        fix_mp3_tags(mp3, dir_parsed, root, dry_run)

    # 4. Bitrate check
    quarantine_root = root / '_quarantine'
    for mp3 in sorted(list(new_dir.glob('*.mp3')) + list(new_dir.glob('*.MP3'))):
        info = _check(mp3)
        if not info['ok']:
            continue
        br = info['br']
        if br < QUARANTINE_BELOW:
            dest = quarantine_root / new_dir.name / mp3.name
            _log(root, 'QUARANTINE [%d kbps]: %s/%s' % (br, new_dir.name, mp3.name))
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(mp3), str(dest))
        elif br < FLAG_BELOW:
            _log(root, 'FLAG LQ [%d kbps]: %s/%s' % (br, new_dir.name, mp3.name))
            if not dry_run:
                mark_low_quality(mp3)

    # 5. Promote to root
    dest_dir = root / new_dir.name
    if dest_dir.exists():
        # Merge: move individual files
        _log(root, 'MERGE into existing: %s' % new_dir.name)
        if not dry_run:
            for f in new_dir.iterdir():
                if f.is_file():
                    target = dest_dir / f.name
                    if not target.exists():
                        shutil.move(str(f), str(target))
                    else:
                        _log(root, 'SKIP (exists in dest): %s' % f.name)
            # Remove if now empty
            if not any(new_dir.iterdir()):
                new_dir.rmdir()
    else:
        _log(root, 'PROMOTE: %s -> root' % new_dir.name)
        if not dry_run:
            shutil.move(str(new_dir), str(dest_dir))


def run(root: Path, dry_run=False):
    root = Path(root)
    import_root = root / '_import'
    workers = min(multiprocessing.cpu_count(), 16)

    if not import_root.exists():
        print('No _import/ dir found at %s' % import_root)
        print('Create it and drop album folders inside, then re-run.')
        return

    dirs = sorted([d for d in import_root.iterdir()
                   if d.is_dir() and not d.name.startswith('.')])

    if not dirs:
        print('_import/ is empty — nothing to process.')
        return

    print('Found %d dirs in _import/' % len(dirs))
    _log(root, '=== import START (dry_run=%s) ===' % dry_run)

    for d in dirs:
        try:
            _process_import_dir(d, root, dry_run, workers)
        except Exception as e:
            _log(root, 'ERROR processing %s: %s' % (d.name, e))

    _log(root, '=== import DONE ===')
