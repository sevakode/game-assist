"""Deterministic public CODE-ONLY Deck archive; explicit files, never private data."""
import argparse
import hashlib
import os
from pathlib import Path
import tempfile
import zipfile

FILES = (
    'LICENSE', 'agent/watch.py', 'decoders/__init__.py', 'decoders/belmont.py',
    'deck/__init__.py', 'deck/__main__.py', 'deck/client.py', 'deck/discovery.py',
    'deck/install.py', 'deck/setup.py',
)
README = '''# Game Assist Deck companion (source only)

Python 3.10+ standard library, venv, and a working systemctl --user session are
required. No pip packages, binaries, Steam passwords, or API keys are included.

On your own Steam Deck, enter Desktop Mode as the normal user (never sudo).
Extract this archive, inspect the source, then run from the extracted directory:

    python3 -m deck setup --server https://YOUR-CONFIGURED-SERVICE

Use the exact HTTPS origin shown by the service's /setup page, not this placeholder.
Explicitly select your save path. On your phone open the displayed pairing URL,
sign in with Steam, compare the code shown on your own Deck, and select the game
and permitted access. New setup asks for the selected Steam AppID and defaults to
minimal metadata: only file size and modification time, not contents or progress.
An explicit Belmont 4231820 / 1.1.3 mode can send the four-field summary instead.
Unknown games need one explicit file path and registration on the service first.
Only one selected file/game is watched; re-pairing replaces it after confirmation.
The file-to-game association is user-declared, not automatically verified.
Approve only your own device. The setup asks
before enabling the user-only background service. No game saves are modified.

Do not disable SteamOS protections or install missing runtime components blindly.
If Python/venv/user-systemd are missing, stop and use a separately reviewed solution.
Gaming Mode persistence still needs real-Deck testing. Device pairing expires after
30 days. Summary fields are reported raw values, not max HP/mana or pickup proof.
This archive contains no account tokens, server state, saves or private fixtures.
Code license: MIT (see LICENSE). Third-party games are not included or licensed here.
'''


def build(source, destination):
    source, destination = Path(source).resolve(), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    contents = {'README.md': README.encode('utf-8')}
    for name in FILES:
        path = source / name
        if any(p.is_symlink() for p in (path, *path.parents) if p == source or source in p.parents):
            raise ValueError('Symlinked source is forbidden')
        # Resolve against source as well as checking each real parent.
        if path.resolve() != path or not path.is_file():
            raise ValueError('Source must be a regular in-tree file')
        data = path.read_bytes()
        if len(data) > 512 * 1024:
            raise ValueError('Unexpected source file size')
        contents[name] = data
    fd, temporary = tempfile.mkstemp(prefix='.deck-', suffix='.zip', dir=destination)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED) as archive:
            for name, data in sorted(contents.items()):
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_STORED
                archive.writestr(info, data)
        target = destination / 'deck-companion.zip'
        os.replace(temporary, target)
        checksum = hashlib.sha256(target.read_bytes()).hexdigest()
        (destination / 'deck-companion.zip.sha256').write_text(checksum+'  deck-companion.zip\n', encoding='ascii')
        return target, checksum
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    destination = args.output or args.source / 'remote_server/downloads'
    _, checksum = build(args.source, destination)
    print('Built code-only deck-companion.zip; SHA256 '+checksum)


if __name__ == '__main__':
    main()
