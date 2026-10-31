# Steam Deck companion — source implementation, not hardware-validated

No separate PC is intended. A small **Deck-side Linux user service** observes
one explicitly selected local save file while you play. A separately deployed
HTTPS service lets your phone's Claude/ChatGPT client request permitted data.
Steam login alone does not read Deck saves. The service and phone connector must
be configured separately; source code alone does not establish a working connection.

**One installation watches one file for one selected game, not your whole library.**
The AppID/file association is your declaration, not proof that the file belongs
to that game. Selecting games on the website does not automatically watch them.

## Choose what may leave the Deck

- **`metadata` — default for new pairing/setup:** only the file's size in bytes
  and reported modification time. No decoder is needed. The file is opened
  read-only for stable descriptor metadata checks; its contents are not read,
  hashed, decoded, or uploaded. This does **not** let the AI read your save or
  determine game progress. Supported file size: up to 1 GiB.
- **`belmont-summary` — explicit option:** only app **4231820**, Belmont format
  **1.1.3**, files up to 32 MiB. Reads locally and uploads the existing decoder's
  four raw player scalar fields, semantic caveats and coverage markers. Health
  and mana are **current values, not maxima**; fragment-counter semantics remain
  unknown. No pickup or location conclusions. Unsupported/invalid versions fail
  closed; the client never silently switches permission or upload modes.

Neither mode sends raw save contents, full paths, filenames, hashes or opaque
entity identifiers. Neither edits saves, extracts archives, executes save data,
inspects game memory, controls input, or polls Steam metadata.

## One-time setup in Desktop Mode

Inspect the source first. Python 3.10+ with `venv` and a functioning
`systemctl --user` session are prerequisites. The installer uses only the Python
standard library: no pip, sudo, SteamOS read-only changes, downloaded executables
or implicit linger setting. If prerequisites are missing, stop rather than
modifying the OS. Run as your normal Deck user, never root.

From the source directory:

```sh
python3 -m deck setup \
  --server https://YOUR-DEPLOYED-SERVICE.example \
  --appid 1245620 --mode metadata \
  --path '/absolute/explicit/path/to/one/save-file'
```

Replace the server placeholder with your actual configured HTTPS origin and
choose the correct AppID/file. AppIDs must be integers from 1 to 2147483647.
For an unknown game, add/register it in your service catalogue before approving
pairing. No parser is required for minimal metadata permission.

If omitted, setup asks for the AppID. For Belmont it offers metadata (default)
or the explicit summary option; other games use metadata. For an unknown game,
omitting `--path` prompts for an actual absolute file path and confirmation—no
folder or home-directory scan. Select one regular file, not a directory. Symlink
components and special files are rejected; use a physical path rather than a
Steam shortcut symlink.

Setup validates the selection, preflights/installs user files, then displays a
short-lived phone verification page and code. Open it on your phone, sign in
through the official Steam flow, compare the code and approve the **same game
and requested scope**: `saves.metadata` or `saves.summary`. Never paste Steam
passwords or device tokens into chat. Credentials are stored only in a private
mode-0600 config within `~/.config/steam-game-companion` (directory mode 0700),
never printed. No save observation is uploaded before explicit approval.

Setup then asks whether to enable/start the user service. Answer `y` only if you
want background operation, or pass `--enable` to authorize it explicitly after
successful pairing. Failed/interrupted pairing never enables it. Partial user
installation files remain for inspection. This is **CLI onboarding**, not a
finished graphical or zero-touch experience.

### Optional Belmont-only path suggestions

For app 4231820, setup without `--path` may suggest existing candidates within
`~/.local/share/Steam` and at most 32 library paths from its bounded 64-KiB
`steamapps/libraryfolders.vdf`. The fixed candidate suffix is:

```text
steamapps/compatdata/4231820/pfx/drive_c/users/steamuser/AppData/LocalLow/KONAMI/Castlevania Belmont's Curse/BuildSave_0.sav
```

This is a known Windows/Proton-layout suggestion, **not a real-Deck verified
location**. Discovery reads no save contents, scans no other app IDs or slots,
and rejects symlinks and unsafe/malformed/oversized VDF input. One candidate
still needs confirmation; multiple candidates need selection and confirmation.
If none is found, supply an actual path or cancel. For metadata files beyond the
Belmont discovery size limit, supply `--path` directly.

`python3 -m deck discover --appid 4231820` only lists these bounded suggestions;
it does not pair, install or upload. Other AppIDs have no automatic discovery.

