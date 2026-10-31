"""Inspectable user-scoped installer. Run explicitly; never needs sudo or pip."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import importlib.util

NAME = 'steam-game-companion'


def unit_text(install):
    # systemd specifiers must not interpret '%' in user paths; double quotes need escaping.
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
    return '''[Unit]
Description=Opt-in Steam Deck save-summary companion
After=network-online.target

[Service]
Type=simple
WorkingDirectory=''' + quote(install / 'source') + '''
ExecStart=''' + quote(install / 'venv/bin/python') + ''' -m deck run
Restart=on-failure
RestartSec=60
RestartPreventExitStatus=3
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=default.target
'''


def paths(home):
    return (home / '.local/share' / NAME,
            home / '.config/systemd/user' / (NAME + '.service'),
            home / '.config' / NAME)


def require_safe(path):
    for p in (path, *path.parents):
        if p.is_symlink():
            raise ValueError('Installer destinations must not contain symlinks')


def preflight():
    if importlib.util.find_spec('venv') is None or shutil.which('systemctl') is None:
        raise ValueError('Python venv and systemctl are required; do not modify the SteamOS system image')
    subprocess.run(['systemctl', '--user', 'show-environment'], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def install(home, source):
    preflight()  # Check capabilities before creating installation files.
    import venv
    destination, unit, config = paths(home)
    for path in (destination, unit, config):
        require_safe(path)
    if destination.exists() or unit.exists():
        raise ValueError('Existing installation found; uninstall with --keep-config before replacing')
    destination.mkdir(parents=True, mode=0o700)
    target = destination / 'source'
    target.mkdir(mode=0o700)
    for package in ('deck', 'agent', 'decoders'):
        shutil.copytree(source / package, target / package,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'), symlinks=False)
    # This client is stdlib-only. No network download or third-party executables.
    venv.EnvBuilder(with_pip=False).create(destination / 'venv')
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(unit_text(destination))
    unit.chmod(0o600)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    print('Installed for this user only. Pair explicitly, then enable/start the user service.')


def uninstall(home, remove_config):
    destination, unit, config = paths(home)
    for path in (destination, unit, config):
        require_safe(path)
    subprocess.run(['systemctl', '--user', 'disable', '--now', NAME + '.service'], check=False)
    unit.unlink(missing_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    if remove_config and config.exists():
        shutil.rmtree(config)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    print('Companion removed. Original game saves were not touched.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('install', 'uninstall'))
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument('--keep-config', action='store_true')
    choice.add_argument('--remove-config', action='store_true')
    args = parser.parse_args(argv)
    if sys.platform != 'linux' or os.geteuid() == 0:
        parser.error('Run as your normal Linux/Steam Deck user, never with sudo')
    if args.command == 'uninstall' and not (args.keep_config or args.remove_config):
        parser.error('Uninstall requires explicit --keep-config or --remove-config')
    if args.command == 'install' and (args.keep_config or args.remove_config):
        parser.error('Config flags apply only to uninstall')
    try:
        if args.command == 'install':
            install(Path.home(), Path(__file__).resolve().parents[1])
        else:
            uninstall(Path.home(), args.remove_config)
    except (OSError, ValueError, subprocess.CalledProcessError):
        print('Installer could not finish. Python venv and an active systemctl --user session are required. Use normal-user Desktop Mode; do not use sudo or change the SteamOS image. Inspect any partial user installation; no game saves were changed.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
