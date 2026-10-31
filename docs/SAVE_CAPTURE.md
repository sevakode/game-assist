# Private Belmont research capture (Linux)

`python -m decoders.capture` prepares **one unencrypted private research package**
from one explicitly selected copy of a Belmont JSON `1.1.3` save. It does not
search for saves, connect to Steam, start a game, synchronize Cloud, write to the
source, or establish pickup semantics. No extra dependency is installed.

The package contains `snapshot.sav` (the complete private bytes) and
`observation.json` (unverified user-supplied context). **Never publish, attach,
commit, or upload this directory.** It may contain account and world identifiers.
Filesystem permissions restrict access; they are not encryption and do not
protect against the same OS user, administrators, backups, or cloud-drive sync.
Choose local storage outside synchronized/shared folders yourself.

## Smallest useful workflow

Create a new private parent outside every Git checkout. It must already exist,
be owned by the current OS user, and have mode `0700`. Use a fresh directory;
there is no overwrite or Git-destination override option.

```sh
mkdir -m 700 "$HOME/game-assist-private-research"
```

Select a stable copy of the save yourself. Record the installed game build
separately from save-format `1.1.3`, the platform, a trial role, before/after phase
and the single observed action. Example placeholders below are not real evidence:

```sh
python -m decoders.capture \
  --source /private/selected-copy.sav \
  --destination "$HOME/game-assist-private-research/action-before" \
  --role action --phase before --action hp_pickup \
  --build EXACT_BUILD --platform steamos_proton --confirm-capture
```

Run again with a separately selected after-copy and a **new** destination such
as `action-after`. Capture a no-action control pair (`--role control --action
no_action`) and an independently comparable repeat pair (`--role repeat`).
Use distinct directories for every capture, including repeats and their controls.
No automatic capture schedule or game action is performed. Do not edit or
roll back saves to manufacture evidence.

Omit any unknown option; role, phase, action and platform become `unknown`, and
build is stored as null. Action describes the interval being observed; a before
snapshot alone does not prove that the intended action subsequently occurred.
Inputs remain **unverified**, even when supplied confidently. Same-slot identity,
independent ground truth, maxima, fragment meaning and mapping are unknown.
Record resource spending, healing, other pickups and autosave confounders in a
separate private observation log; this tool does not solicit or publish free text.

Without `--confirm-capture`, the command returns `cancelled` before reading any
source or creating any file. The flag records the explicit request to make this
copy; it does not mark evidence as verified. It is not a permission override.

Compare the chosen pair locally using the previously shipped inspector:

```sh
python -m decoders.inspection --appid 4231820 \
  "$HOME/game-assist-private-research/action-before/snapshot.sav" \
  --compare "$HOME/game-assist-private-research/action-after/snapshot.sav"
```

Only the categorical comparison result is a candidate for later redaction and
human review. Never share the package or its metadata file. Follow
[SAVE_INSPECTION.md](SAVE_INSPECTION.md) and the existing BEL-01 protocol for
control/repeat, independent in-game observations and reviewer requirements.
There is no new community-export command or automatic `ParserEvidence`.

## File and failure guarantees

- Linux only; unsupported systems fail closed. The source uses the existing
  bounded double-read checks (32 MiB maximum), symlink refusal and Belmont
  structural/version gate. These checks do not prove Cloud synchronization.
- Destination ancestors are opened by directory descriptors with `O_NOFOLLOW`.
  Checkout markers (`.git/HEAD`, `.git` file/symlink) and bare-repository markers
  are rejected. An empty reserved `.git` directory is not a checkout. There is
  no repository bypass flag. Keep all parent directories stable; this is not
  isolation against a hostile same-user process moving directories concurrently.
- New package/staging directories use `0700`; files use `0600` or stricter umask
  permissions. Files are exclusively created; source is opened read-only.
- Only a fully written package is published, by Linux `renameat2(RENAME_NOREPLACE)`.
  Existing destinations, including empty directories or broken symlinks, are
  never replaced. Unsupported atomic rename fails closed. Files and staging
  directory are fsynced before publication; power-loss durability of the final
  rename is not claimed.
- Ordinary write/validation errors and Ctrl+C **before publication** clean up
  created staging files. Cancellation before capture creates nothing. A complete
  package survives interruption after publication: exit 130 reports unknown and
  tells the caller to check the private destination locally before retrying.
- SIGKILL, machine failure, storage failure during cleanup, and hostile concurrent
  modification cannot guarantee cleanup. `cleanup_incomplete` means inspect the
  private parent locally; do not share its listing or contents. Hidden staging
  directories can contain raw bytes. They retain restricted permissions.
- Exit 0 means `captured` or explicitly `cancelled`; inspect the categorical
  `status`. Exit 2 means failed/unknown; 130 means interrupted/possibly committed.
  stdout and argument-error output contain only fixed categories: no user paths,
  hashes, raw scalar values, build strings, identifiers or exception details.
  Shell history/process arguments remain local OS concerns; do not publish them.

## Reproducible synthetic checks

```sh
python -m unittest discover -s tests -p test_capture.py -v
```

Tests cover unchanged read-only source bytes/mtime, permissions, missing context,
symlinks, Git destinations, no-overwrite races, staging-name collisions, malformed
saves, cancellation, fsync/write/publication failures, post-publication interruption,
and redacted CLI output. All save bytes are synthetic. No real owner save,
installed game build, maximum HP/mana or pickup mapping has been validated here.