### Manual installation or later re-pairing

```sh
python3 -m deck.install install
cd "$HOME/.local/share/steam-game-companion/source"
../venv/bin/python -m deck pair \
  --server https://YOUR-DEPLOYED-SERVICE.example \
  --appid 1245620 --mode metadata \
  --path '/absolute/explicit/path/to/one/save-file'
```

`pair` requires explicit `--appid`, `--server` and `--path`; its default mode is
metadata. To request Belmont decoding, use `--appid 4231820 --mode belmont-summary`.
Existing legacy configurations retain their original Belmont-summary mode;
changing mode requires fresh explicit pairing and approval.

Re-pairing asks before replacing the existing single-game/file configuration
and queue. It does not add a second watcher. A generation ID plus AppID/mode
binding and locking prevents old queues crossing accounts, games or scopes;
an old running process exits when the pairing changes. Replacing local config
is not automatic revocation of the old remote device—revoke it on the service
when appropriate. Restart the user service after successful re-pairing.

## Background operation and status

If setup did not enable the service, explicitly start it from Desktop Mode:

```sh
systemctl --user enable --now steam-game-companion.service
cd "$HOME/.local/share/steam-game-companion/source"
../venv/bin/python -m deck status
```

After re-pairing an already-enabled service, use
`systemctl --user restart steam-game-companion.service`.

Return to Gaming Mode. The target is operation in the same user's systemd
session; **Desktop→Gaming Mode persistence, battery cost, suspend/resume and
actual Deck save compatibility have not been hardware tested**. Suspend stops
observations until wake. Two stable checks are required, initially 60 seconds
apart; idle checks back off to ten minutes.

`status` reports the selected AppID/mode, observation status, queue and local
observation/sync timestamps, without exposing credentials or file paths. It
is not proof that the phone connector is healthy. A file's reported modification
time is not trusted freshness: keep it separate from the service's receipt time.
Metadata-only state means contents and progress are unknown. Configure the phone
client against the remote service separately; never reuse the Deck credential
as a Claude/ChatGPT credential.

A private bounded queue retains only the latest changed sanitized observation
with a UUID for idempotent retries. Unchanged files avoid duplicate content
scans after restart. Offline retries use bounded exponential jitter. Unreadable,
unstable, oversized or unsupported summary files leave previous remote data
unchanged rather than pretending to be current. Revocation/401/403 or credential
expiry stops sending and requires explicit re-pairing.

HTTPS uses ordinary certificate verification, one fixed origin, no redirects
and no environment proxies. `--allow-local-test` permits only explicit loopback
HTTP development; it is never stored in config or included in the installed
unit, and guided setup does not accept it.

## Stop / uninstall

```sh
systemctl --user disable --now steam-game-companion.service
# From the original source checkout, choose exactly one:
python3 -m deck.install uninstall --keep-config
# OR remove the local credential, queue and state:
python3 -m deck.install uninstall --remove-config
```

Only this companion's user installation/unit and optionally its config are
removed; original saves remain untouched. Keeping config keeps a credential.
Remote device revocation is a separate explicit action. No Windows support or
installed/hardware-tested status is claimed.

## Local doctor and recovery

From the extracted source, or the installed source directory, run:

```sh
python3 -m deck doctor
```

Doctor emits a small JSON report with fixed status values and recovery actions.
It does not install/start/stop anything, create configuration, contact the server,
read save contents (even in summary mode), or print paths/tokens/queued payloads.
Its exit code 0 means the report was produced, **not** that every check passed.
`network: not_tested` and `summary_format: not_tested` are deliberate: a readable
file does not prove format support, current consent or working phone integration.
`installation: present` checks required files exist, not their code integrity.
Each service query times out after five seconds; unavailable user-systemd is
reported without exposing raw systemctl output. Installation/service mutations
have a 15-second command timeout; a timeout may leave a completed or partial
operation, so inspect with doctor before repeating it.

