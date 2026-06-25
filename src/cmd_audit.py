#!/usr/bin/env python3
"""cmd_audit — Scan the Rekordbox library and produce a manifest."""

import json
import re
from pathlib import Path

from prep.utils import (
    MUSIC_EXTS, parse_dir_name, canonical_dir_name,
    parse_filename, get_mp3_tags, get_flac_tags,
    genre_for_code, label_name_for_code, is_va, vinyl_sort_key,
)


def has_ogg(d: Path) -> bool:
    return any(d.rglob('*.ogg')) or any(d.rglob('*.OGG'))


def has_m4a(d: Path) -> bool:
    return any(d.rglob('*.m4a')) or any(d.rglob('*.M4A'))


def _is_vinyl(stem):
    return bool(re.match(r'^[A-Fa-f]\d*\.', stem.strip()))


def _scan_track(path: Path, num: int, dir_parsed: dict) -> dict:
    fmt = path.suffix.lstrip('.').lower()
    tags = get_mp3_tags(path) if fmt == 'mp3' else \
           get_flac_tags(path) if fmt == 'flac' else {}
    file_parsed = parse_filename(path.stem)
    eff_artist = tags.get('artist') or file_parsed.get('artist') or dir_parsed.get('artist')
    eff_title  = tags.get('title')  or file_parsed.get('title')  or path.stem
    eff_year   = (tags.get('year')  or dir_parsed.get('year') or '')[:4]
    eff_label  = tags.get('label')  or label_name_for_code(dir_parsed.get('label_code'))
    eff_genre  = tags.get('genre')  or genre_for_code(dir_parsed.get('label_code'))
    return {
        'file': path.name, 'track_num': num, 'fmt': fmt, 'tags': tags,
        'eff_artist': eff_artist, 'eff_title': eff_title,
        'eff_year': eff_year, 'eff_label': eff_label, 'eff_genre': eff_genre,
        'missing_tags': [k for k in ('artist','title','album','year','label','genre')
                         if not tags.get(k)],
        'has_comment': tags.get('has_comment', False),
    }


def scan_album_dir(album_dir: Path) -> dict:
    dir_parsed = parse_dir_name(album_dir.name)
    canonical  = canonical_dir_name(dir_parsed)
    ogg = has_ogg(album_dir)
    m4a = has_m4a(album_dir)
    if ogg or m4a:
        return {
            'dir': album_dir.name, 'canonical_dir': canonical,
            'dir_changed': album_dir.name != canonical, 'dir_parsed': dir_parsed,
            'tracks': [], 'formats': (['ogg'] if ogg else []) + (['m4a'] if m4a else []),
            'rejected': True,
            'reject_reason': ', '.join((['ogg'] if ogg else []) + (['m4a'] if m4a else [])),
            'needs_conversion': False, 'has_ogg': ogg,
        }

    audio_files = sorted([f for f in album_dir.iterdir()
                          if f.is_file() and f.suffix.lower() in
                          {e.lower() for e in MUSIC_EXTS}])
    vinyl_files   = [f for f in audio_files if _is_vinyl(f.stem)]
    numbered_files = [f for f in audio_files if not _is_vinyl(f.stem)]
    tracks = []
    if vinyl_files:
        vinyl_files.sort(key=lambda f: vinyl_sort_key(
            parse_filename(f.stem).get('vinyl_side') or ''))
        for i, f in enumerate(vinyl_files, 1):
            tracks.append(_scan_track(f, i, dir_parsed))
    for f in numbered_files:
        p = parse_filename(f.stem)
        tracks.append(_scan_track(f, p.get('track_num') or 0, dir_parsed))
    tracks.sort(key=lambda t: t['track_num'] or 0)

    return {
        'dir': album_dir.name, 'canonical_dir': canonical,
        'dir_changed': album_dir.name != canonical, 'dir_parsed': dir_parsed,
        'sub_dirs': [x.name for x in album_dir.iterdir() if x.is_dir()],
        'tracks': tracks, 'formats': list({t['fmt'] for t in tracks}),
        'rejected': False, 'reject_reason': None,
        'needs_conversion': any(t['fmt'] == 'flac' for t in tracks),
        'has_ogg': False,
    }


