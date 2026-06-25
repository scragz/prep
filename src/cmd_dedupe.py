#!/usr/bin/env python3
"""cmd_dedupe — Find duplicate tracks (report only, no deletions)."""

import re
import unicodedata
from pathlib import Path
from collections import defaultdict

from prep.utils import get_mp3_tags, parse_filename


def _normalize_key(s: str) -> str:
    s = s.lower()
    s = re.sub(r'\b(feat\.?|ft\.?|vs\.?|featuring)\b.*', '', s)
    s = ''.join(c for c in unicodedata.normalize('NFD', s)
                if unicodedata.category(c) != 'Mn')
    s = re.sub(r"[^\w\s]", ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _track_key(path: Path) -> str | None:
    tags = get_mp3_tags(path) if path.suffix.lower() == '.mp3' else {}
    artist = tags.get('artist', '')
    title  = tags.get('title', '')
    if not title:
        p = parse_filename(path.stem)
        artist = artist or p.get('artist', '')
        title  = p.get('title', '') or path.stem
    if not artist or not title:
        return None
    return '%s|%s' % (_normalize_key(artist), _normalize_key(title))


def _bitrate(path: Path) -> int:
    try:
        from mutagen.mp3 import MP3
        return int(MP3(str(path)).info.bitrate / 1000)
    except Exception:
        return 0


def run(root: Path):
    root = Path(root)
    out = root / 'dedupe_report.txt'
    print('Scanning for duplicates in %s ...' % root)

    track_index = defaultdict(list)
    mp3_files = sorted(list(root.rglob('*.mp3')) + list(root.rglob('*.MP3')))
    # Skip _quarantine, _import
    mp3_files = [f for f in mp3_files
                 if not any(p.startswith('_') for p in f.relative_to(root).parts[:-1])]
    print('Scanning %d MP3 files...' % len(mp3_files))

    for i, f in enumerate(mp3_files):
        if i % 200 == 0:
            print('  %d/%d' % (i, len(mp3_files)))
        key = _track_key(f)
        if key:
            track_index[key].append(f)

    dupes = {k: v for k, v in track_index.items() if len(v) > 1}
    print('Found %d duplicate groups' % len(dupes))

    with open(out, 'w') as f:
        f.write('DUPLICATE TRACK REPORT\n' + '=' * 60 + '\n\n')
        f.write('Groups: %d\n\n' % len(dupes))
        for key, paths in sorted(dupes.items()):
            artist_part, title_part = key.split('|', 1)
            f.write('--- %s / %s ---\n' % (artist_part, title_part))
            for p in paths:
                br = _bitrate(p)
                f.write('  [%d kbps] %s\n' % (br, p.relative_to(root)))
            f.write('\n')

    print('Report: %s' % out)
