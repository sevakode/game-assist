"""Local, read-only diagnostics. Never contact the server or print private state."""
import importlib.util
import json
import os
import stat
from pathlib import Path
import shutil
import subprocess
import time

from .client import Store, selection, signature, server_origin, MAX_METADATA_BYTES, belmont, watch
from .install import paths, require_safe, unit_text, NAME


def installation_state(home):
    destination, unit, _ = paths(home)
    for path in (destination, unit):
        require_safe(path)
    if not destination.exists() and not unit.exists():
        return 'missing'
    if (destination / '.installing').exists() or (destination / '.installing').is_symlink():
        return 'interrupted'
    required = (destination / 'source/deck/__main__.py',
                destination / 'source/deck/client.py', destination / 'venv/bin/python', unit)
    if not all(path.is_file() for path in required):
        return 'partial'
    fd, _ = watch._open_root(unit)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or stream.read(8193) != unit_text(destination).encode():
            return 'unit_mismatch'
    return 'present'


def service_state(operation):
    """Use only fixed systemctl operations; discard all untrusted diagnostic text."""
    allowed = {'is-active': {'active', 'inactive', 'failed', 'activating', 'deactivating'},
               'is-enabled': {'enabled', 'disabled', 'static', 'masked', 'not-found'}}
    try:
        result = subprocess.run(['systemctl', '--user', operation, NAME + '.service'],
                                capture_output=True, text=True, timeout=5, check=False)
        value = result.stdout.strip()
        return value if value in allowed[operation] else 'unavailable'
    except (OSError, subprocess.TimeoutExpired):
        return 'unavailable'


def report(home=None, now=None):
    home = Path.home() if home is None else Path(home)
    now = time.time() if now is None else now
    result = {'installation': 'unsafe_or_unreadable', 'pairing': 'missing',
              'selected_file': 'not_checked', 'queue': 'none', 'sync': 'not_synced',
              'network': 'not_tested', 'summary_format': 'not_tested',
              'venv_available': importlib.util.find_spec('venv') is not None}
    actions = []
    try:
        result['installation'] = installation_state(home)
    except (OSError, ValueError, watch.SnapshotError):
        actions.append('Inspect unsafe installation locally; do not use sudo.')
    if result['installation'] in ('partial', 'interrupted'):
        actions.append('From extracted source run: python3 -m deck.install uninstall --keep-config; then repeat setup.')
    elif result['installation'] == 'unit_mismatch':
        actions.append('Inspect the companion unit locally; it differs from the expected unit. Do not start it until reviewed. No automatic replacement is performed.')
    elif result['installation'] == 'missing':
        actions.append('Run setup explicitly from the extracted source.')
    result['service'] = service_state('is-active') if shutil.which('systemctl') else 'unavailable'
    result['autostart'] = service_state('is-enabled') if shutil.which('systemctl') else 'unavailable'
    directory = paths(home)[2]
    try:
        require_safe(directory)
        if directory.exists():
            store = Store(directory, create=False)
            config = store.read('config.json')
            if config:
                appid, mode = config.get('appid', 4231820), config.get('mode', 'belmont-summary')
                selection(appid, mode)
                server_origin(config['server'])
                token = config['device_token']
                if not isinstance(token, str) or not token or len(token) > 4096 or any(c.isspace() for c in token):
                    raise ValueError('Invalid credential')
                expires = config.get('expires_at')
                if type(expires) not in (float, int) or not 0 < expires < float('inf'):
                    raise ValueError('Invalid expiration')
                result['pairing'] = 'expired' if now >= expires else 'locally_valid_remote_not_checked'
                result['appid'], result['mode'] = appid, mode
                try:
                    limit = MAX_METADATA_BYTES if mode == 'metadata' else belmont.MAX_BYTES
                    first = signature(config['path'], limit)
                    result['selected_file'] = 'regular_bounded' if first == signature(config['path'], limit) else 'changing'
                except (OSError, ValueError, TypeError, KeyError, watch.SnapshotError):
                    result['selected_file'] = 'missing_unsafe_or_unreadable'
                state = store.read('state.json')
                if (state.get('pairing_id') != config.get('pairing_id')
                        or state.get('appid', 4231820) != appid
                        or state.get('mode', 'belmont-summary') != mode):
                    result['queue'] = 'old_pairing_ignored'
                else:
                    result['queue'] = 'pending' if state.get('queue') else 'none'
                    status = state.get('sync_status')
                    if status in ('synced', 'offline_or_rejected', 'pairing_or_consent_required'):
                        result['sync'] = status
    except (OSError, ValueError, TypeError, KeyError, watch.SnapshotError):
        result['pairing'] = 'invalid_or_unreadable'
        actions.append('Inspect private configuration permissions locally; never share config or tokens.')
    if result['pairing'] in ('missing', 'expired') or result['sync'] == 'pairing_or_consent_required':
        if result['installation'] == 'present':
            actions.append('Run pair with explicit server, AppID, mode and file; approve on your phone. Then explicitly restart the user service.')
        else:
            actions.append('Recover or review the installation first; then run doctor again before pairing or starting the service.')
    if result['selected_file'] in ('changing', 'missing_unsafe_or_unreadable'):
        actions.append('Wait for saving to finish; verify your selected regular file locally. To change selection, pair again.')
    if result['sync'] == 'offline_or_rejected':
        actions.append('Check Deck connectivity and the service /setup page. A sleeping host may take a minute; the bounded queue retries automatically.')
    if result['installation'] == 'present' and result['service'] != 'active':
        actions.append('In normal-user Desktop Mode check the user session. After pairing, explicitly enable/start or restart steam-game-companion.service if desired.')
    result['actions'] = actions
    return result


def doctor():
    print(json.dumps(report(), ensure_ascii=False))
    return 0