## Compare two selected capture folders directly

The read-only folder interface avoids selecting internal files manually:

```sh
python -m decoders.compare_captures \
  "$HOME/game-assist-private-research/action-before" \
  "$HOME/game-assist-private-research/action-after"
```

Use the same command separately for a control pair or repeat pair. It does not
search folders, write reports, alter metadata, combine trials, or attest evidence.
Only the two explicitly selected folders are read. No paths from metadata are
followed; extra metadata keys are rejected.

The interface accepts capture schema `1.0`, AppID `4231820`, format `1.1.3`, and
exactly `snapshot.sav` plus `observation.json`. Missing/extra files, staging names,
symlinks (including ancestors), hardlinked/nonregular files, nonprivate ownership
or permissions, and unstable reads are rejected. Metadata is bounded to 8 KiB;
save bytes to the inspector's 32 MiB. It rechecks both packages across the pair,
including inode/metadata and bytes. Keep parent directories stable; repeated
reads cannot prove immutability after the command returns or defeat a hostile
same-user process. Linux is the supported reader platform.

The first package must declare `before`, the second `after`. Role, action, exact
build and platform must be known and match. Roles are action, control or repeat;
control must declare no action, while action/repeat must name an action.
Incomplete/incompatible declarations block comparison with categorical reasons.
The actual save format is checked independently by the existing inspector.

Successful structural comparison returns `comparison_status: known` and the
existing categorical observations, **while overall `status` remains `unknown`**.
Exit 0 means only that the structural comparison ran; it is never an evidence
approval. `review_blockers` always retain unconfirmed slot identity, ground truth,
owner attestation and the unevaluated full action/control/repeat series. A changing
control, ambiguous observations or positional arrays add blockers. Exit 2 means
comparison unavailable/unsupported; exit 130 means interrupted (no writes).

Matching user declarations do not prove the build, capture provenance or that
files came from one playthrough. A structurally complete package can be fabricated;
there is no signature or trusted capture attestation. The reader rejects attempts
to mark capture metadata verified, and never emits build strings, scalar values,
paths, hashes, entity IDs, `ParserEvidence`, or a completed protocol submission.
Use the observations only as a redacted draft for the existing human review
process. Real controlled pairs and independent in-game observations remain needed.

```sh
python -m unittest discover -s tests -p test_compare_captures.py -v
```

## First real HP or mana observation: owner checklist

Run HP and mana as **separate experiments**. Choose an opportunity already found
through normal play; this protocol supplies no item names, locations or route.
No real pair has been tested here and no additional decoded field is claimed.

1. **Establish context privately.** Record the exact installed build, platform,
   DLC/mod context and whether the same selected slot/playthrough is used. Keep
   consent and a local sequence log with the copies. Format `1.1.3` is not the
   game build. If any required context is unknown, capture may still preserve
   the copy, but comparison/review remains blocked. Do not alter metadata to
   claim slot, owner, ground-truth or reviewer confirmation.
2. **Capture a no-action control.** Take a deliberately selected stable copy,
   then a second copy with no pickup, spending, damage/healing, travel or other
   deliberate game action between them. Use role `control`, action `no_action`,
   phases `before`/`after` and distinct destinations. Confirm locally how saving
   finished; file stability alone does not prove a completed in-game save or
   Cloud sync. If obtaining a copy forces extra game events, record that
   confounder; do not call the control clean.
3. **Observe one pickup interval.** Capture `action/before`, personally perform
   exactly one already-discovered HP **or** mana pickup, wait for a confirmed
   save, then capture `action/after`. Use the same declared build/platform and
   `hp_pickup` or `mana_pickup` on both packages. Privately note what the game
   independently displayed before/after: current resource, explicitly displayed
   maximum, and fragment counter if visible. A full-looking bar is not a measured
   maximum; absent displays are unknown. Note any damage, healing, spending,
   second pickup, autosave/sync uncertainty or unrelated event.
4. **Compare and stop on ambiguity.** Run `decoders.compare_captures` separately
   on each pair. Check for known structural comparison, an unchanged control,
   and absence of unresolved confounders. `control_changed`, unclassified or
   positional changes, incompatible context, missing observations, and uncertain
   save completion block interpretation. Preserve the copies privately; do not
   discard changing fields or rename an aggregate delta into an item flag.
5. **Corroborate without modifying saves.** When naturally available, capture a
   comparable independent `repeat/before` and `repeat/after` for the same action
   category, with its own no-action control and in-game observations. This is
   four pairs (eight packages) for a complete initial experiment. Keep each pair
   in one selected slot/playthrough and record cross-trial differences locally.
   Another pickup may test a scalar hypothesis but cannot verify the first
   pickup's identity. If repetition is unavailable, retain a hypothesis; do not
   edit, restore or roll back saves to force a result.
6. **Review only a redacted draft.** Transfer only categorical observations into
   the existing BEL-01 evidence template, with capture/consent/ground-truth fields
   completed honestly by the owner and review performed independently. Public
   notes omit copies, screenshots with private data, paths, raw values, hashes,
   slot/entity IDs and undiscovered content. The command never completes these
   attestations. Even matching action/repeat changes and an unchanged control
   establish no per-item mapping without separate correspondence and semantic
   review. Until then, maxima, completed upgrade counts and collected items stay
   unknown; no automatic hint or completion claim is justified.
