# Local contribution example — entirely synthetic

This is the bounded fallback for the Elden Ring / The Witcher 3 knowledge task:
**one fictional HP record, zero real gameplay facts**. No rights-cleared primary
gameplay source was established from the supplied material. This is not a claim
that no such source exists. No wiki text, game asset, private save or achievement
definition was copied, and no broad forum research was performed.

The example uses the existing `Catalog` and `ParserEvidence` contracts, without
changing their schemas or the runtime. AppID `999999999` is a test sentinel, not
a verified Steam identity. Never change it to 1245620 or 292030 and present the
same fictional locations or flags as game evidence. Real coverage is unchanged.

## Files and rights

- `catalog.draft.json`: one synthetic record with unverified location/mappings
  and a draft neutral hint. Not included in `knowledge/catalog.json`.
- `evidence.synthetic.json`: hand-written boolean fixture, not parser output.
  `verified: false` is intentional; production trust must not come from a file
  uploaded by a client.
- `LICENSE.txt`: MIT permission for **this original synthetic example only**,
  with the Game Assist contributor notice. This explicitly covers the invented
  data and these instructions; it does not choose a license for the community
  database or confer rights to any third-party source or game material.

## Synthetic observation

The example author invented a blue room, token, pickup and eligibility flag to
exercise the schema. These facts have no game counterpart. `fictional-observation`
refers to this paragraph. The `example.invalid` source URL is deliberately
non-resolving; validation must not fetch it. Local fictional provenance is
sufficient only for testing, never for factual approval.

The invented build and parser versions match exactly within this fixture. No
platform, DLC or localization compatibility is asserted. `false` in the pickup
fixture is a boolean test input, not evidence that a player lacks an item.

## Run and expected outcome

From repository root:

```sh
python -m knowledge docs/contribution-example/catalog.draft.json
python -m unittest discover -s tests -p test_contribution_example.py -v
```

The first command validates shape only. The tests use the existing projection:
the committed draft yields `unknown` collection state and no hint. A copy
reviewed **only inside a synthetic test** yields exactly the neutral text when
all gates pass. Missing evidence/flags, wrong build/parser, already-collected
items, draft hints or unreviewed location/mappings suppress the hint. Tests also
check required license/provenance and rejection of authorized rights without a
permission reference. They check metadata integrity, not legal validity.

## Admission criteria for a separate real contribution

1. Establish actual game identity, exact tested build, platform, DLC scope and
   language. Unknown compatibility stays unknown; do not turn a date, latest
   patch or save-format string into build evidence. No wildcard build claims.
2. Provide attributable primary observations or a source with an explicit
   reuse license/permission covering the proposed content. Preserve the source
   revision and notices. Public access alone is not permission to republish.
   Review source rights and the database's chosen license separately.
3. Create fresh records using original descriptions and real provenance.
   A reviewer checks locations/requirements. Never promote this synthetic file
   by flipping `synthetic` or replacing its AppID/source URL.
4. A separate parser review must establish individual collection and eligibility
   mappings for the current build/slot. Aggregate HP, achievements, file hashes
   and missing flags do not prove individual pickups. Keep state unknown until
   this evidence exists. Do not include real save bytes in the contribution.
5. Independently review spoiler-safe text and eligibility. For schema 1.0 only
   the neutral reminder is allowed. Do not pass the full catalog or future
   locations, requirements, names, counts or URLs to the player/model. Greater
   help depth does not permit future spoilers; known/discovered context still
   needs evidence. Real identity/freshness/consent checks remain adapter duties,
   not functionality supplied by this example.
6. Run schema and projection tests, obtain maintainer approval, and separately
   authorize publication before changing the active registry. Passing a test or
   writing `verified` is not that approval.

See [CONTRIBUTING](../../CONTRIBUTING.md) and
[COMMUNITY_DATA](../COMMUNITY_DATA.md). There is no new import path, service,
decoder, source downloader or automatic promotion mechanism in this example.
