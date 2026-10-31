"""Declarative registry contract tests. No real save fixtures or parser execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from knowledge.profiles import ProfileRegistry, approved_profile, coverage_for, load_registry


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((Path(__file__).resolve().parents[1] / 'knowledge/game_profiles.json').read_text())

    def invalid(self, data):
        with self.assertRaises(ValidationError):
            ProfileRegistry.model_validate(data)

    def test_priority_games_and_no_auto_enable(self):
        registry = load_registry()
        self.assertEqual({p.appid for p in registry.profiles}, {4231820, 1245620, 292030})
        self.assertTrue(all(p.parser_auto_enable is False for p in registry.profiles))

    def test_only_four_belmont_scalars_not_game_build(self):
        profile = approved_profile(4231820)
        claim = coverage_for(profile, 'resource_scalars', save_format_version='1.1.3')
        self.assertEqual(len(claim.scalar_fields), 4)
        self.assertIsNone(claim.game_version)
        self.assertIsNone(coverage_for(profile, 'hp_pickups', save_format_version='1.1.3'))
        self.assertIsNone(coverage_for(profile, 'mana_pickups', save_format_version='1.1.3'))

    def test_unsupported_build_and_format_remain_unknown(self):
        profile = approved_profile(4231820)
        for kwargs in [{}, {'save_format_version':'1.1.4'}, {'save_format_version':'1.1.3', 'game_version':'unverified-build'}]:
            self.assertIsNone(coverage_for(profile, 'resource_scalars', **kwargs))

    def test_other_game_and_unknown_appid(self):
        for appid in (1245620,292030):
            self.assertIsNone(coverage_for(approved_profile(appid), 'resource_scalars'))
        self.assertIsNone(approved_profile(1))

    def test_new_game_identity_allowed_without_parser(self):
        data = copy.deepcopy(self.data['profiles'][1])
        data['appid'] = 12345
        registry = ProfileRegistry.model_validate({'schema_version':'1.0','profiles':[data]})
        self.assertEqual(approved_profile(12345,registry).appid,12345)
        self.assertIsNone(coverage_for(registry.profiles[0],'quests'))

    def test_draft_profile_not_approved_or_covered(self):
        self.data['profiles'][0]['registry_status'] = 'draft'
        registry = ProfileRegistry.model_validate(self.data)
        self.assertIsNone(approved_profile(4231820, registry))
        self.assertIsNone(coverage_for(registry.profiles[0], 'resource_scalars',save_format_version='1.1.3'))

    def test_unsupported_schema_version(self):
        self.data['schema_version'] = '2.0'
        self.invalid(self.data)

    def test_unknown_fields_and_execution_configuration_rejected(self):
        for key, value in [('executable_path','/tmp/plugin'),('download_url','https://example.invalid/code'),
                           ('permissions',['saves.read']),('command','python plugin.py'),('coverage_percent',100)]:
            data = copy.deepcopy(self.data)
            data['profiles'][0][key] = value
            self.invalid(data)

    def test_auto_enable_rejected(self):
        self.data['profiles'][0]['parser_auto_enable'] = True
        self.invalid(self.data)

    def test_capability_name_and_missing_evidence_rejected(self):
        for key,value in [('capability','execute_plugin'),('evidence_ids',[]),('evidence_ids',['missing']),
                           ('parser_revision',None),('reviewer',None),('save_format_version','*')]:
            data=copy.deepcopy(self.data)
            data['profiles'][0]['coverage'][0][key]=value
            self.invalid(data)

    def test_source_only_not_verification(self):
        self.data['profiles'][0]['coverage'][0]['evidence_ids']=['local-reader-review']
        self.invalid(self.data)

    def test_gameplay_claim_needs_exact_game_build(self):
        claim=self.data['profiles'][0]['coverage'][0]
        claim['capability']='hp_pickups'
        claim['scalar_fields']=[]
        self.invalid(self.data)

    def test_unknown_cannot_smuggle_parser_claim(self):
        self.data['profiles'][0]['coverage'][0]['status']='unknown'
        self.invalid(self.data)

    def test_duplicate_appid_and_evidence_rejected(self):
        data=copy.deepcopy(self.data)
        data['profiles'].append(data['profiles'][0])
        self.invalid(data)
        self.data['profiles'][0]['evidence'].append(self.data['profiles'][0]['evidence'][0])
        self.invalid(self.data)

    def test_duplicate_json_keys_and_size_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad.json'
            for raw in ['{"schema_version":"1.0","schema_version":"2.0","profiles":[]}', ' '*(1024*1024+1)]:
                path.write_text(raw)
                with self.assertRaises(ValueError):
                    load_registry(path)

    def test_validator_does_not_fetch_sources_or_import_parser(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('no network')), patch('subprocess.run', side_effect=AssertionError('no subprocess')):
            self.assertEqual(len(load_registry().profiles),3)


if __name__=='__main__':
    unittest.main()
