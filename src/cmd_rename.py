#!/usr/bin/env python3
"""cmd_rename — Normalize dir names and track filenames."""

import json
import re
from pathlib import Path
from datetime import datetime

from prep.utils import (
    MUSIC_EXTS, parse_dir_name, canonical_dir_name,
    parse_filename, canonical_filename, vinyl_sort_key, sanitize_path, is_va,
)

_path_map = []


def _log(root: Path, msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    line = '[%s] %s' % (ts, msg)
    print(line)
    with open(root / 'operations.log', 'a') as f:
        f.write(line + '\n')


def _audio_files_in(d: Path):
    exts = {e.lower() for e in MUSIC_EXTS}
    return sorted([f for f in d.iterdir() if f.is_file() and f.suffix.lower() in exts])


def _is_vinyl(stem):
    return bool(re.match(r'^[A-Fa-f]\d*\.', stem.strip()))


def _normalize_dir(album_dir: Path, root: Path, dry_run: bool) -> Path:
    parsed = parse_dir_name(album_dir.name)
    canonical = sanitize_path(canonical_dir_name(parsed))
    if canonical == album_dir.name:
        return album_dir
    new_path = album_dir.parent / canonical
    if new_path.exists():
        _log(root, 'COLLISION skipping: %s -> %s' % (album_dir.name, canonical))
        return album_dir
    _log(root, 'RENAME DIR: %s\n           -> %s' % (album_dir.name, canonical))
    if not dry_run:
        album_dir.rename(new_path)
        return new_path
    return album_dir


def _normalize_tracks(album_dir: Path, dir_parsed: dict, root: Path, dry_run: bool):
    files = _audio_files_in(album_dir)
    if not files:
        return
    va = is_va(dir_parsed.get('artist'))
    vinyl_files   = [f for f in files if _is_vinyl(f.stem)]
    numbered_files = [f for f in files if not _is_vinyl(f.stem)]
    vinyl_files.sort(key=lambda f: vinyl_sort_key(parse_filename(f.stem).get('vinyl_side') or ''))

    to_rename = [(f, i) for i, f in enumerate(vinyl_files, 1)]
    for f in numbered_files:
        p = parse_filename(f.stem)
        to_rename.append((f, p.get('track_num') or 0))
    to_rename.sort(key=lambda x: x[1])

    nums = [n for _, n in to_rename]
    if len(nums) > 1 and (min(nums) == 0 or len(set(nums)) != len(nums)):
        to_rename = [(f, i) for i, (f, _) in enumerate(to_rename, 1)]

    for f, num in to_rename:
        p = parse_filename(f.stem)
        artist = p.get('artist') or (None if va else dir_parsed.get('artist'))
        title  = p.get('title') or f.stem
        new_name = sanitize_path(canonical_filename(num, artist, title, is_va=va) + '.mp3')
        if new_name == f.name:
            continue
        new_path = f.parent / new_name
        if new_path.exists() and new_path != f:
            _log(root, 'COLLISION track: %s -> %s' % (f.name, new_name))
            continue
        _path_map.append({'old': str(f), 'new': str(new_path)})
        _log(root, 'RENAME TRACK: %s -> %s' % (f.name, new_name))
        if not dry_run:
            f.rename(new_path)


def _process_dir(album_dir: Path, root: Path, dry_run: bool):
    new_dir = _normalize_dir(album_dir, root, dry_run)
    dir_parsed = parse_dir_name(new_dir.name)
    _normalize_tracks(new_dir, dir_parsed, root, dry_run)


def run(root: Path, dry_run=False):
    root = Path(root)
    global _path_map
    _path_map = []
    _log(root, '=== rename START (dry_run=%s) ===' % dry_run)

    for item in sorted(root.iterdir()):
        if not item.is_dir() or item.name.startswith('_') or item.name.startswith('.'):
            continue
        audio = _audio_files_in(item)
        sub_audio = []
        for sub in sorted(item.iterdir()):
            if sub.is_dir():
                sub_audio += _audio_files_in(sub)

        # Skip placeholder/stub dirs with no audio files anywhere inside
        if not audio and not sub_audio:
            continue

        if not audio and sub_audio:
            new_item = _normalize_dir(item, root, dry_run)
            for sub in sorted(new_item.iterdir()):
                if sub.is_dir() and _audio_files_in(sub):
                    dir_parsed = parse_dir_name(new_item.name)
                    _normalize_tracks(sub, dir_parsed, root, dry_run)
        else:
            _process_dir(item, root, dry_run)

    pathmap = root / 'path_map.json'
    existing = []
    if pathmap.exists():
        with open(pathmap) as f:
            existing = json.load(f)
    combined = existing + _path_map
    with open(pathmap, 'w') as f:
        json.dump(combined, f, indent=2)

    _log(root, '=== rename DONE: %d path mappings ===' % len(combined))
