"""
utils.py — shared utilities for the prep pipeline.
"""

import re
from pathlib import Path

MUSIC_EXTS = {'.mp3', '.flac', '.ogg', '.m4a', '.MP3', '.Mp3', '.FLAC', '.M4A'}

JUNK_SUFFIXES = re.compile(
    r'\s*[\[\(]?\s*(?:WEB|DIGITAL|FLAC|CDQ|CBR|VBR|V0|V2|320|128|'
    r'VINYL|LP\b|EP\b|Single|Limited|Promo|Bootleg|Unofficial|Rip|'
    r'Remaster(?:ed)?|Reissue|Deluxe|Expanded|'
    r'Anniversary|Bonus|Hand.?stamped)\s*[\]\)]?\s*$',
    re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Dir name parsing
# ---------------------------------------------------------------------------

def parse_dir_name(dirname: str) -> dict:
    s = dirname.strip()
    result = dict(label_code=None, artist=None, album=None, year=None,
                  raw=dirname, pattern='unknown')

    # Pattern 2: [year] [CODE] Artist - Album
    m = re.match(r'^\[(\d{4})\]\s+\[([^\]]+)\]\s+(.+)$', s)
    if m:
        result['year'] = m.group(1)
        result['label_code'] = _clean_code(m.group(2))
        result['pattern'] = 'year_bracket_code'
        _parse_artist_album(m.group(3), result)
        return result

    # Pattern 1: [CODE_or_year] rest
    m = re.match(r'^\[([^\]]+)\]\s+(.+)$', s)
    if m:
        code_part = m.group(1).strip()
        rest = m.group(2).strip()
        if re.fullmatch(r'\d{4}', code_part):
            result['year'] = code_part
            result['pattern'] = 'bracket_year_no_code'
        else:
            result['label_code'] = _clean_code(code_part)
            result['pattern'] = 'bracket_code'
        # Handle "- YEAR - Artist - Album" format in rest (e.g. QUAY, ONR, FORMULA)
        my = re.match(r'^-\s*(\d{4})\s*-\s*(.+)$', rest)
        if my:
            if not result['year']:
                result['year'] = my.group(1)
            rest = my.group(2).strip()
        else:
            rest, year = _extract_trailing_year(rest)
            if year and not result['year']:
                result['year'] = year
        _parse_artist_album(rest, result)
        return result

    # Pattern 3: (year) LABEL... - Artist - Album
    m = re.match(r'^\((\d{4})\)\s+(.+)$', s)
    if m:
        result['year'] = m.group(1)
        result['pattern'] = 'paren_year_first'
        rest = m.group(2).strip()
        # Code patterns: SHADOW020, SHADOW 020, SHADOW 020 R, SHADOW 049 R 2, TOP 002
        mc = re.match(
            r'^([A-Z]+\s+\d+(?:\s+(?:CD|LP|R|H|P)\s*\d*)?)\s*(?:-\s*)?([A-Z].+)$',
            rest)
        if mc:
            code_norm = re.sub(r'\s+', '', mc.group(1)).upper()
            result['label_code'] = code_norm
            _parse_artist_album(mc.group(2).strip(), result)
        else:
            _parse_artist_album(rest, result)
        return result

    # Pattern 4: (CODE) Artist - Album [year]
    m = re.match(r'^\(([A-Z][A-Z0-9]*\d+[A-Z]?)\)\s+(.+)$', s, re.IGNORECASE)
    if m:
        result['label_code'] = _clean_code(m.group(1))
        result['pattern'] = 'paren_code'
        rest = m.group(2).strip()
        rest, year = _extract_trailing_year(rest)
        if year:
            result['year'] = year
        _parse_artist_album(rest, result)
        return result

    # Pattern 4b: CODE NNN [NNN] - Artist - Album (year)  (spaced catalog number, no brackets)
    # e.g. SHADOW 012 - Artist - Album (1997)
    # e.g. ASHADOW 012 001 - E-Z Rollers - Weekend World LP Sampler (1997)
    m = re.match(r'^([A-Z]{2,}(?:\s+\d+)+)\s*-\s*(.+)$', s)
    if m:
        result['label_code'] = _clean_code(m.group(1))
        result['pattern'] = 'spaced_code'
        rest = m.group(2).strip()
        rest, year = _extract_trailing_year(rest)
        if year:
            result['year'] = year
        _parse_artist_album(rest, result)
        return result

    # Pattern 5: CODE-YEAR-Artist-Album[-junk]  (torrent release format)
    # e.g. CONGONATTY01-2004-Congo_Natty-Walking_In_The_Air-Reissue
    # e.g. conscious001-congo_natty_conscious-lion_of_judah-vinyl-2007-xtc
    # Also handles all-uppercase alpha codes (Congo Natty style: BLADERUNNER-2002-...)
    m = re.match(r'^([A-Z]{4,}|[A-Za-z]{2,}\d+[A-Za-z0-9]*)-(\d{4})-(.+)$', s)
    if m:
        result['label_code'] = _clean_code(m.group(1))
        result['year'] = m.group(2)
        result['pattern'] = 'torrent_code_year'
        rest = m.group(3)
        parts = rest.split('-', 1)
        artist_raw = parts[0].replace('_', ' ').strip()
        album_raw  = parts[1].replace('_', ' ').strip() if len(parts) > 1 else ''
        album_raw  = _strip_torrent_suffix(album_raw, result['year'])
        result['artist'] = _clean_name(artist_raw) if artist_raw else None
        result['album']  = _clean_name(album_raw)  if album_raw  else None
        return result

    # Pattern 6: CODE-Artist-Album-YEAR[-junk]  (year at end, not right after code)
    # e.g. CONGOLP001-congo_natty-12_yrs_of_jungle-2002-sour
    # e.g. CONGONATTY016DG-Rebel_MC-Banana_Boat_Man-WEB-2008-DEF
    # Also handles all-uppercase alpha codes (BLADERUNNER, PEACE, etc.)
    m = re.match(r'^([A-Z]{4,}|[A-Za-z]{2,}\d+[A-Za-z0-9]*)-(.*?[^-])-(\d{4})(?:-.+)?$', s)
    if m:
        result['label_code'] = _clean_code(m.group(1))
        result['year'] = m.group(3)
        result['pattern'] = 'torrent_code_artist_year'
        rest = m.group(2)
        parts = rest.split('-', 1)
        artist_raw = parts[0].replace('_', ' ').strip()
        album_raw  = parts[1].replace('_', ' ').strip() if len(parts) > 1 else ''
        album_raw  = _strip_torrent_suffix(album_raw, result['year'])
        result['artist'] = _clean_name(artist_raw) if artist_raw else None
        result['album']  = _clean_name(album_raw)  if album_raw  else None
        return result

    # Fallback: no label code
    result['pattern'] = 'no_code'
    s2, year = _extract_trailing_year(s)
    if year:
        result['year'] = year
        s = s2
    _parse_artist_album(s, result)
    return result


def _clean_code(code):
    return re.sub(r'\s+', '', code).upper()


def _extract_trailing_year(s):
    m = re.search(r'[\[\(](\d{4})[\]\)]\s*$', s)
    if m:
        return s[:m.start()].strip(), m.group(1)
    m = re.search(r'\b((?:19|20)\d{2})\s*$', s)
    if m:
        return s[:m.start()].strip(), m.group(1)
    return s, None


def _parse_artist_album(s, result):
    s = _strip_junk(s)
    s = s.replace('–', '-').replace('—', '-').replace('−', '-')
    s = re.sub(r'(?<=[A-Za-z])_(?=[A-Za-z])', ' ', s)
    parts = re.split(r'\s+[-–—]\s+', s, maxsplit=1)
    if len(parts) == 2:
        result['artist'] = _clean_name(parts[0])
        result['album'] = _clean_name(parts[1])
    else:
        result['album'] = _clean_name(s)


def _strip_junk(s):
    # Remove trailing bracket annotations like [UK 12'' EP], [CD 1], etc.
    s = re.sub(r'\s*\[[^\]]{1,30}\]\s*$', '', s)
    s = JUNK_SUFFIXES.sub('', s)
    # Remove torrent scene tags: _Ripper-1993-GROUP or -Name-YYYY-GROUP at end
    s = re.sub(r'[-_][A-Za-z0-9.]+[-_]\d{4}[-_][A-Za-z0-9]+\s*$', '', s)
    s = re.sub(r'\s*-\s*$', '', s).strip()
    return s


def _strip_torrent_suffix(s, year=None):
    """Strip scene-group/format junk from the end of an album string extracted
    from a torrent-style filename (CODE-YEAR-Artist-Album-junk)."""
    # Strip -YEAR-GROUP if year already known (avoids eating single-char title components)
    if year:
        s = re.sub(r'-' + re.escape(year) + r'-[A-Za-z0-9]+\s*$', '', s)
    # Strip common format/group tokens: -WEB, -VINYL, -sour, -0db, -NRX etc.
    s = re.sub(r'-(?:WEB|VINYL|CDR?|FLAC|MP3|320|128|sour|NRX|SOUR|DDB|uC|xtc[_a-z]*|[0-9]db)\s*$',
               '', s, flags=re.IGNORECASE)
    # Strip remaining -GROUP at end (short alphanum token after final dash)
    s = re.sub(r'-[A-Za-z0-9]{2,8}\s*$', '', s)
    return s.strip(' -_')


def _clean_name(s):
    # Replace underscores used as spaces with actual spaces
    s = re.sub(r'(?<=[A-Za-z0-9])_(?=[A-Za-z0-9])', ' ', s)
    s = re.sub(r'\s{2,}', ' ', s)
    s = s.strip(' -_')
    # Title-case if entirely lowercase (torrent filenames)
    if s and s == s.lower():
        s = s.title()
    return s


def canonical_dir_name(parsed):
    code = parsed.get('label_code')
    artist = parsed.get('artist')
    album = parsed.get('album') or 'Unknown Album'
    year = parsed.get('year')
    # Normalize "Various Artists", "Various", etc. → "VA"
    if artist and artist.lower().strip('._') in ('va', 'various', 'various artists', 'v.a'):
        artist = 'VA'
    prefix = '[%s] ' % code if code else ''
    body = '%s - %s' % (artist, album) if artist else album
    suffix = ' (%s)' % year if year else ''
    return '%s%s%s' % (prefix, body, suffix)


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

VINYL_SIDE_RE = re.compile(r'^([A-Fa-f])(\d*)\.\s*(.+)$')
TRACK_NUM_RE = re.compile(r'^(\d{1,3})[\.\s\-]+(.+)$')


def parse_filename(stem):
    s = stem.strip()
    result = dict(track_num=None, artist=None, title=None, vinyl_side=None)
    m = VINYL_SIDE_RE.match(s)
    if m:
        side_letter = m.group(1).upper()
        side_num = m.group(2) or '1'
        result['vinyl_side'] = '%s%s' % (side_letter, side_num)
        _parse_artist_title(m.group(3).strip(), result)
        return result
    m = TRACK_NUM_RE.match(s)
    if m:
        result['track_num'] = int(m.group(1))
        _parse_artist_title(m.group(2).strip(), result)
        return result
    _parse_artist_title(s, result)
    return result


def _parse_artist_title(s, result):
    s = s.replace('–', '-').replace('—', '-')
    parts = re.split(r'\s+-\s+', s, maxsplit=1)
    if len(parts) == 2:
        result['artist'] = _clean_name(parts[0])
        result['title'] = _clean_name(parts[1])
    else:
        result['title'] = _clean_name(s)


def vinyl_sort_key(vinyl_side):
    if not vinyl_side:
        return 999
    side = vinyl_side[0].upper()
    num_s = vinyl_side[1:] or '1'
    try:
        num = int(num_s)
    except ValueError:
        num = 1
    return (ord(side) - ord('A')) * 10 + num


def canonical_filename(track_num, artist, title, is_va=False):
    num = '%02d' % track_num
    title = sanitize_path(title or 'Unknown')
    if artist and not is_va:
        return '%s %s - %s' % (num, sanitize_path(artist), title)
    return '%s %s' % (num, title)


def sanitize_path(s):
    s = s.replace('/', '-').replace('\\', '-')
    s = re.sub(r'[<>:"|?*\x00-\x1f]', '', s)
    s = re.sub(r'\s{2,}', ' ', s)
    return s.strip(' .')


# ---------------------------------------------------------------------------
# Tag helpers
# ---------------------------------------------------------------------------

def get_mp3_tags(path):
    from mutagen.id3 import ID3, ID3NoHeaderError
    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        return {}
    out = {}
    for fid, key in [('TPE1','artist'),('TIT2','title'),('TALB','album'),
                     ('TRCK','track'),('TDRC','year'),('TYER','year'),
                     ('TCON','genre'),('TPUB','label')]:
        if fid in tags:
            val = str(tags[fid]).strip()
            if val and key not in out:
                out[key] = val
    for key in tags.keys():
        if key.startswith('COMM'):
            out['has_comment'] = True
            break
    return out


def get_flac_tags(path):
    from mutagen.flac import FLAC
    try:
        f = FLAC(str(path))
    except Exception:
        return {}
    mapping = {
        'artist': ['artist', 'performer'],
        'title': ['title'],
        'album': ['album'],
        'year': ['date', 'year'],
        'genre': ['genre'],
        'label': ['organization', 'label', 'publisher'],
        'track': ['tracknumber', 'track'],
    }
    out = {}
    if f.tags:
        tag_dict = {}
        for k, v in dict(f.tags).items():
            if v:
                tag_dict[k.lower()] = v[0]
        for key, candidates in mapping.items():
            for c in candidates:
                if c in tag_dict:
                    out[key] = tag_dict[c].strip()
                    break
    return out


# ── Pipeline processed flag ─────────────────────────────────────────────────
PIPELINE_VERSION = '1'
_RB_DESC = 'RB_PROCESSED'

def is_processed(path) -> bool:
    """Return True if this MP3 has already been through the full pipeline."""
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError
        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            return False
        return bool(tags.get('TXXX:' + _RB_DESC))
    except Exception:
        return False

def mark_processed(path) -> bool:
    """Stamp TXXX:RB_PROCESSED onto the file. Call after 04_tags completes."""
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError, TXXX
        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            tags = ID3()
        tags.add(TXXX(encoding=3, desc=_RB_DESC, text=[PIPELINE_VERSION]))
        tags.save(str(path))
        return True
    except Exception:
        return False


_LQ_DESC = 'RB_QUALITY'

def mark_low_quality(path) -> bool:
    """Stamp TXXX:RB_QUALITY=LQ for files between 192-319 kbps."""
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError, TXXX
        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            tags = ID3()
        tags.add(TXXX(encoding=3, desc=_LQ_DESC, text=['LQ']))
        tags.save(str(path))
        return True
    except Exception:
        return False


def flac_tags_to_id3_frames(flac_tags):
    from mutagen.id3 import TPE1, TIT2, TALB, TDRC, TYER, TRCK, TCON, TPUB
    frames = {}
    simple = {'artist': TPE1, 'title': TIT2, 'album': TALB,
              'track': TRCK, 'genre': TCON, 'label': TPUB}
    for key, cls in simple.items():
        if key in flac_tags:
            frames[cls.__name__] = cls(encoding=3, text=flac_tags[key])
    if 'year' in flac_tags:
        yr = flac_tags['year'][:4]
        frames['TDRC'] = TDRC(encoding=3, text=yr)
        frames['TYER'] = TYER(encoding=3, text=yr)
    return frames


# ---------------------------------------------------------------------------
# Label / genre lookup
# ---------------------------------------------------------------------------

LABEL_GENRE = {
    'TRESOR': 'Techno', 'PLUS8': 'Techno', 'PLUS': 'Techno',
    'LINO': 'Techno', 'DO': 'Techno', 'DN': 'Techno', 'DWN': 'Techno',
    'SA': 'Techno', 'SAM': 'Techno', 'SASTE': 'Techno',
    'CRD': 'Dub Techno',
    'SHADOW': 'Drum & Bass', 'ASHADOW': 'Drum & Bass',
    'DS': 'Drum & Bass', 'DSCD': 'Drum & Bass', 'DSLP': 'Drum & Bass',
    # Respect Records (Russian DnB) — longer prefixes first
    'RFOPPLP': 'Drum & Bass', 'RFBF': 'Drum & Bass',
    'RFDD': 'Drum & Bass', 'RFCD': 'Drum & Bass', 'RSM': 'Drum & Bass',
    'RESPECT': 'Drum & Bass',
    # Good Looking Records (LTJ Bukem) — longer prefixes first
    'GLRBS': 'Drum & Bass', 'GLRCL': 'Drum & Bass', 'GLRAA': 'Drum & Bass',
    'GLRMA': 'Drum & Bass', 'GLRPS': 'Drum & Bass', 'GLRSX': 'Drum & Bass',
    'GLRM': 'Drum & Bass', 'GLRD': 'Drum & Bass', 'GLRV': 'Drum & Bass',
    'GLR': 'Drum & Bass',
    # Suburban Base Records (jungle/hardcore/DnB) — longer prefixes first
    'SUBBASELP': 'Jungle', 'SUBBASECD': 'Jungle', 'SUBBASE': 'Jungle',
    'SBBP': 'Jungle', 'BOOGIE': 'Jungle',
    'SUB': 'Techno', 'TOP': 'Rave', 'SC': 'Techno',
    # Jungle / Ragga Jungle labels
    # Congo Natty Records sublabels (longer prefixes first to avoid short-circuit)
    'CONGONATTYREMIX': 'Jungle', 'CONGONATTY': 'Jungle', 'CONGOLP': 'Jungle', 'CN': 'Jungle',
    'CONSCIOUS': 'Jungle',
    'LIONR': 'Jungle', 'LION': 'Jungle',
    'RAS': 'Jungle', 'ZION': 'Jungle', 'MOUNTZION': 'Jungle',
    # Looking Good Records
    'LGRB': 'Jungle', 'LGRF': 'Jungle', 'LGR': 'Jungle',
    # Deep Jungle Records
    'DATLP': 'Drum & Bass', 'DAT': 'Drum & Bass', 'LEEBOGUSMUSIC': 'Drum & Bass',
    # Quayside Records (catalog format: QUAY 04, QUAY 05...)
    'QUAY': 'Jungle',
    # Creative Wax / early jungle labels
    'CW': 'Jungle', 'CPW': 'Jungle', 'AW': 'Jungle', 'AWW': 'Jungle',
    'COO': 'Jungle', 'JW': 'Jungle', 'XCK': 'Jungle',
    # Telepathy / Valve / Onset / Infrared
    'TEL': 'Jungle', 'VALV': 'Jungle', 'ONR': 'Jungle', 'IR': 'Jungle',
    # Formula 7 artist-run label (catalog: FORMULA 7, FORMULA 09, FORMULA 7EP)
    'FORMULA': 'Jungle',
    # Labello Dance
    'LABELLO': 'Jungle',
}

LABEL_NAMES = {
    'TRESOR': 'Tresor', 'PLUS8': 'Plus 8 Records',
    'LINO': 'Lino Records', 'DO': 'Downwards', 'DN': 'Downwards', 'DWN': 'Downwards',
    'SA': 'Stroboscopic Artefacts', 'SAM': 'Stroboscopic Artefacts',
    'CRD': 'Chain Reaction',
    'SHADOW': 'Moving Shadow', 'ASHADOW': 'Moving Shadow',
    'DS': "Droppin' Science", 'DSCD': "Droppin' Science",
    'DSLP': "Droppin' Science",
    # Respect Records (longer prefixes first)
    'RFOPPLP': 'Respect Records', 'RFBF': 'Respect Records',
    'RFDD': 'Respect Records', 'RFCD': 'Respect Records', 'RSM': 'Respect Records',
    'RESPECT': 'Respect Records',
    # Good Looking Records — longer prefixes first
    'GLRBS': 'Good Looking Records', 'GLRCL': 'Good Looking Records',
    'GLRAA': 'Good Looking Records', 'GLRMA': 'Good Looking Records',
    'GLRPS': 'Good Looking Records', 'GLRSX': 'Good Looking Records',
    'GLRM': 'Good Looking Records', 'GLRD': 'Good Looking Records',
    'GLRV': 'Good Looking Records', 'GLR': 'Good Looking Records',
    # Suburban Base Records — longer prefixes first
    'SUBBASELP': 'Suburban Base Records', 'SUBBASECD': 'Suburban Base Records',
    'SUBBASE': 'Suburban Base Records', 'SBBP': 'Suburban Base Records',
    'BOOGIE': 'Suburban Base Records',
    'SUB': 'Sub Records', 'TOP': 'Top Banana', 'SC': 'Shitkatapult',
    # Congo Natty Records sublabels (longer prefixes first)
    'CONGONATTYREMIX': 'Congo Natty Records', 'CONGONATTY': 'Congo Natty Records',
    'CONGOLP': 'Congo Natty Records', 'CN': 'Congo Natty Records',
    'CONSCIOUS': 'Congo Natty Records',
    'LIONR': 'Congo Natty Records', 'LION': 'Congo Natty Records',
    'RAS': 'Congo Natty Records', 'ZION': 'Congo Natty Records',
    'MOUNTZION': 'Congo Natty Records',
    # Looking Good Records
    'LGRB': 'Looking Good Records', 'LGRF': 'Looking Good Records',
    'LGR': 'Looking Good Records',
    # Deep Jungle Records
    'DATLP': 'Deep Jungle Records', 'DAT': 'Deep Jungle Records',
    'LEEBOGUSMUSIC': 'Deep Jungle Records',
    # Quayside Records
    'QUAY': 'Quayside Records',
    # Creative Wax family
    'CW': 'Creative Wax', 'CPW': 'Creative Wax', 'AW': 'Awesome Wax',
    'AWW': 'Awesome Wax', 'COO': 'Cooler Records', 'JW': 'JW Records',
    'XCK': 'X Certificate Records',
    # Telepathy / Valve / Onset / Infrared
    'TEL': 'Telepathy Records', 'VALV': 'Valve Records',
    'ONR': 'Onset Records', 'IR': 'Infrared Records',
    # Formula 7 artist-run label
    'FORMULA': 'Formula 7',
    # Labello Dance
    'LABELLO': 'Labello Dance',
}


def genre_for_code(label_code):
    if not label_code:
        return None
    uc = label_code.upper()
    for prefix, genre in sorted(LABEL_GENRE.items(), key=lambda x: -len(x[0])):
        if uc.startswith(prefix):
            return genre
    return None


def label_name_for_code(label_code):
    if not label_code:
        return None
    uc = label_code.upper()
    for prefix, name in sorted(LABEL_NAMES.items(), key=lambda x: -len(x[0])):
        if uc.startswith(prefix):
            return name
    return None


def is_va(artist_str):
    if not artist_str:
        return False
    return artist_str.lower().strip('._') in ('va', 'various', 'various artists', 'v.a')
