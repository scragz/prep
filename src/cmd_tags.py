#!/usr/bin/env python3
"""cmd_tags — Fix ID3 tags on all MP3 files."""

import re
from pathlib import Path
from datetime import datetime

from prep.utils import (
    MUSIC_EXTS, parse_dir_name, get_mp3_tags,
    genre_for_code, label_name_for_code, is_va,
    is_processed, mark_processed,
)

BOGUS_GENRES = {'unknown', 'other', '', 'none', 'soundtrack', 'misc'}


def _log(root: Path, msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    line = '[%s] %s' % (ts, msg)
    print(line)
    with open(root / 'operations.log', 'a') as f:
        f.write(line + '\n')


def fix_mp3_tags(mp3_path: Path, dir_parsed: dict, root: Path, dry_run: bool, force: bool = False):
    if not force and is_processed(mp3_path):
        return

    from mutagen.id3 import (ID3, ID3NoHeaderError, TPE1, TIT2, TALB,
                              TDRC, TYER, TCON, TPUB)
    try:
        try:
            tags = ID3(str(mp3_path))
        except ID3NoHeaderError:
            tags = ID3()
            tags.save(str(mp3_path))
            tags = ID3(str(mp3_path))
    except Exception as e:
        _log(root, 'ERROR opening %s: %s' % (mp3_path.name, e))
        return

    changed = False
    changes = []

    label_code = dir_parsed.get('label_code')
    dir_artist = dir_parsed.get('artist')
    dir_album  = dir_parsed.get('album')
    dir_year   = dir_parsed.get('year')
    va = is_va(dir_artist)

    # Remove COMM frames (torrent junk)
    comm_keys = [k for k in tags.keys() if k.startswith('COMM')]
    if comm_keys:
        for k in comm_keys:
            del tags[k]
        changed = True
        changes.append('removed COMM')

    # Year
    year_val = None
    if 'TDRC' in tags:
        year_val = str(tags['TDRC'])[:4]
    elif 'TYER' in tags:
        year_val = str(tags['TYER'])[:4]

    if (not year_val or not re.fullmatch(r'\d{4}', year_val)) and dir_year:
        tags.add(TDRC(encoding=3, text=dir_year))
        tags.add(TYER(encoding=3, text=dir_year))
        changed = True
        changes.append('year=%s' % dir_year)
    elif year_val and (not year_val.isdigit() or len(year_val) != 4):
        if dir_year:
            tags.add(TDRC(encoding=3, text=dir_year))
            tags.add(TYER(encoding=3, text=dir_year))
            changed = True
            changes.append('year fixed=%s' % dir_year)

    # Artist (skip VA)
    if not va and dir_artist:
        if 'TPE1' not in tags or not str(tags['TPE1']).strip():
            tags.add(TPE1(encoding=3, text=dir_artist))
            changed = True
            changes.append('artist=%s' % dir_artist)

    # Album
    if dir_album:
        if 'TALB' not in tags or not str(tags['TALB']).strip():
            tags.add(TALB(encoding=3, text=dir_album))
            changed = True
            changes.append('album=%s' % dir_album)

    # Label — label code lookup is authoritative; always overwrite if it differs
    label_name = label_name_for_code(label_code)
    if label_name:
        current_label = str(tags['TPUB']).strip() if 'TPUB' in tags else ''
        if current_label != label_name:
            tags.add(TPUB(encoding=3, text=[label_name]))
            changed = True
            changes.append('label=%s' % label_name)

    # Genre — label code lookup is authoritative; always overwrite if it differs
    genre_val = genre_for_code(label_code)
    if genre_val:
        current_genre = str(tags['TCON']).strip() if 'TCON' in tags else ''
        if current_genre != genre_val:
            tags.add(TCON(encoding=3, text=[genre_val]))
            changed = True
            changes.append('genre=%s' % genre_val)

    if changed:
        if not dry_run:
            tags.save(str(mp3_path))
        _log(root, '%s%s: %s' % ('DRY ' if dry_run else '', mp3_path.name, ', '.join(changes)))

    if not dry_run:
        mark_processed(mp3_path)


def run(root: Path, dry_run=False, force=False):
    root = Path(root)
    _log(root, '=== tags START (dry_run=%s, force=%s) ===' % (dry_run, force))

    for item in sorted(root.iterdir()):
        if not item.is_dir() or item.name.startswith('_') or item.name.startswith('.'):
            continue
        mp3s = list(item.glob('*.mp3')) + list(item.glob('*.MP3'))
        if mp3s:
            dir_parsed = parse_dir_name(item.name)
            for f in sorted(mp3s):
                fix_mp3_tags(f, dir_parsed, root, dry_run, force=force)
        else:
            for sub in sorted(item.iterdir()):
                if sub.is_dir():
                    sub_mp3s = list(sub.glob('*.mp3')) + list(sub.glob('*.MP3'))
                    if sub_mp3s:
                        dir_parsed = parse_dir_name(item.name)
                        for f in sorted(sub_mp3s):
                            fix_mp3_tags(f, dir_parsed, root, dry_run, force=force)

    _log(root, '=== tags DONE ===')
