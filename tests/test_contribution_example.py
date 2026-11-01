"""Exercise the shipped fictional contribution using the existing contracts."""
import copy
import json
from pathlib import Path
import unittest

from pydantic import ValidationError
from knowledge import Catalog, ParserEvidence, Record, collection_status, safe_hint_view

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'docs/contribution-example'


class ContributionExampleTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((EXAMPLE / 'catalog.draft.json').read_text())
        self.raw = self.catalog['records'][0]
        self.evidence = json.loads((EXAMPLE / 'evidence.synthetic.json').read_text())

    def reviewed_test_copy(self):
        item = copy.deepcopy(self.raw)
        review = {'status': 'verified', 'reviewer': 'FICTIONAL TEST REVIEWER',
                  'evidence_source_ids': ['fictional-observation'], 'notes': 'Synthetic test only'}
        for target in (item['full_location'], item['collection_mapping'], item['safe_hint']['trigger']):
            target['review'] = copy.deepcopy(review)
        item['safe_hint'].update(status='reviewed', reviewer='FICTIONAL TEST REVIEWER')
        ev = dict(self.evidence, verified=True)
        return item, ev

    def test_example_is_fictional_and_not_in_active_catalog(self):
        parsed = Catalog.model_validate(self.catalog)
        self.assertEqual(len(parsed.records), 1)
        record = parsed.records[0]
        self.assertIs(record.synthetic, True)
        self.assertEqual(record.appid, 999999999)
        self.assertEqual(record.game_version, 'synthetic-example-build-1')
        self.assertEqual(record.sources[0].url.host, 'example.invalid')
        active = Catalog.model_validate_json((ROOT / 'knowledge/catalog.json').read_text())
        self.assertNotIn(record.id, {r.id for r in active.records})
        self.assertNotIn(record.appid, {r.appid for r in active.records})

    def test_committed_draft_never_produces_a_hint(self):
        record = Record.model_validate(self.raw)
        self.assertFalse(self.evidence['verified'])
        for ev in (None, ParserEvidence.model_validate(self.evidence),
                   ParserEvidence.model_validate(dict(self.evidence, verified=True))):
            self.assertEqual(collection_status(record, ev), 'unknown')
            self.assertIsNone(safe_hint_view(record, ev))

    def test_license_and_provenance_are_required(self):
        self.assertEqual((EXAMPLE / 'LICENSE.txt').read_bytes(), (ROOT / 'LICENSE').read_bytes())
        self.assertEqual(self.raw['rights']['basis'], 'original')
        self.assertIn('synthetic example only', self.raw['rights']['license'])
        for field in ('license', 'contributor'):
            item = copy.deepcopy(self.raw)
            item['rights'][field] = ''
            with self.assertRaises(ValidationError):
                Record.model_validate(item)
        item = copy.deepcopy(self.raw)
        item['rights'].update(basis='authorized', permission_reference=None)
        with self.assertRaises(ValidationError):
            Record.model_validate(item)
        item = copy.deepcopy(self.raw)
        item['sources'] = []
        with self.assertRaises(ValidationError):
            Record.model_validate(item)

    def test_verified_review_needs_referenced_evidence(self):
        for evidence_ids in ([], ['absent-source']):
            item, _ = self.reviewed_test_copy()
            item['collection_mapping']['review']['evidence_source_ids'] = evidence_ids
            with self.assertRaises(ValidationError):
                Record.model_validate(item)

    def test_build_and_parser_mismatch_fail_closed(self):
        item, ev = self.reviewed_test_copy()
        record = Record.model_validate(item)
        for key, value in (('appid', 292030), ('game_version', 'another-build'),
                           ('parser_id', 'another-parser'), ('parser_version', '2')):
            changed = ParserEvidence.model_validate(dict(ev, **{key: value}))
            self.assertEqual(collection_status(record, changed), 'unknown')
            self.assertIsNone(safe_hint_view(record, changed))
        item['collection_mapping']['game_version'] = 'another-build'
        with self.assertRaises(ValidationError):
            Record.model_validate(item)

    def test_independent_review_gates_suppress_hint(self):
        for target in ('location', 'collection', 'eligibility', 'hint'):
            item, ev = self.reviewed_test_copy()
            if target == 'hint':
                item['safe_hint']['status'] = 'draft'
            else:
                mapping = {'location': item['full_location'], 'collection': item['collection_mapping'],
                           'eligibility': item['safe_hint']['trigger']}[target]
                mapping['review']['status'] = 'unverified'
            self.assertIsNone(safe_hint_view(Record.model_validate(item), ParserEvidence.model_validate(ev)))

    def test_projection_never_returns_fictional_spoilers(self):
        item, ev = self.reviewed_test_copy()
        record = Record.model_validate(item)
        self.assertEqual(safe_hint_view(record, ParserEvidence.model_validate(ev)),
                         {'text': 'не забудь осмотреться'})
        for flags in ({}, {'aggregate_hp': True}, {'fictional.pickup.a': False},
                      {'fictional.pickup.a': False, 'fictional.hint.allowed': False},
                      {'fictional.pickup.a': True, 'fictional.hint.allowed': True}):
            self.assertIsNone(safe_hint_view(record, ParserEvidence.model_validate(dict(ev, flags=flags))))
        item['safe_hint']['text'] = 'FICTIONAL BLUE ROOM'
        with self.assertRaises(ValidationError):
            Record.model_validate(item)


if __name__ == '__main__':
    unittest.main()