def run(root: Path):
    root = Path(root)
    out_json   = root / 'audit.json'
    out_report = root / 'audit_report.txt'
    out_reject = root / 'reject_ogg.txt'

    print('Scanning %s ...' % root)
    if not root.exists():
        print('ERROR: path not found:', root)
        return

    albums = []
    skipped = []

    for item in sorted(root.iterdir()):
        if not item.is_dir() or item.name.startswith('_') or item.name.startswith('.'):
            continue
        try:
            album = scan_album_dir(item)
            if album['tracks'] or album['rejected']:
                albums.append(album)
            else:
                for sub in sorted(item.iterdir()):
                    if sub.is_dir():
                        try:
                            sub_album = scan_album_dir(sub)
                            if sub_album['tracks'] or sub_album['rejected']:
                                sub_album['parent_dir'] = item.name
                                albums.append(sub_album)
                        except Exception as e:
                            skipped.append('%s/%s: %s' % (item.name, sub.name, e))
        except Exception as e:
            skipped.append('%s: %s' % (item.name, e))

    good     = [a for a in albums if not a['rejected']]
    rejected = [a for a in albums if a['rejected']]
    total_tracks = sum(len(a['tracks']) for a in good)
    formats = {}
    for a in good:
        for t in a['tracks']:
            formats[t['fmt']] = formats.get(t['fmt'], 0) + 1

    manifest = {
        'root': str(root), 'total_albums': len(good),
        'total_rejected': len(rejected), 'total_tracks': total_tracks,
        'formats': formats, 'albums': good, 'rejected': rejected, 'skipped': skipped,
    }
    with open(out_json, 'w') as f:
        json.dump(manifest, f, indent=2)

    dirs_changed     = [a for a in good if a.get('dir_changed')]
    needs_conversion = [a for a in good if a.get('needs_conversion')]

    with open(out_report, 'w') as f:
        f.write('REKORDBOX LIBRARY AUDIT\n' + '=' * 60 + '\n\n')
        f.write('Root: %s\n' % root)
        f.write('Good albums: %d | Tracks: %d\n' % (len(good), total_tracks))
        f.write('Formats: %s\n' % ', '.join('%s=%d' % kv for kv in sorted(formats.items())))
        f.write('REJECTED (ogg/m4a): %d\n\n' % len(rejected))
        f.write('--- REJECTED DIRS (%d) ---\n' % len(rejected))
        for a in rejected:
            f.write('  [%s] %s\n' % (a['reject_reason'], a['dir']))
        f.write('\n--- DIRS TO RENAME (%d) ---\n' % len(dirs_changed))
        for a in dirs_changed:
            f.write('  OLD: %s\n  NEW: %s\n\n' % (a['dir'], a['canonical_dir']))
        f.write('\n--- NEEDS FLAC CONVERSION (%d) ---\n' % len(needs_conversion))
        for a in needs_conversion:
            counts = {}
            for t in a['tracks']:
                counts[t['fmt']] = counts.get(t['fmt'], 0) + 1
            f.write('  %s  %s\n' % (a['dir'], counts))
        f.write('\n--- SKIPPED ---\n')
        for s in skipped:
            f.write('  %s\n' % s)

    with open(out_reject, 'w') as f:
        for a in rejected:
            f.write('%s\n' % a['dir'])

    print('Good: %d albums, %d tracks' % (len(good), total_tracks))
    print('Rejected (ogg/m4a): %d' % len(rejected))
    print('Formats: %s' % formats)
    print('Written: audit.json, audit_report.txt, reject_ogg.txt')
