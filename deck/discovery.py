"""Bounded suggestions for one game's documented Proton save layout.

These are candidates, not a claim of verified real-Deck compatibility. Save
contents are never read here; selection and confirmation remain explicit.
"""
import os
from pathlib import Path
import re
import stat

from agent import watch
from .client import signature

MAX_VDF_BYTES = 64 * 1024
MAX_LIBRARIES = 32
SAVE_RELATIVE = Path('steamapps/compatdata/4231820/pfx/drive_c/users/steamuser/AppData/LocalLow') / 'KONAMI' / "Castlevania Belmont's Curse" / 'BuildSave_0.sav'
TOKEN = re.compile(r'\s+|//[^\r\n]*|[{}]|"((?:[^"\\\x00-\x1f]|\\["\\])*)"')


def library_paths(raw):
    """Parse a bounded VDF token stream; accept only modern quoted path entries."""
    if len(raw) > MAX_VDF_BYTES:
        return []
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        return []
    tokens = []
    position = 0
    while position < len(text):
        match = TOKEN.match(text, position)
        if match is None:
            return []
        position = match.end()
        if match.group(1) is not None:
            value = re.sub(r'\\(["\\])', r'\1', match.group(1))
            tokens.append(value)
        elif match.group() in ('{', '}'):
            tokens.append(None)
    paths = []
    for index, key in enumerate(tokens[:-1]):
        if key != 'path':
            continue
        value = tokens[index + 1]
        if not value or not os.path.isabs(value) or '..' in Path(value).parts or any(ord(c) < 32 for c in value):
            return []
        paths.append(Path(value))
        if len(paths) > MAX_LIBRARIES:
            return []
    return paths


def read_library_paths(path):
    try:
        fd, _ = watch._open_root(path)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_VDF_BYTES:
                return []
            raw = os.read(fd, MAX_VDF_BYTES + 1)
            if len(raw) != before.st_size or watch._signature(before) != watch._signature(os.fstat(fd)):
                return []
            return library_paths(raw)
        finally:
            os.close(fd)
    except (OSError, ValueError, watch.SnapshotError):
        return []


def discover(home=None):
    steam = (Path.home() if home is None else Path(home)) / '.local/share/Steam'
    libraries = [steam, *read_library_paths(steam / 'steamapps/libraryfolders.vdf')]
    candidates = []
    seen = set()
    for library in libraries[:MAX_LIBRARIES + 1]:
        path = library / SAVE_RELATIVE
        if str(path) in seen:
            continue
        seen.add(str(path))
        try:
            signature(path)  # Opens/fstats only; never hashes or decodes saves.
        except (OSError, ValueError, watch.SnapshotError):
            continue
        candidates.append(path)
    return candidates


def choose_path(*, home=None, ask=input):
    candidates = discover(home)
    if not candidates:
        print('No safe candidate found in the bounded known Proton locations. The real Deck path is not verified.')
        value = ask('Enter the actual absolute save-file path (blank cancels): ').strip()
        if not value or not os.path.isabs(value):
            raise ValueError('Explicit absolute save path required')
        path = Path(value)
    elif len(candidates) == 1:
        path = candidates[0]
    else:
        print('Candidate save files (contents not read):')
        for index, candidate in enumerate(candidates, 1):
            print(f'{index}: {candidate}')
        answer = ask('Choose a candidate number (blank cancels): ').strip()
        if not answer.isdecimal() or not 1 <= int(answer) <= len(candidates):
            raise ValueError('Explicit selection required')
        path = candidates[int(answer) - 1]
    signature(path)
    print('Selected save file: ' + str(path))
    if ask('Allow this specific file to be read after phone pairing approval? [y/N] ').strip().lower() not in ('y', 'yes'):
        raise ValueError('Save path not approved')
    return str(path)
