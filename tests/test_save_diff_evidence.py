"""Synthetic BEL-01 protocol evidence only; no private save reads."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from pydantic import ValidationError
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'knowledge'))
from save_diff_evidence import EvidenceSubmission, public_projection, review_blockers


def fixture(category='health_fragment_counter', action='hp_pickup', target='hp_pickup'):
    trials=[]
    for index, role in enumerate(('action','control','repeat'),1):
        trials.append({'trial_id':f'trial-{index}','role':role,'action':'no_action' if role=='control' else action,
                       'same_selected_slot':True,'independent_in_game_observation':True,'stable_snapshots':True,
                       'originals_unchanged':True,'observations':[{'field_category':category,
                       'change':'unchanged' if role=='control' else 'increased','identity':'not_applicable'}],
                       'private_pair':{'before_sha256':'a'*64,'after_sha256':'b'*64}})
    return {'schema_version':'1.0','protocol':'controlled-save-observation-v1','appid':4231820,
            'game_version':'synthetic-build','save_format_version':'1.1.3','platform':'linux',
            'parser_revision':'sha256:'+'c'*64,'target':target,'status':'hypothesis',
            'consented_local_comparison':True,'redaction_review_completed':True,'trials':trials}


class EvidenceTests(unittest.TestCase):
    def parse(self, data):
        return EvidenceSubmission.model_validate(data)

    def test_eligible_does_not_automatically_verify(self):
        report=self.parse(fixture())
        self.assertEqual(review_blockers(report),[])
        self.assertEqual(report.status,'hypothesis')
        self.assertEqual(public_projection(report)['semantic_mapping_status'],'unknown')

    def test_fragments_never_mean_collected_item(self):
        for category in ('health_fragment_counter','mana_fragment_counter'):
            result=public_projection(self.parse(fixture(category)))
            self.assertEqual(result['collected_item_status'],'unknown')
            self.assertIn('fragment_counter_is_not_collected_item_identity',result['limitations'])

    def test_current_resources_never_mean_maximum(self):
        for category,action in [('current_health','spend_health'),('current_mana','spend_mana')]:
            data=fixture(category,action,'resource_spend')
            for t in data['trials']:
                if t['role']!='control':t['observations'][0]['change']='decreased'
            result=public_projection(self.parse(data))
            self.assertEqual(result['semantic_mapping_status'],'unknown')
            self.assertIn('current_resource_is_not_maximum',result['limitations'])
            self.assertNotIn('maximum_health',json.dumps(result))

    def test_named_maximum_field_not_semantic_proof(self):
        result=public_projection(self.parse(fixture('maximum_health')))
        self.assertEqual(result['semantic_mapping_status'],'unknown')

    def test_candidate_flag_not_mapping(self):
        result=public_projection(self.parse(fixture('candidate_item_flag')))
        self.assertEqual(result['collected_item_status'],'unknown')
        self.assertNotIn('collection_mapping',json.dumps(result))

    def test_positional_array_noise_blocks_review(self):
        data=fixture('array_position')
        for t in data['trials']:t['observations'][0]['identity']='positional_only'
        self.assertIn('positional_array_changes_not_identity',review_blockers(self.parse(data)))

    def test_unknown_or_unsupported_versions(self):
        for field,value,reason in [('game_version',None,'exact_game_build_unknown'),
                                  ('save_format_version',None,'unsupported_or_unknown_format'),
                                  ('save_format_version','1.1.4','unsupported_or_unknown_format'),
                                  ('appid',1245620,'unsupported_or_unknown_format')]:
            data=fixture();data[field]=value
            self.assertIn(reason,review_blockers(self.parse(data)))

    def test_baseline_alone_never_confirms(self):
        data=fixture();data['trials']=data['trials'][:1];data['trials'][0]['role']='baseline'
        self.assertIn('action_control_repeat_required',review_blockers(self.parse(data)))
        self.assertEqual(public_projection(self.parse(data))['collected_item_status'],'unknown')

    def test_changed_control_and_failed_repeat(self):
        data=fixture();data['trials'][1]['observations'][0]['change']='increased'
        self.assertIn('control_changed',review_blockers(self.parse(data)))
        data=fixture();data['trials'][2]['observations'][0]['change']='unchanged'
        self.assertIn('repeat_does_not_reproduce_observation',review_blockers(self.parse(data)))

    def test_control_must_observe_same_categories(self):
        data=fixture();data['trials'][1]['observations'][0]['field_category']='other_unknown'
        self.assertIn('control_observed_different_fields',review_blockers(self.parse(data)))

    def test_slot_ground_truth_stability_and_confounds(self):
        for flag in ('same_selected_slot','independent_in_game_observation','stable_snapshots','originals_unchanged'):
            data=fixture();data['trials'][0][flag]=False
            self.assertIn('trial_capture_or_ground_truth_unconfirmed',review_blockers(self.parse(data)))
        data=fixture();data['trials'][0]['confounders']=['autosave']
        self.assertIn('unresolved_confounders',review_blockers(self.parse(data)))

    def test_status_requires_review_provenance_not_just_flag(self):
        data=fixture();data['status']='verified';data['independent_review_completed']=True
        with self.assertRaises(ValidationError):self.parse(data)

    def test_verified_is_structural_only_and_keeps_unknown_mapping(self):
        data=fixture();data.update(status='verified',independent_review_completed=True,
            review_attestation={'reviewer_alias':'reviewer-synthetic','review_reference':'review-synthetic',
                                'reviewed_scope':'structural_observations_only'})
        result=public_projection(self.parse(data))
        self.assertEqual(result['submission']['status'],'verified')
        self.assertEqual(result['semantic_mapping_status'],'unknown')
        data['game_version']=None
        with self.assertRaises(ValidationError):self.parse(data)

    def test_public_projection_excludes_private_hashes(self):
        report=self.parse(fixture());result=json.dumps(public_projection(report))
        for forbidden in ('private_pair','before_sha256','after_sha256','a'*64,'b'*64):
            self.assertNotIn(forbidden,result)
        self.assertIsNotNone(report.trials[0].private_pair)

    def test_unknown_fields_and_private_payload_rejected(self):
        for key,value in [('raw_save','secret'),('path','/private/save'),('entity_id','secret'),
                          ('values',{'before':1,'after':2}),('collected',True)]:
            data=fixture();data['trials'][0][key]=value
            with self.assertRaises(ValidationError):self.parse(data)

    def test_type_change_null_and_missing_are_not_false(self):
        for change in ('null','unknown','type_changed'):
            data=fixture();data['trials'][0]['observations'][0]['change']=change
            result=public_projection(self.parse(data))
            self.assertIn('ambiguous_observations',result['review_blockers'])
            self.assertEqual(result['collected_item_status'],'unknown')

    def test_control_wrong_action_duplicate_id_bad_schema(self):
        for mutate in [lambda d:d.update(schema_version='2.0'),
                       lambda d:d['trials'][1].update(action='hp_pickup'),
                       lambda d:d['trials'][1].update(trial_id='trial-1')]:
            data=fixture();mutate(data)
            with self.assertRaises(ValidationError):self.parse(data)

    def test_protocol_does_not_open_files_network_or_commands(self):
        with patch('builtins.open',side_effect=AssertionError('no files')), \
             patch('urllib.request.urlopen',side_effect=AssertionError('no network')), \
             patch('subprocess.run',side_effect=AssertionError('no commands')):
            self.assertEqual(public_projection(self.parse(fixture()))['collected_item_status'],'unknown')

    def test_empty_template_is_hypothesis_and_blocked(self):
        path=Path(__file__).resolve().parents[1]/'knowledge/evidence_template.json'
        report=EvidenceSubmission.model_validate_json(path.read_text())
        self.assertEqual(report.trials,[])
        self.assertEqual(report.status,'hypothesis')
        self.assertIn('action_control_repeat_required',review_blockers(report))


if __name__=='__main__':unittest.main()
