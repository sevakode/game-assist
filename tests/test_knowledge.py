"""Entirely fictional test records; not Belmont data or real save mappings."""
import copy
import json
from pathlib import Path
import unittest
from pydantic import ValidationError
from knowledge import Catalog, ParserEvidence, Record, collection_status, safe_hint_view


def fixture():
    review = {'status': 'verified', 'reviewer': 'synthetic-reviewer', 'evidence_source_ids': ['test-source']}
    mapping = {'appid': 999999999, 'game_version': 'synthetic-build', 'parser_id': 'synthetic-only',
               'parser_version': 'test-1', 'flag_key': 'synthetic-item-a', 'meaning': 'per_item_collection',
               'true_value': True, 'review': review}
    return {'schema_version': '1.0', 'id': 'synthetic.item-a', 'appid': 999999999,
            'game_version': 'synthetic-build', 'object_type': 'hp_upgrade', 'synthetic': True,
            'full_location': {'area': 'FICTIONAL TEST ROOM', 'instructions': 'Synthetic test only',
                              'requirements': ['FICTIONAL REQUIREMENT'], 'review': review},
            'safe_hint': {'text': 'не забудь осмотреться', 'status': 'reviewed', 'original': True,
                          'reviewer': 'synthetic-reviewer',
                          'trigger': dict(mapping, flag_key='synthetic-eligible', meaning='hint_eligibility')},
            'collection_mapping': mapping,
            'sources': [{'id': 'test-source', 'url': 'https://example.invalid/synthetic',
                         'attribution': 'Synthetic test fixture; no real source'}],
            'rights': {'contributor': 'test author', 'basis': 'original', 'license': 'TEST-ONLY'}}


def evidence(**changes):
    value = {'appid': 999999999, 'game_version': 'synthetic-build', 'parser_id': 'synthetic-only',
             'parser_version': 'test-1', 'verified': True,
             'flags': {'synthetic-item-a': False, 'synthetic-eligible': True}}
    value.update(changes)
    return ParserEvidence.model_validate(value)


