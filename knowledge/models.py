"""Versioned community data; not a save decoder or a spoiler-safe API by itself."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StrictBool, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)


class Source(StrictModel):
    id: str = Field(min_length=1)
    url: HttpUrl
    attribution: str = Field(min_length=1)


class Rights(StrictModel):
    contributor: str = Field(min_length=1)
    basis: Literal['original', 'authorized']
    license: str = Field(min_length=1)
    permission_reference: str | None = None

    @model_validator(mode='after')
    def authorized_reference(self):
        if self.basis == 'authorized' and not self.permission_reference:
            raise ValueError('authorized contributions need a permission reference')
        return self


class Review(StrictModel):
    status: Literal['unverified', 'verified'] = 'unverified'
    reviewer: str | None = None
    evidence_source_ids: list[str] = Field(default_factory=list)
    notes: str = ''

    @model_validator(mode='after')
    def verified_evidence(self):
        if self.status == 'verified' and (not self.reviewer or not self.evidence_source_ids):
            raise ValueError('verified review needs a reviewer and evidence sources')
        return self


class FullLocation(StrictModel):
    """Spoiler-bearing public reference data: never serialize into a safe hint."""
    area: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    requirements: list[str] = Field(default_factory=list)
    requirement_record_ids: list[str] = Field(default_factory=list)
    review: Review = Field(default_factory=Review)


class FlagMapping(StrictModel):
    appid: int = Field(gt=0)
    game_version: str = Field(min_length=1)
    parser_id: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    flag_key: str = Field(min_length=1)
    meaning: Literal['per_item_collection', 'hint_eligibility']
    true_value: StrictBool
    review: Review = Field(default_factory=Review)


class SafeHint(StrictModel):
    # v1 deliberately allows only the user-approved neutral reminder.
    text: Literal['не забудь осмотреться']
    status: Literal['draft', 'reviewed'] = 'draft'
    original: Literal[True]
    reviewer: str | None = None
    trigger: FlagMapping

    @model_validator(mode='after')
    def review_and_trigger(self):
        if self.status == 'reviewed' and not self.reviewer:
            raise ValueError('reviewed hint needs a reviewer')
        if self.trigger.meaning != 'hint_eligibility':
            raise ValueError('hint needs an eligibility mapping')
        return self


class Record(StrictModel):
    schema_version: Literal['1.0']
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9._-]+$')
    appid: int = Field(gt=0)
    game_version: str = Field(min_length=1)
    object_type: Literal['hp_upgrade', 'mana_upgrade']
    synthetic: StrictBool = False
    full_location: FullLocation
    safe_hint: SafeHint | None = None
    collection_mapping: FlagMapping | None = None
    sources: list[Source] = Field(min_length=1)
    rights: Rights

    @model_validator(mode='after')
    def references(self):
        ids = [s.id for s in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate source IDs')
        reviews = [self.full_location.review]
        mappings = [self.collection_mapping, self.safe_hint.trigger if self.safe_hint else None]
        for mapping in filter(None, mappings):
            if (mapping.appid, mapping.game_version) != (self.appid, self.game_version):
                raise ValueError('mapping game/build must match record')
            reviews.append(mapping.review)
        if self.collection_mapping and self.collection_mapping.meaning != 'per_item_collection':
            raise ValueError('collection mapping must refer to an individual item flag')
        for review in reviews:
            if not set(review.evidence_source_ids).issubset(ids):
                raise ValueError('review references missing source')
        return self


class Catalog(StrictModel):
    schema_version: Literal['1.0']
    records: list[Record]

    @model_validator(mode='after')
    def record_references(self):
        by_id = {r.id: r for r in self.records}
        if len(by_id) != len(self.records):
            raise ValueError('duplicate stable record IDs')
        for record in self.records:
            for ref in record.full_location.requirement_record_ids:
                target = by_id.get(ref)
                if target is None or ref == record.id:
                    raise ValueError('missing or self-referential requirement record')
                if (target.appid, target.game_version) != (record.appid, record.game_version):
                    raise ValueError('requirement references a different game/build')
        return self


class ParserEvidence(StrictModel):
    """Trusted local parser output, never an arbitrary client claim of verification."""
    appid: int = Field(gt=0)
    game_version: str = Field(min_length=1)
    parser_id: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    verified: StrictBool
    flags: dict[str, StrictBool]