| Report / situation | Explicit recovery |
| --- | --- |
| `installation: partial` | From extracted source: `python3 -m deck.install uninstall --keep-config`, then repeat setup. This stops/removes only companion files, retaining private pairing state. |
| Installed but pairing interrupted | Run `pair` using the explicit server, AppID, mode and selected file as above. Setup does not overwrite an existing installation. |
| `pairing: expired` or `sync: pairing_or_consent_required` | Re-pair with fresh phone approval; then explicitly restart the user service. Confirm the per-game scope on the service. |
| `sync: offline_or_rejected` | Check connectivity and open the deployed `/setup` page. Free-host wake-up may take about a minute. The observation queue retains the latest permitted observation and retries; no extra permission is granted. |
| Pairing start fails during cold start | No local pairing changed. Wait for the service to respond, then run `pair` again for a fresh code. |
| Pair polling temporarily fails | Transient network/408/429/500/502/503/504 failures retry within the original bounded code lifetime, with polling delayed up to 60 seconds. Expired codes require a fresh explicit pairing. |
| `selected_file: missing_unsafe_or_unreadable` | Verify the actual selected file locally after the game finishes saving. Directories, FIFO/special files and symlinks are refused. Changing selection requires pairing again. |
| `queue: old_pairing_ignored` | A previous generation's queue will not be sent. Restart the service after successful pairing; new stable observations replace stale local state. |
| `service: unavailable` | Use the normal user's Desktop Mode session; confirm Python/venv/user-systemd prerequisites. Do not use sudo or modify SteamOS protections. |

A cancelled, denied or timed-out replacement keeps the previous local pairing
until a new approval is committed. A previously running old service may continue
under its old permission during this time: explicitly stop it first if desired.
If interrupted between writing new config and resetting state, generation checks
ignore the old queue. Successful pairing followed by a later setup/service error
may already have saved the new credential: doctor distinguishes local pairing
from service state. The original remote device must be revoked separately.
Do not share config files, raw service logs, save files or private paths as a
support report. Doctor is the intended redacted diagnostic surface.

## Physical Steam Deck acceptance — still pending

Use the reviewed ZIP on the Deck itself; no separate computer is required.
Record SteamOS/Python version and status labels only. Do not record personal
paths, pairing codes, tokens, screenshots containing them, or save contents.

1. In normal-user Desktop Mode extract the reviewed ZIP and run doctor. Confirm
   Python/venv and user-systemd availability. On a fresh device the installation
   and pairing must be missing; doctor must not create them.
2. Start the chosen game, save and exit. Locate the actual file locally; the
   documented Proton suggestion is unverified. Select one physical regular file
   and its AppID. Begin with metadata. Confirm on the phone the same game and
   `saves.metadata`; decline service enablement once. Doctor must show local
   pairing with no background service started by setup.
3. Explicitly enable the service with the command above. Allow at least two
   stable observations (initially 60 seconds apart; later idle intervals reach
   ten minutes). Confirm the service receipt separately from the file mtime.
   Metadata must show only size/time and unknown progress. Compare the selected
   original locally before/after a read-only run; never upload the comparison.
4. Stop the companion explicitly. Start a replacement pairing, cancel before
   phone approval, and run doctor. The previous configuration must remain. Repeat
   pairing, approve on the phone, and explicitly restart the service. Confirm
   fresh observations are under the new selection only; revoke the old device.
5. Disable Deck networking, make a legitimate in-game save, wait for stable
   checks, then run doctor: expect a pending queue and offline/rejected status.
   Restore networking; allow backoff (up to 72 minutes of retry backoff with jitter, plus
   up to ten minutes before the next idle check) and verify a service receipt. No raw save should leave the Deck.
   Repeat against a sleeping free host and record actual wake-up/delivery delay.
6. With owner-authorized service enabled, test Desktop→Game Mode, save, suspend,
   resume, then reboot independently. After each, check service state and new
   receipts from the phone, recording observed latency. These are separate
   hardware gates; passing local tests does not establish any of them.
7. Revoke the device/consent on the service and make another legitimate save.
   Confirm sending stops with re-pair required (exit 3, no restart loop).
   Restore only through explicit pairing and scope approval. For token expiry,
   use a controlled test service with short-lived credentials or wait for actual
   expiry; never edit production credentials to simulate a result.
8. If Belmont summary is desired, separately re-pair AppID 4231820 with
   `belmont-summary` and `saves.summary` approval. Validate format 1.1.3 and only
   the four permitted raw fields. Do not infer maxima, pickups or locations.
9. Explicitly uninstall with `--keep-config`, confirm service stopped and original
   save intact; reinstall/re-pair as needed. Finally test `--remove-config` and
   remote device revocation separately. Record success/failure per step rather
   than declaring complete Deck support from a partial run.

This companion remains optional. It does not provide automatic Steam Cloud
access, guarantee Game Mode persistence, or establish a mobile ChatGPT connector.
