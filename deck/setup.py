"""Explicitly invoked guided CLI setup; no privileged operations."""
import os
from pathlib import Path
import subprocess
import sys

from .client import Store, Transport, pair, server_origin, signature, selection, MAX_METADATA_BYTES, watch, belmont
from .install import install, paths, NAME
from .doctor import installation_state


def setup(server, path=None, *, enable=False, ask=input, appid=None, mode=None):
    """Install -> phone pairing -> opt-in user service. Never called implicitly."""
    if sys.platform != 'linux' or os.geteuid() == 0:
        print('Use your normal Linux/Steam Deck user in Desktop Mode, never sudo.')
        return 1
    try:
        server_origin(server)  # Reject insecure origins before installation.
        if appid is None:
            appid = int(ask('Steam AppID выбранной игры (например, 4231820): ').strip())
        if mode is None:
            print('1: Только размер/время изменения файла; содержимое и прогресс неизвестны, декодер не нужен.')
            if appid == 4231820:
                print('2: Четыре поля Belmont 1.1.3; полный сейв не передаётся.')
                choice = ask('Режим [1]: ').strip()
                if choice not in ('', '1', '2'):
                    raise ValueError('Choose metadata or the supported summary mode')
                mode = 'belmont-summary' if choice == '2' else 'metadata'
            else:
                mode = 'metadata'
        selection(appid, mode)
        if path is None:
            if appid == 4231820:
                from .discovery import choose_path
                path = choose_path(ask=ask)
            else:
                path = ask('Полный путь к одному файлу сейва (пусто — отмена; папки не сканируются): ').strip()
                if not path or not os.path.isabs(path):
                    raise ValueError('Explicit absolute file path required')
                if ask('Разрешить локальный доступ только для чтения и передачу лишь размера/времени? [y/N] ').strip().lower() not in ('y', 'yes'):
                    raise ValueError('Read access not approved')
        signature(path, MAX_METADATA_BYTES if mode == 'metadata' else belmont.MAX_BYTES)
        home = Path.home()
        destination, unit, _ = paths(home)
        if destination.exists() or unit.exists():
            state = installation_state(home)
            if state == 'present':
                print('Installation already present. Run python3 -m deck doctor, then pair with explicit server, AppID, mode and file. Restart the user service explicitly after pairing.')
            else:
                print('Partial installation found. From extracted source run python3 -m deck.install uninstall --keep-config, then repeat setup. No service has been enabled by this setup attempt.')
            return 1
        install(home, Path(__file__).resolve().parents[1])
        pair(Store(), Transport(server), path, appid=appid, mode=mode, ask=ask)
        if not enable:
            try:
                enable = ask('Enable and start this user-only background service now? [y/N] ').strip().lower() in ('y', 'yes')
            except EOFError:
                enable = False
        if enable:
            subprocess.run(['systemctl', '--user', 'enable', '--now', NAME + '.service'], check=True, timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print('User service enabled. Gaming Mode persistence still requires testing on your Deck.')
        else:
            print('Paired; background service is not enabled. Start it later with systemctl --user enable --now steam-game-companion.service.')
        print('Setup complete. Configure your phone assistant against the deployed service separately.')
        return 0
    except KeyboardInterrupt:
        print('Setup interrupted. Run python3 -m deck doctor from extracted source for recovery; any installed user files remain for inspection; no game saves were changed.')
        return 1
    except (watch.SnapshotError, OSError, ValueError, KeyError, TypeError, EOFError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print('Setup incomplete. Run python3 -m deck doctor from extracted source for recovery steps. If pairing failed offline or during a sleeping-host cold start, retry pair explicitly; existing pairing is retained until approval. No game saves were changed and no credentials logged.')
        return 1
