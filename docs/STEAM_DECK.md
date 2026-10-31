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

### Interrupted installation and private-state commits

The supported target for these operations is **Linux/SteamOS with POSIX directory
file descriptors, `O_NOFOLLOW`, atomic rename/link and directory fsync on the
user filesystem**. Other platforms/filesystems are not validated. Do not infer
complete race resistance: installer tree creation/copy/removal still includes
path-based operations, and another process running as the same user is outside
this protection boundary. Install only inspected source in your own session.

The installer creates a private destination and `.installing` marker before
copy/build. It builds the venv at its final path so its absolute paths remain
valid. A caught build failure or cancellation removes only the newly created
tree if its identity is unchanged; it leaves existing pairing/configuration
alone. An abrupt process exit can leave the marker and partial tree. Doctor
reports `installation: interrupted`, even if the unit and required files exist.

Only a complete, flushed unit is linked into place, privately and without
replacing an existing unit. The installer then requests daemon-reload; it never
enables or starts the service. A publication/reload error or timeout leaves the
marker for explicit recovery, because publication may already have succeeded.
From extracted source, run doctor, then explicitly uninstall with `--keep-config`
and repeat setup. A repeat setup never overwrites an existing installation.
A successful installation clears the marker. Power-loss integrity of the whole
copied tree/venv is not established by these tests.

Doctor also reports `installation: unit_mismatch` when the unit differs from the
expected complete text. Inspect it locally before starting; doctor does not print
or overwrite its contents. Presence/matching unit text still does not verify the
integrity of every installed source file or interpreter.

Uninstall now stops on a failed or timed-out `disable --now`, keeping installation
and config for inspection. If the unit file is absent, it checks the user manager
and permits removal only for inactive/unknown service status. A missing unit
file alone does not prove a loaded service has stopped. If the manager is
unavailable or service state is ambiguous, restore the normal user session and
stop the companion explicitly before retrying. No sudo or linger is added.

Store opens the private directory by components without following symlinks,
checks its owner/mode and remembers its identity. File reads, temporary writes,
locking and replacement are relative to a checked directory descriptor. Changing
the directory between operations requires reopening Store. Only `config.json`
and `state.json` are accepted state filenames.

Config/state writes flush a private temporary file, atomically replace the
selected state file and fsync the directory. Failure/cancellation before replace
retains the previous configuration. An error **after** replace may leave the
complete new configuration committed: inspect doctor rather than assume rollback.
An abrupt exit can leave private `.tmp-*` files; the client never loads them as
configuration or queue, and never promotes them automatically. They may contain
credentials, so do not share them. Explicit uninstall `--remove-config` removes
this entire private state directory after confirmed service stop. Pairing still
requires owner approval; the two-file config/state transition remains protected
by the existing generation checks, not a claimed multi-file transaction.

Additional owner checks on a real Deck: cancel an initial installation during
build, inspect doctor, then recover with the commands above; cancel pairing
before phone approval and verify the previous selection stays active; verify a
successful reinstall does not start a service without the explicit setup choice.
If stopping the service fails, verify files remain, restore the user session and
retry explicitly. Do not deliberately power-cut the Deck or corrupt real tokens
for this acceptance. Game Mode, suspend/resume, reboot and actual save paths
remain the separate hardware checks listed above.

## Python/Linux compatibility gate (prepared, not yet run in GitHub CI)

