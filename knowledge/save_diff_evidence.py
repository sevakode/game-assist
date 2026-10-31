"""BEL-01 redacted observation protocol, not a save decoder or semantic mapper.

Only accepts human-prepared categorical evidence. Never reads a save, follows
references, executes contributed code, or promotes a field delta into a pickup.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)


class PrivatePair(StrictModel):
    """Optional LOCAL-ONLY hashes. Excluded from public_projection entirely."""
    before_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    after_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class Observation(StrictModel):
    field_category: Literal['current_health', 'current_mana', 'maximum_health', 'maximum_mana',
                            'health_fragment_counter', 'mana_fragment_counter', 'candidate_item_flag',
                            'array_position', 'other_unknown']
    change: Literal['increased', 'decreased', 'unchanged', 'added', 'removed', 'type_changed',
                    'null', 'unknown']
    identity: Literal['not_applicable', 'schema_verified_stable', 'positional_only', 'unknown'] = 'unknown'
    # No raw values, JSON pointers, entity IDs, filenames or arbitrary text fields.


class Trial(StrictModel):
    trial_id: str = Field(pattern=r'^trial-[0-9]{1,4}$')
    role: Literal['baseline', 'action', 'control', 'repeat']
    action: Literal['hp_pickup', 'mana_pickup', 'spend_health', 'spend_mana', 'no_action', 'unknown']
    same_selected_slot: bool
    independent_in_game_observation: bool
    stable_snapshots: bool
    originals_unchanged: bool
    confounders: list[Literal['autosave', 'other_pickup', 'resource_spend', 'random_event',
                              'slot_changed', 'partial_sync', 'unknown']] = Field(default_factory=list, max_length=7)
    observations: list[Observation] = Field(default_factory=list, max_length=32)
    private_pair: PrivatePair | None = Field(default=None, exclude=True)

    @model_validator(mode='after')
    def role_checks(self):
        if self.role == 'control' and self.action != 'no_action':
            raise ValueError('control must describe no deliberate action')
        if len(self.confounders) != len(set(self.confounders)):
            raise ValueError('duplicate confounder categories')
        return self


class ReviewAttestation(StrictModel):
    """Maintainer-recorded review provenance; schema validation cannot authenticate it."""
    reviewer_alias: str = Field(pattern=r'^reviewer-[a-z0-9-]{1,40}$')
    review_reference: str = Field(pattern=r'^review-[a-z0-9-]{1,60}$')
    reviewed_scope: Literal['structural_observations_only']


class EvidenceSubmission(StrictModel):
    schema_version: Literal['1.0']
    protocol: Literal['controlled-save-observation-v1']
    appid: int = Field(gt=0, le=2147483647)
    # Exact version identifiers only, not personal paths, URLs or broad ranges.
    game_version: str | None = Field(default=None, pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
    save_format_version: str | None = Field(default=None, pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
    platform: Literal['windows', 'linux', 'steamos_proton', 'unknown']
    parser_revision: str | None = Field(default=None, pattern=r'^sha256:[a-f0-9]{64}$')
    target: Literal['hp_pickup', 'mana_pickup', 'resource_spend', 'unknown']
    status: Literal['hypothesis', 'verified'] = 'hypothesis'
    verification_scope: Literal['structural_observations_only'] = 'structural_observations_only'
    independent_review_completed: bool = False
    review_attestation: ReviewAttestation | None = None
    consented_local_comparison: bool = False
    redaction_review_completed: bool = False
    trials: list[Trial] = Field(default_factory=list, max_length=16)

    @model_validator(mode='after')
    def consistency(self):
        if len({t.trial_id for t in self.trials}) != len(self.trials):
            raise ValueError('duplicate trial IDs')
        if self.status == 'verified':
            if not self.independent_review_completed or self.review_attestation is None:
                raise ValueError('verified observations require independent review')
            if review_blockers(self):
                raise ValueError('verified observations have unmet controlled-protocol gates')
        return self


def review_blockers(submission: EvidenceSubmission) -> list[str]:
    """Readiness gates, not an automatic factual verdict or a mapping generator."""
    reasons = []
    if not submission.game_version:
        reasons.append('exact_game_build_unknown')
    if submission.platform == 'unknown':
        reasons.append('platform_unknown')
    # Current research protocol supports only observed Belmont JSON format.
    if (submission.appid, submission.save_format_version) != (4231820, '1.1.3'):
        reasons.append('unsupported_or_unknown_format')
    if not submission.parser_revision:
        reasons.append('parser_revision_unknown')
    if not submission.consented_local_comparison:
        reasons.append('local_comparison_consent_missing')
    if not submission.redaction_review_completed:
        reasons.append('redaction_review_missing')
    if submission.target == 'unknown':
        reasons.append('action_unknown')
    roles = {t.role for t in submission.trials}
    if not {'action', 'control', 'repeat'}.issubset(roles):
        reasons.append('action_control_repeat_required')
    action_trials = [t for t in submission.trials if t.role in ('action', 'repeat')]
    expected = {'hp_pickup': {'hp_pickup'}, 'mana_pickup': {'mana_pickup'},
                'resource_spend': {'spend_health', 'spend_mana'}, 'unknown': set()}[submission.target]
    if any(t.action not in expected for t in action_trials):
        reasons.append('action_target_mismatch')
    if len({t.action for t in action_trials}) > 1:
        reasons.append('repeat_action_mismatch')
    for t in submission.trials:
        if not all((t.same_selected_slot, t.stable_snapshots, t.originals_unchanged,
                    t.independent_in_game_observation)):
            reasons.append('trial_capture_or_ground_truth_unconfirmed')
        if t.confounders:
            reasons.append('unresolved_confounders')
        if not t.observations:
            reasons.append('observations_missing')
        if any(o.change in ('unknown', 'type_changed', 'null') for o in t.observations):
            reasons.append('ambiguous_observations')
        if any(o.identity == 'positional_only' or o.field_category == 'array_position' for o in t.observations):
            reasons.append('positional_array_changes_not_identity')
        if t.role == 'control' and any(o.change != 'unchanged' for o in t.observations):
            reasons.append('control_changed')
    # An unchanged repeat, or unrelated observed category, cannot corroborate action.
    primary = [t for t in action_trials if t.role == 'action']
    repeats = [t for t in action_trials if t.role == 'repeat']
    def signatures(trial):
        return {(o.field_category, o.change) for o in trial.observations
                if o.change in ('increased', 'decreased', 'added', 'removed')}
    if primary and repeats and not all(signatures(t) and signatures(t) == signatures(primary[0]) for t in action_trials):
        reasons.append('repeat_does_not_reproduce_observation')
    if primary:
        categories = {o.field_category for o in primary[0].observations}
        if any({o.field_category for o in t.observations} != categories
               for t in submission.trials if t.role == 'control'):
            reasons.append('control_observed_different_fields')
    return sorted(set(reasons))


def public_projection(submission: EvidenceSubmission) -> dict:
    """Redacted categorical report. No raw values, private hashes, mapping or hints."""
    data = submission.model_dump(mode='json')
    # Explicit defense even if model serialization changes in a later version.
    for trial in data['trials']:
        trial.pop('private_pair', None)
    return {'submission': data, 'review_blockers': review_blockers(submission),
            'semantic_mapping_status': 'unknown', 'collected_item_status': 'unknown',
            'limitations': ['current_resource_is_not_maximum',
                            'fragment_counter_is_not_collected_item_identity',
                            'positional_array_change_is_not_entity_change',
                            'verified_structure_is_not_verified_game_semantics']}
