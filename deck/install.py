"""Inspectable user-scoped installer. Run explicitly; never needs sudo or pip."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import importlib.util
import stat
import uuid

from agent import watch

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
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)


def publish_unit(unit, content):
    """Publish a complete unit without overwriting a concurrent installation.

    Linux directory-relative link is the no-replace commit; the temporary file
    is private from creation. A failed directory fsync has an uncertain commit.
    """
    directory, _ = watch._open_root(unit.parent)
    temporary = '.companion-unit-' + uuid.uuid4().hex
    try:
        st = os.fstat(directory)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o022:
            raise ValueError('User unit directory must be owned and not writable by others')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, unit.name, src_dir_fd=directory, dst_dir_fd=directory,
                    follow_symlinks=False)
            os.fsync(directory)
        finally:
            os.unlink(temporary, dir_fd=directory)
    finally:
        os.close(directory)


def install(home, source):
    preflight()  # Check capabilities before creating installation files.
    import venv
    destination, unit, config = paths(home)
    for path in (destination, unit, config):
        require_safe(path)
    if destination.exists() or unit.exists():
        raise ValueError('Existing installation found; uninstall with --keep-config before replacing')
    destination.mkdir(parents=True, mode=0o700)
    identity = destination.stat()
    marker = destination / '.installing'
    try:
        # Remains after an abrupt kill or uncertain unit publication/reload.
        with marker.open('x') as stream:
            stream.write('installation incomplete\n')
            stream.flush()
            os.fsync(stream.fileno())
        target = destination / 'source'
        target.mkdir(mode=0o700)
        for package in ('deck', 'agent', 'decoders'):
            shutil.copytree(source / package, target / package,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'), symlinks=False)
        # Build at its final path: moving a venv would leave absolute paths stale.
        venv.EnvBuilder(with_pip=False).create(destination / 'venv')
        unit.parent.mkdir(parents=True, exist_ok=True)
        require_safe(unit.parent)
    except BaseException:
        # Only remove the directory created by this attempt, before publication.
        # If its identity/path changed, leave it for explicit local inspection.
        require_safe(destination)
        current = destination.stat()
        if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
            shutil.rmtree(destination)
        raise
    # Publication errors are uncertain: keep marker and files for explicit recovery.
    publish_unit(unit, unit_text(destination))
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True, timeout=15,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    marker.unlink()
    print('Installed for this user only. Pair explicitly, then enable/start the user service.')


def uninstall(home, remove_config):
    destination, unit, config = paths(home)
    for path in (destination, unit, config):
        require_safe(path)
    if unit.exists():
        # Failed/uncertain stop must not delete the running service or its state.
        subprocess.run(['systemctl', '--user', 'disable', '--now', NAME + '.service'], check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        # A removed unit file can still be loaded/running in the user manager.
        # Never infer that it stopped merely from filesystem absence.
        status = subprocess.run(['systemctl', '--user', 'is-active', NAME + '.service'],
                                check=False, timeout=5, capture_output=True, text=True)
        if status.returncode not in (3, 4) or status.stdout.strip() not in ('inactive', 'unknown'):
            raise ValueError('Service stop is unconfirmed; inspect user service before removal')
    unit.unlink(missing_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    if remove_config and config.exists():
        shutil.rmtree(config)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True, timeout=15,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    except KeyboardInterrupt:
        print('Installer interrupted. Installation or private pairing state may have changed. Run python3 -m deck doctor from extracted source before retrying.')
        return 1
    except (OSError, ValueError, watch.SnapshotError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print('Installer could not finish. Python venv and an active systemctl --user session are required. Use normal-user Desktop Mode; do not use sudo or change the SteamOS image. Inspect any partial user installation; no game saves were changed.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