As checked on 2026-10-31, the companion/ZIP still declares Python **3.10+**;
this is separate from the backend README's Python 3.11+ requirement. Upstream
Python 3.10 reached end of life on 2026-10-01, while 3.12 receives security fixes
and 3.15 is a stable bugfix series. The legacy minimum remains a regression
check, not a recommendation to install an unsupported runtime. Use the supported
runtime supplied by SteamOS; missing prerequisites are not permission to change
the system image. Source: [official Python version status](https://devguide.python.org/versions/).

The separate `.github/workflows/deck-compatibility.yml` pins these CPython builds
on GitHub-hosted Ubuntu 24.04 x64:

| Build | Purpose | Evidence before publication |
| --- | --- | --- |
| 3.10.22 | Previously declared minimum, legacy compatibility only | Not executed locally or in this new workflow yet |
| 3.12.16 | Current working 3.12 series, updated security patch | Local evidence is 3.12.14, not this exact build |
| 3.15.2 | Latest stable maintenance build found during research | Not executed locally or in this new workflow yet |

The exact builds were present as stable Ubuntu 24.04 x64 entries in the
[official actions/python-versions manifest](https://github.com/actions/python-versions/blob/main/versions-manifest.json).
Python 3.15.2 was released on October 25:
[official release](https://www.python.org/downloads/release/python-3152/).
Versions are pinned, not floating `3.x`; update them in a reviewed change after
checking current upstream security releases. Ubuntu's hosted runner image can
still change, so this is not a bit-for-bit fixed OS environment.

The workflow uses only `contents: read`, has no secret inputs, dependency install,
cache, artifact publication or deploy step, and does not use `pull_request_target`.
Checkout disables persisted credentials. The two official actions are pinned
to verified upstream release commits: [checkout v6.0.3](https://github.com/actions/checkout/releases/tag/v6.0.3)
(`df4cb1c069e1874edd31b4311f1884172cec0e10`, the peeled commit of its annotated tag)
and [setup-python v7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0)
(`5fda3b95a4ea91299a34e894583c3862153e4b97`). Both use Node 24 on the hosted runner.
Setup obtains interpreters through the official action distribution; the
companion itself remains stdlib-only.

Run the same focused gate from a source checkout:

```sh
python -I -S tools/check_deck_compatibility.py
```

It explicitly selects companion, watcher and Belmont contract tests without
importing backend integration tests. It fails on errors or skipped tests and
prints the actual Python version. Tests use synthetic files and mocked systemctl;
the watcher has a synthetic loopback HTTP test. Archive checks verify deterministic
bytes, the code allowlist, private-file exclusion and doctor in an extracted ZIP
without site-packages or access to systemctl. These checks do not run a real user
service, phone pairing or SteamOS. The packager/installer/doctor implementation is
unchanged by this compatibility slice. The new workflow has **not been run in
GitHub Actions yet**; only publication and successful matrix results can establish
those exact-build CI claims. Local validation of this runner passed **113 tests,
zero skips** on both Python **3.12.14** and **3.13.5** with `-I -S`; those are
executor results, not the pinned GitHub matrix or SteamOS. Passing Linux CI does not prove all Python versions
between the selected points, SteamOS filesystem behavior or Deck hardware gates.

## Manual upgrade of an existing companion (no automatic updater)

This is a reviewed reinstall procedure for versions retaining the current
config/state format and protocol. There is no transactional updater, automatic
rollback, network update daemon or state-migration tool. For these changes the
existing private pairing can be retained: **use `install`, not guided `setup` or
`pair`**, because those flows request a new pairing. Expiry, revocation or a
changed game/file/scope still requires a separately approved pairing. Doctor's
local validity is not proof of remote consent.

1. **Prepare before stopping anything.** On the Deck, download the new code-only
   ZIP from the deployment's HTTPS `/setup` page. Keep the previously reviewed
   archive/extracted source for rollback, outside the installed companion tree.
   Obtain the expected SHA256 tied to the exact reviewed release. Run
   `sha256sum deck-companion.zip` in the download directory and compare the full
   digest. A checksum fetched beside the ZIP detects mismatches, but is not an
   independent signature or protection against a compromised publisher. If the
   release/hash cannot be established, leave the current installation alone.
2. **Inspect and stage separately.** List the verified ZIP using
   `python3 -I -m zipfile -l deck-companion.zip`. The expected members are
   `LICENSE`, `README.md`, `agent/watch.py`, `decoders/__init__.py`,
   `decoders/belmont.py`, and `deck/{__init__,__main__,client,discovery,install,setup,doctor}.py`.
   Refuse unexpected files, absolute/traversal names, links or bundled state.
   Extract into a newly created empty directory, never over the current source
   or config. Review source/release changes before executing it. Do not copy the
   private config or queue into the source directory or an uploadable archive.
3. **Check locally, then choose.** From the new extracted directory run
   `python3 -m deck doctor`. Note the redacted pairing/service/autostart statuses.
   Stop for `unit_mismatch`, unsafe paths or unknown state compatibility; inspect
   locally instead of overwriting. Ensure Python/venv/user-systemd prerequisites
   exist. Up to here cancellation leaves the old installation and service alone.
4. **Remove code while retaining pairing.** Stay in the separately extracted
   directory, not the installed directory that is about to be removed. Run:

   ```sh
   python3 -m deck.install uninstall --keep-config
   ```

   This explicitly disables/stops the companion and removes its installed code
   and unit, retaining private config and queued state. Do **not** use
   `--remove-config` for an upgrade. If the command fails or is interrupted, run
   doctor before repeating; service/file state may already have changed. A
   failed stop blocks deletion. There is a service outage from this step onward.
5. **Install reviewed code without replacing pairing or starting a service.**
   From the new extracted directory run:

   ```sh
   python3 -m deck.install install
   python3 -m deck doctor
   ```

   Require `installation: present`, expected local pairing/selection and no
   unresolved private-state error. Installation only reloads the user manager;
   it neither pairs nor enables/starts. If the credential is expired/revoked,
   complete the explicit phone-approved `pair` procedure before proceeding.
6. **Resume only by owner choice.** For this session only, explicitly run
   `systemctl --user start steam-game-companion.service`; for user-session
   autostart, explicitly run
   `systemctl --user enable --now steam-game-companion.service` instead.
   Uninstall does not preserve the previous enabled setting. Check doctor and
   verify a new service receipt from the phone after stable checks/backoff.
   Never infer successful delivery from local pairing or file mtime alone.

**Cancel/recover after removal:** leaving the service stopped is valid. If the
new install is incomplete, run doctor and explicitly uninstall it with
`--keep-config` before retrying. To return to the previous version, change to its
retained, independently reviewed extracted source and perform the same
`install` → doctor → explicit start steps. If new code has already been installed,
remove it with `--keep-config` first. Do not copy an installed venv between paths;
rebuild it through install. This rollback is limited to versions with confirmed
state/protocol compatibility. It cannot undo remote consent changes, restore a
revoked credential or promise recovery from arbitrary future migrations. No
private-state backup/restore or verified automatic rollback exists yet.

The next small implementation, if needed, should be a **local dry-run upgrade
preflight**: validate existing installation and an independently verified new
archive, compare declared state compatibility, report planned stop/reinstall
steps, and perform no writes/network/service mutation. A later explicitly invoked
upgrade could add a journal and recovery after each stage. Required tests include
interruption before/after stop, failed build/reload, preserved config hashes,
unsupported state versions and a rollback candidate rejected when compatibility
is unknown. Do not call this upgrade transactional until those behaviors exist.

Physical gates still belong to the owner: Desktop Mode upgrade/cancellation,
actual permissions on the Deck filesystem, real systemctl stop/start and consented
phone receipt; then Game Mode transition, suspend/resume, reboot and battery/latency
observations. CI and synthetic failure injection do not close those gates.

## Synthetic owner-journey checkpoint

`tests/test_deck_acceptance.py` connects the existing installer, setup, Store,
pairing, Runner and doctor in three reproducible journeys. It uses a temporary
home and synthetic save, a stub venv, an in-memory HTTPS peer and a small service
model. A socket guard rejects real sockets; subprocess calls are intercepted.
The service model is a test fixture, **not a simulation that proves systemd or
SteamOS behavior**. Pairing approval is a separate test-owner action after a
pending poll; no production approval behavior is changed.

| Journey | Assertions |
| --- | --- |
| First setup → pending approval → declined background start → explicit test-owner start → metadata send → revocation → approved re-pair | No credential or observation before approval; only size/time sent; revoked send returns CLI exit 3; old queue is not carried into the new pairing; pairing does not restart the service. The unit's exit-3 rule is checked as text only. |
| Interrupt initial daemon-reload → repeat setup → explicit uninstall/retry | Doctor reports `interrupted`; no pairing request or background enable occurs; repeated setup refuses overwrite; explicit recovery produces an installation awaiting owner start. |
| Offline queue → keep-config uninstall → cancelled build → manual reinstall → explicit start | Config and state remain byte-identical through cancellation/reinstall; no new pairing request occurs; queued event retains its ID and sends after simulated connectivity returns. |

The companion leaves the synthetic save unchanged. The revocation journey has
one explicit fixture write representing a new game save; the companion does not
perform that write. Tests check diagnostic/output redaction without publishing
paths, credentials or save contents. They do not contact Steam or the hosted API.

Run this standalone stdlib-only acceptance layer from the source root:

```sh
python -S -m unittest discover -s tests -p 'test_deck_acceptance.py' -v
```

This checkpoint passed **3 journeys on Python 3.12.14 and 3.13.5**, without skipped
tests. These executor results do not establish the exact pinned CI versions.
Python **3.10 remains EOL legacy compatibility only**, not a safe recommended
runtime; the official lifecycle source is linked in the compatibility section.

**Integration dependency:** the frozen compatibility runner's `MODULES` tuple in
`tools/check_deck_compatibility.py` must gain `test_deck_acceptance` in a separately
reviewed integration change. Until then its focused matrix does not run this new
module, even though its path filter matches the filename. Standard unittest
full discovery includes it automatically. No workflow/runtime change is part of
this acceptance patch.

### Minimum owner check on an actual Deck

Use the reviewed archive and a normal-user Desktop Mode session; keep only
redacted status labels and observed timing in the acceptance record.

1. Check Python/venv/user-systemd prerequisites and doctor. Select one real file
   and metadata mode explicitly; confirm the same scope on the phone. Decline
   background start once and check that the companion is not running. Then
   explicitly enable/start it and verify a new service receipt after a normal
   in-game save. Size/time is not game-progress evidence.
2. With the companion deliberately stopped, cancel a replacement pairing before
   phone approval and check that the previous local selection remains. Exercise
   the documented keep-config reinstall only after retaining a verified old
   archive; check that it remains stopped until explicitly started. Never
   deliberately power-cut the Deck or damage a token to manufacture a failure.
3. Revoke the device/scope through the service, make a normal in-game save, and
   verify that delivery stops with re-pair required. Restore only through fresh
   phone approval and an explicit service restart. Then confirm a fresh receipt.

This minimum check is still **pending**. Successful Desktop Mode execution would
not establish Game Mode transition, suspend/resume, reboot persistence, real save
path discovery, free-host cold-start/offline latency, battery use, all Python
versions or the selected phone assistant's connector. Those remain the distinct
hardware/external gates above. No synthetic result should be recorded as passing
one of them; actual Deck/phone access is the next external dependency.
