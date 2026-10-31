"""Explicitly invoked guided CLI setup; no privileged operations."""
import os
from pathlib import Path
import subprocess
import sys

from .client import Store, Transport, pair, server_origin, signature
from .install import install, paths, NAME


def setup(server, path=None, *, enable=False, ask=input):
    """Install -> phone pairing -> opt-in user service. Never called implicitly."""
    if sys.platform != 'linux' or os.geteuid() == 0:
        print('Use your normal Linux/Steam Deck user in Desktop Mode, never sudo.')
        return 1
    try:
        server_origin(server)  # Reject insecure origins before installation.
        if path is None:
            from .discovery import choose_path
            path = choose_path(ask=ask)
        signature(path)
        home = Path.home()
        destination, unit, _ = paths(home)
        if destination.exists() or unit.exists():
            print('Existing installation found. Use pair to re-pair, or uninstall --keep-config before replacing.')
            return 1
        install(home, Path(__file__).resolve().parents[1])
        pair(Store(), Transport(server), path)
        if not enable:
            try:
                enable = ask('Enable and start this user-only background service now? [y/N] ').strip().lower() in ('y', 'yes')
            except EOFError:
                enable = False
        if enable:
            subprocess.run(['systemctl', '--user', 'enable', '--now', NAME + '.service'], check=True)
            print('User service enabled. Gaming Mode persistence still requires testing on your Deck.')
        else:
            print('Paired; background service is not enabled. Start it later with systemctl --user enable --now steam-game-companion.service.')
        print('Setup complete. Configure your phone assistant against the deployed service separately.')
        return 0
    except KeyboardInterrupt:
        print('Setup interrupted. Any installed user files remain for inspection; no game saves were changed.')
        return 1
    except (OSError, ValueError, KeyError, TypeError, EOFError, subprocess.CalledProcessError):
        print('Setup incomplete. Inspect the user installation and service prerequisites; no game saves were changed and no credentials logged.')
        return 1
