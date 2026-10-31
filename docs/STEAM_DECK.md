# Steam Deck companion — source implementation, not hardware-validated

No separate PC is intended: a small **Deck-side Linux user service** reads one
explicitly selected save file while you play; a separately hosted HTTPS service
lets your phone's Claude/ChatGPT client request the sanitized summary. The remote
service must first be deployed and its browser/account integration configured.
This repository is not evidence that a live service or a working Claude/ChatGPT
connection already exists. Steam login alone does not read Deck saves.

## One-time setup in Desktop Mode

Inspect this source before running it. Python 3 with `venv` and a functioning
`systemctl --user` are prerequisites. The installer is stdlib-only: no pip,
`sudo`, SteamOS read-only changes, external installer downloads, or auto-login.
If these prerequisites are unavailable, stop rather than modifying the OS.

From the repository directory, as your normal Deck user, the guided **CLI**
setup validates your selected path, preflights and installs user files, pairs on
your phone, then asks whether to enable the background service:

```sh
python3 -m deck setup \
  --server https://YOUR-DEPLOYED-SERVICE.example \
  --path '/absolute/explicit/path/to/your/Belmont-save-file'
```

You may omit `--path`: setup suggests only existing files at the known Proton
layout for app 4231820, within `~/.local/share/Steam` and at most 32 library paths
from its bounded `steamapps/libraryfolders.vdf`. The fixed suffix is
`steamapps/compatdata/4231820/pfx/drive_c/users/steamuser/AppData/LocalLow/KONAMI/Castlevania Belmont's Curse/BuildSave_0.sav`.
This layout is a suggestion based on the known Windows/Proton path, **not a
real-Deck verified location**. No recursive home/library scan occurs; no other
app IDs or save slots are enumerated. Discovery opens/fstats candidates but
never reads their save contents. Symlinks and unsafe/malformed/oversized VDF
inputs are rejected. A single suggestion still requires confirmation; multiple
ones require a numbered selection then confirmation. If none exists, enter an
actual explicit absolute path or cancel. `python3 -m deck discover` only lists
these bounded suggestions and does not pair, install, or upload anything.

Answer `y` only if you want the user service enabled. Alternatively, add
`--enable` to explicitly authorize enabling after successful pairing. No service
is enabled after a failed/interrupted pairing. Partial installation is left for
inspection rather than deleted automatically. This is CLI onboarding, not a
finished graphical or zero-touch experience. Phone connector setup is separate.

For manual installation/pairing instead:

```sh
python3 -m deck.install install
cd "$HOME/.local/share/steam-game-companion/source"
../venv/bin/python -m deck pair \
  --server https://YOUR-DEPLOYED-SERVICE.example \
  --path '/absolute/explicit/path/to/your/Belmont-save-file'
```

The placeholder is not a deployed service. Choose **one actual Belmont 1.1.3
save file for app 4231820**, not a directory or whole Steam library. There is no
home-directory scan or automatic path selection. Symlink path components are
rejected; use an actual physical path (Steam's familiar shortcut paths may be
symlinks). The source file remains read-only and unchanged.

Pairing displays a short-lived verification page and code; open them on your
phone, use the official Steam sign-in flow, and approve this device and the
specific save-summary grant. Never paste Steam passwords or device tokens into
chat. The scoped credential is stored only in a private mode-0600 config under
`~/.config/steam-game-companion` (directory mode 0700). It is never printed.
Pairing grants no automatic permission to read raw saves or all games.

If you used manual setup, or declined guided setup's enable prompt, explicitly start background operation:

```sh
systemctl --user enable --now steam-game-companion.service
../venv/bin/python -m deck status
```

Return to Gaming Mode. This targets background operation in the same user's
systemd session; **Desktop→Gaming Mode persistence, battery cost, suspend/resume,
and actual Deck save compatibility have not been hardware tested**. Suspend
stops observations until the Deck wakes. No system linger setting is changed.
A fresh summary requires the game to write its save and two stable checks,
initially 60 seconds apart; idle checks back off to ten minutes. No game memory
inspection, input control, process injection, or polling Steam metadata occurs.

The phone interface should show observation freshness and disconnected/stale
state. `status` prints only paired/queued state and observation/sync timestamps.
It does not prove that your service or phone connector is healthy. Configure the
phone client against the deployed service separately; do not expose this Deck
credential to the phone or reuse it as a Claude/ChatGPT credential.

## Data and failure behavior

Only the existing decoder's four raw player scalar fields, semantic caveats,
and coverage markers are uploaded. Health/mana are **current, not maxima**;
fragment-counter semantics remain unknown. No pickup or location claims.
No raw saves, file names, paths, opaque entity IDs, hashes, or metadata are sent.
A private bounded queue keeps only the latest sanitized changed summary, with a
UUID event ID for retries. Restart uses a local file signature to avoid duplicate
full scans of an unchanged save. Retrying uses bounded exponential jitter;
401/403 or credential expiry stops the service for explicit re-pairing.
HTTPS uses ordinary certificate verification, one fixed server origin, no
redirects, and no environment proxies. Re-pair to change path/server/account. A private generation ID binds each queue
to its pairing; an old running process exits on configuration change. Restart
the user service after successful re-pairing.
`--allow-local-test` is only for explicit loopback-HTTP development; it is never
written into config or included in the installed unit.

## Stop / uninstall

```sh
systemctl --user disable --now steam-game-companion.service
# From the original source checkout, choose exactly one:
python3 -m deck.install uninstall --keep-config
# OR remove the local credential, queue and state:
python3 -m deck.install uninstall --remove-config
```

Uninstall only removes this companion's user installation/unit and optionally
its config. It never removes game saves. Keeping config keeps a credential;
revoking the device at the remote service is a separate explicit action.
No Windows support or installed/hardware-tested status is claimed.
