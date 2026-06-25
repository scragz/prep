#!/usr/bin/env python3
"""cmd_convert — Convert FLAC→MP3 320 CBR with parallel workers."""

import subprocess
from pathlib import Path
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing


def _log_line(root: Path, msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    line = '[%s] %s' % (ts, msg)
    print(line, flush=True)
    with open(root / 'operations.log', 'a') as f:
        f.write(line + '\n')


def convert_flac(args):
    """Worker — runs in subprocess pool, imports independently."""
    flac_path_str, dry_run = args
    flac_path = Path(flac_path_str)
    mp3_path  = flac_path.with_suffix('.mp3')

    if mp3_path.exists():
        return ('skip', flac_path_str)

    from prep.utils import get_flac_tags, flac_tags_to_id3_frames
    flac_tags = get_flac_tags(flac_path)

    if dry_run:
        return ('dry', flac_path_str)

    cmd = ['ffmpeg', '-i', str(flac_path),
           '-codec:a', 'libmp3lame', '-b:a', '320k', '-q:a', '0',
           '-map_metadata', '-1', '-y', str(mp3_path)]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        err = result.stderr.decode(errors='replace')[-300:]
        return ('error', flac_path_str, err)

    try:
        from mutagen.id3 import ID3, ID3NoHeaderError
        try:
            tags = ID3(str(mp3_path))
        except ID3NoHeaderError:
            tags = ID3()
        for name, frame in flac_tags_to_id3_frames(flac_tags).items():
            tags.add(frame)
        tags.save(str(mp3_path))
    except Exception:
        pass  # non-fatal, tags fixed by cmd_tags

    try:
        from mutagen.mp3 import MP3
        if MP3(str(mp3_path)).info.length < 1:
            raise ValueError('too short')
    except Exception as e:
        mp3_path.unlink(missing_ok=True)
        return ('error', flac_path_str, 'verify failed: %s' % e)

    flac_path.unlink()
    return ('ok', flac_path_str)


def run(root: Path, dry_run=False, workers=0, purge_ogg=False):
    root = Path(root)
    if not workers:
        workers = min(multiprocessing.cpu_count(), 16)

    _log_line(root, '=== convert START (dry_run=%s, workers=%d, purge_ogg=%s) ===' % (dry_run, workers, purge_ogg))

    # Optionally delete OGG files before scanning for FLACs
    if purge_ogg:
        ogg_files = sorted(list(root.rglob('*.ogg')) + list(root.rglob('*.OGG')))
        ogg_files = [f for f in ogg_files
                     if not any(p.startswith('_') for p in f.parts[len(root.parts):])]
        for ogg in ogg_files:
            _log_line(root, 'DELETE OGG: %s' % ogg.relative_to(root))
            if not dry_run:
                ogg.unlink()

    flac_files = []
    for f in sorted(list(root.rglob('*.flac')) + list(root.rglob('*.FLAC'))):
        parts = f.parts
        if any(p.startswith('_') for p in parts[len(root.parts):]):
            continue
        oggs = list(f.parent.glob('*.ogg')) + list(f.parent.glob('*.OGG'))
        if oggs:
            _log_line(root, 'SKIP (dir has OGG, quarantine first): %s' % f.parent.name)
            continue
        flac_files.append(f)

    total = len(flac_files)
    print('Found %d FLAC files — using %d workers' % (total, workers))

    converted = errors = skipped = 0
    args = [(str(f), dry_run) for f in flac_files]

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(convert_flac, a): a[0] for a in args}
        done = 0
        for fut in as_completed(futures):
            done += 1
            res = fut.result()
            status = res[0]
            name  = Path(res[1]).name
            if status == 'ok':
                converted += 1
                _log_line(root, '[%d/%d] CONVERTED: %s' % (done, total, name))
            elif status == 'skip':
                skipped += 1
            elif status == 'dry':
                converted += 1
                _log_line(root, '[%d/%d] DRY: %s' % (done, total, name))
            elif status == 'error':
                errors += 1
                _log_line(root, '[%d/%d] ERROR: %s — %s' % (
                    done, total, name, res[2] if len(res) > 2 else ''))

    _log_line(root, '=== convert DONE: converted=%d skipped=%d errors=%d ===' % (
        converted, skipped, errors))
