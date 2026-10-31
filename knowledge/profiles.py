"""Declarative, bounded profile registry. Never imports parsers or fetches URLs."""
import argparse
import json
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
from .models import StrictModel, Rights, Source

Capability = Literal['resource_scalars', 'hp_pickups', 'mana_pickups', 'inventory', 'quests', 'bosses', 'missables']
CAPABILITIES = ('resource_scalars', 'hp_pickups', 'mana_pickups', 'inventory', 'quests', 'bosses', 'missables')
Scalar = Literal['healthUpgradeFragmentCount', 'manaUpgradeFragmentCount', 'currentHealth', 'currentMana']


class Coverage(StrictModel):
    capability: Capability
    status: Literal['unknown', 'verified']
    # A save-format version is NOT a tested game-build version.
    game_version: str | None = Field(default=None, min_length=1, max_length=80)
    save_format_version: str | None = Field(default=None, min_length=1, max_length=80)
    parser_id: str | None = Field(default=None, pattern=r'^[a-z0-9][a-z0-9._-]{0,79}$')
    parser_revision: str | None = Field(default=None, pattern=r'^sha256:[0-9a-f]{64}$')
    scalar_fields: list[Scalar] = Field(default_factory=list, max_length=4)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    reviewer: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode='after')
    def evidence_gate(self):
        for version in (self.game_version, self.save_format_version):
            if version and any(x in version for x in ('*', '<', '>', '|')):
                raise ValueError('only exact versions, never wildcard/range claims')
        if len(self.scalar_fields) != len(set(self.scalar_fields)):
            raise ValueError('duplicate scalar fields')
        if self.status == 'unknown':
            if self.parser_id or self.parser_revision or self.scalar_fields or self.evidence_ids or self.reviewer:
                raise ValueError('unknown coverage must not imply verified parser support')
        else:
            if not all((self.parser_id, self.parser_revision, self.evidence_ids, self.reviewer)):
                raise ValueError('verified capability needs pinned parser, evidence and review')
            if not self.game_version and not (self.capability == 'resource_scalars' and self.save_format_version):
                raise ValueError('gameplay claims require exact game version')
            if self.capability == 'resource_scalars' and not self.scalar_fields:
                raise ValueError('scalar coverage must name supported scalar fields')
        if self.capability != 'resource_scalars' and self.scalar_fields:
            raise ValueError('scalar names do not establish gameplay facts')
        return self


class Evidence(StrictModel):
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9._-]{0,79}$')
    kind: Literal['source_review', 'synthetic_test', 'private_fixture_report']
    reference: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=1500)
    # Descriptive reference only: no URL fetch, filesystem open or code execution.


class GameProfile(StrictModel):
    appid: int = Field(gt=0, le=2**32-1)
    title: str = Field(min_length=1, max_length=160)
    registry_status: Literal['draft', 'approved'] = 'draft'
    registry_reviewer: str | None = Field(default=None, min_length=1, max_length=120)
    parser_auto_enable: Literal[False] = False
    sources: list[Source] = Field(min_length=1, max_length=20)
    rights: Rights
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)
    coverage: list[Coverage] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def reference_gate(self):
        if self.registry_status == 'approved' and not self.registry_reviewer:
            raise ValueError('approved registry entry requires reviewer')
        ids = [e.id for e in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate evidence IDs')
        source_ids = [s.id for s in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError('duplicate source IDs')
        keys = [(c.capability, c.game_version, c.save_format_version) for c in self.coverage]
        if len(keys) != len(set(keys)):
            raise ValueError('duplicate capability/version claim')
        evidence = {e.id: e for e in self.evidence}
        for c in self.coverage:
            if not set(c.evidence_ids).issubset(evidence):
                raise ValueError('missing capability evidence')
            if c.status == 'verified':
                kinds = {evidence[i].kind for i in c.evidence_ids}
                if not {'source_review', 'synthetic_test'}.issubset(kinds):
                    raise ValueError('verified capability needs source review and tests')
                if 'private_fixture_report' not in kinds:
                    raise ValueError('verified capability needs consented private-fixture report')
        return self


class ProfileRegistry(StrictModel):
    schema_version: Literal['1.0']
    profiles: list[GameProfile] = Field(max_length=1000)

    @model_validator(mode='after')
    def unique_games(self):
        if len({p.appid for p in self.profiles}) != len(self.profiles):
            raise ValueError('duplicate AppID')
        return self


def load_registry(path: Path | None = None) -> ProfileRegistry:
    path = path or Path(__file__).with_name('game_profiles.json')
    with path.open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('profile registry exceeds 1 MiB')
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate JSON key')
            value[key] = item
        return value
    return ProfileRegistry.model_validate(json.loads(raw, object_pairs_hook=pairs))


def approved_profile(appid: int, registry: ProfileRegistry | None = None) -> GameProfile | None:
    """Descriptive metadata only, never permission or a runnable parser registration."""
    registry = registry if registry is not None else load_registry()
    return next((p for p in registry.profiles if p.appid == appid and p.registry_status == 'approved'), None)


def coverage_for(profile: GameProfile, capability: Capability, *, game_version: str | None = None,
                 save_format_version: str | None = None) -> Coverage | None:
    """None means unknown: missing profile/build support does not mean zero progress."""
    if profile.registry_status != 'approved':
        return None
    return next((c for c in profile.coverage if c.capability == capability and c.status == 'verified'
                 and c.game_version == game_version and c.save_format_version == save_format_version), None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    try:
        registry = load_registry(args.path)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Invalid profile registry: {exc}\n')
    print(f'Valid profile registry: {len(registry.profiles)} games; no parsers enabled.')
