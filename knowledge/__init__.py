"""Offline community catalog validation and conservative hint projection."""
from .models import Catalog, ParserEvidence, Record


def _flag(mapping, evidence):
    if mapping is None or evidence is None:
        return None
    if mapping.review.status != 'verified' or not evidence.verified:
        return None
    if (mapping.appid, mapping.game_version, mapping.parser_id, mapping.parser_version) != (
        evidence.appid, evidence.game_version, evidence.parser_id, evidence.parser_version
    ):
        return None
    # Missing flags never mean false. No aggregate HP/mana inference exists here.
    if mapping.flag_key not in evidence.flags:
        return None
    return evidence.flags[mapping.flag_key] == mapping.true_value


def collection_status(record: Record, evidence: ParserEvidence | None) -> str:
    result = _flag(record.collection_mapping, evidence)
    return 'unknown' if result is None else ('collected' if result else 'not_collected')


def safe_hint_view(record: Record, evidence: ParserEvidence | None) -> dict | None:
    """Only a reviewed neutral string; no identifiers, types, future details or location."""
    hint = record.safe_hint
    if not hint or hint.status != 'reviewed' or record.full_location.review.status != 'verified':
        return None
    if collection_status(record, evidence) != 'not_collected':
        return None
    if _flag(hint.trigger, evidence) is not True:
        return None
    return {'text': hint.text}


__all__ = ['Catalog', 'ParserEvidence', 'Record', 'collection_status', 'safe_hint_view']
