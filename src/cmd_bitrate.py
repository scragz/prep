#!/usr/bin/env python3
"""cmd_bitrate — Quarantine <192 kbps, flag 192-319 kbps as LQ.

Policy:
  < 192 kbps  → move to ROOT/_quarantine/<rel_path>
  192-319 kbps → keep, add TXXX:RB_QUALITY=LQ tag
  320+ kbps   → keep, no action

VBR: V0 averages ~220-260 kbps; still flagged LQ since we can't confirm
quality without a full decode. Treat as acceptable, not ideal.
"""

import shutil
from pathlib import Path
from datetime import datetime

from prep.utils import mark_low_quality

QUARANTINE_BELOW = 192   # kbps
FLAG_BELOW = 320          # kbps


def _log(root: Path, msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    line = '[%s] %s' % (ts, msg)
    print(line)
    with open(root / 'operations.log', 'a') as f:
        f.write(line + '\n')


def _check(path: Path) -> dict:
    try:
        from mutagen.mp3 import MP3, BitrateMode
        info = MP3(str(path)).info
        br = int(info.bitrate / 1000)
        mode = info.bitrate_mode
        return {'br': br, 'cbr': mode == BitrateMode.CBR,
                'vbr': mode == BitrateMode.VBR, 'ok': True}
    except Exception as e:
        return {'br': 0, 'ok': False, 'err': str(e)}


def run(root: Path, dry_run=False):
    root = Path(root)
    quarantine_root = root / '_quarantine'
    _log(root, '=== bitrate START (dry_run=%s) ===' % dry_run)

    mp3_files = sorted(list(root.rglob('*.mp3')) + list(root.rglob('*.MP3')))
    # Skip _quarantine, _import, _prep, hidden dirs
    mp3_files = [f for f in mp3_files
                 if not any(p.startswith('_') or p.startswith('.')
                            for p in f.relative_to(root).parts[:-1])]

    print('Checking %d MP3 files...' % len(mp3_files))

    quarantined = flagged = kept = warn = 0
    report_lines = {'quarantine': [], 'flagged': [], 'warn': []}

    for i, f in enumerate(mp3_files):
        if i % 500 == 0 and i:
            print('  %d/%d' % (i, len(mp3_files)))
        info = _check(f)
        if not info['ok']:
            warn += 1
            report_lines['warn'].append('[ERR] %s — %s' % (f.relative_to(root), info.get('err','')))
            continue

        br = info['br']
        rel = f.relative_to(root)

        if br < QUARANTINE_BELOW:
            dest = quarantine_root / rel
            _log(root, 'QUARANTINE [%d kbps]: %s' % (br, rel))
            report_lines['quarantine'].append('[%d kbps] %s' % (br, rel))
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest))
            quarantined += 1

        elif br < FLAG_BELOW:
            _log(root, 'FLAG LQ [%d kbps]: %s' % (br, rel))
            report_lines['flagged'].append('[%d kbps] %s' % (br, rel))
            if not dry_run:
                mark_low_quality(f)
            flagged += 1

        else:
            kept += 1

    # Write report
    with open(root / 'bitrate_report.txt', 'w') as rep:
        rep.write('BITRATE REPORT\n' + '=' * 60 + '\n')
        rep.write('Kept: %d | LQ flagged: %d | Quarantined: %d | Warn: %d\n\n'
                  % (kept, flagged, quarantined, warn))
        rep.write('--- QUARANTINED (< %d kbps) ---\n' % QUARANTINE_BELOW)
        for l in report_lines['quarantine']:
            rep.write('  %s\n' % l)
        rep.write('\n--- FLAGGED LQ (%d–%d kbps) ---\n' % (QUARANTINE_BELOW, FLAG_BELOW - 1))
        for l in report_lines['flagged']:
            rep.write('  %s\n' % l)
        if report_lines['warn']:
            rep.write('\n--- WARN (unreadable) ---\n')
            for l in report_lines['warn']:
                rep.write('  %s\n' % l)

    _log(root, '=== bitrate DONE: kept=%d flagged=%d quarantined=%d warn=%d ===' % (
        kept, flagged, quarantined, warn))
    print('Report: bitrate_report.txt')