class KnowledgeTests(unittest.TestCase):
    def record(self, value=None):
        return Record.model_validate(value or fixture())

    def catalog(self, records):
        return Catalog.model_validate({'schema_version': '1.0', 'records': records})

    def test_empty_production_catalog(self):
        data = Path(__file__).resolve().parents[1] / 'knowledge/catalog.json'
        self.assertEqual(Catalog.model_validate_json(data.read_text()).records, [])

    def test_schema_export_is_versioned(self):
        self.assertEqual(Catalog.model_json_schema()['properties']['schema_version']['const'], '1.0')

    def test_explicit_collection_states(self):
        self.assertEqual(collection_status(self.record(), evidence()), 'not_collected')
        self.assertEqual(collection_status(self.record(), evidence(flags={'synthetic-item-a': True})), 'collected')

    def test_missing_evidence_or_flag_unknown(self):
        for ev in [None, evidence(flags={}), evidence(flags={'aggregate_hp': True}), evidence(verified=False)]:
            self.assertEqual(collection_status(self.record(), ev), 'unknown')
            self.assertIsNone(safe_hint_view(self.record(), ev))

    def test_scope_mismatch_unknown(self):
        for field, value in [('appid', 42), ('game_version', 'other'), ('parser_id', 'other'), ('parser_version', 'other')]:
            ev = evidence(**{field: value})
            self.assertEqual(collection_status(self.record(), ev), 'unknown')
            self.assertIsNone(safe_hint_view(self.record(), ev))

    def test_no_mapping_unknown(self):
        item = fixture()
        item['collection_mapping'] = None
        self.assertEqual(collection_status(self.record(item), evidence()), 'unknown')

    def test_unverified_mapping_unknown(self):
        item = copy.deepcopy(fixture())
        item['collection_mapping']['review']['status'] = 'unverified'
        self.assertEqual(collection_status(self.record(item), evidence()), 'unknown')

    def test_inverted_explicit_boolean_mapping(self):
        item = fixture()
        item['collection_mapping']['true_value'] = False
        self.assertEqual(collection_status(self.record(item), evidence()), 'collected')
        self.assertEqual(collection_status(self.record(item), evidence(flags={})), 'unknown')

    def test_safe_projection_contains_only_neutral_text(self):
        self.assertEqual(safe_hint_view(self.record(), evidence()), {'text': 'не забудь осмотреться'})
        result = json.dumps(safe_hint_view(self.record(), evidence()))
        for forbidden in ['synthetic', 'hp_upgrade', 'location', 'requirements', 'id']:
            self.assertNotIn(forbidden, result)

    def test_no_trigger_unknown_false_or_collected(self):
        for flags in [{'synthetic-item-a': False}, {'synthetic-item-a': False, 'synthetic-eligible': False},
                      {'synthetic-item-a': True, 'synthetic-eligible': True}]:
            self.assertIsNone(safe_hint_view(self.record(), evidence(flags=flags)))

    def test_draft_hint_not_served(self):
        item = fixture()
        item['safe_hint']['status'] = 'draft'
        self.assertIsNone(safe_hint_view(self.record(item), evidence()))

    def test_unverified_location_or_trigger_not_served(self):
        for path in ['full_location', 'trigger']:
            item = copy.deepcopy(fixture())
            target = item['full_location'] if path == 'full_location' else item['safe_hint']['trigger']
            target['review']['status'] = 'unverified'
            self.assertIsNone(safe_hint_view(self.record(item), evidence()))

    def test_non_neutral_hint_rejected(self):
        item = fixture()
        item['safe_hint']['text'] = 'There is an HP upgrade behind the future boss'
        with self.assertRaises(ValidationError):
            self.record(item)

    def test_duplicate_record_ids_rejected(self):
        with self.assertRaises(ValidationError):
            self.catalog([fixture(), fixture()])

    def test_invalid_requirement_reference_rejected(self):
        for ref in ['missing', 'synthetic.item-a']:
            item = fixture()
            item['full_location']['requirement_record_ids'] = [ref]
            with self.assertRaises(ValidationError):
                self.catalog([item])

    def test_cross_game_requirement_rejected(self):
        item, target = fixture(), fixture()
        target['id'] = 'synthetic.item-b'
        target['appid'] = 2
        target['collection_mapping'] = None
        target['safe_hint'] = None
        item['full_location']['requirement_record_ids'] = [target['id']]
        with self.assertRaises(ValidationError):
            self.catalog([item, target])

    def test_missing_evidence_source_rejected(self):
        item = copy.deepcopy(fixture())
        item['collection_mapping']['review']['evidence_source_ids'] = ['missing']
        with self.assertRaises(ValidationError):
            self.record(item)

    def test_verified_mapping_requires_evidence(self):
        item = copy.deepcopy(fixture())
        item['collection_mapping']['review']['evidence_source_ids'] = []
        with self.assertRaises(ValidationError):
            self.record(item)

    def test_malformed_fields_rejected(self):
        for field, bad in [('schema_version', '2.0'), ('object_type', 'boss'), ('appid', '1'), ('unknown', True)]:
            item = fixture()
            item[field] = bad
            with self.assertRaises(ValidationError):
                self.record(item)

    def test_non_boolean_flags_rejected(self):
        for bad in [0, 1, 'false', None, 100]:
            with self.assertRaises(ValidationError):
                evidence(flags={'synthetic-item-a': bad})

    def test_authorized_rights_need_reference(self):
        item = fixture()
        item['rights']['basis'] = 'authorized'
        with self.assertRaises(ValidationError):
            self.record(item)

    def test_mapping_wrong_build_rejected(self):
        item = fixture()
        item['collection_mapping']['game_version'] = 'other'
        with self.assertRaises(ValidationError):
            self.record(item)

    def test_duplicate_sources_rejected(self):
        item = fixture()
        item['sources'].append(item['sources'][0])
        with self.assertRaises(ValidationError):
            self.record(item)


if __name__ == '__main__':
    unittest.main()
