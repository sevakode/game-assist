import json
from pathlib import Path
import unittest
from diagnostics.report import (REPORT_SCHEMA, MAX_REPORT_BYTES, REASONS, ReportError,
                                build_report, parse_report, serialize_report, validate_report)

SECRET = 'SENTINEL:/home/deck/save.dat?SteamID=76561198000000001&token=private'

class ReportTests(unittest.TestCase):
    def report(self):
        return build_report(component='deck', stage='install', reason='install_interrupted',
                            installation='interrupted', python_version='3.11.2', platform='linux')

    def test_roundtrip_and_schema_artifact(self):
        report = self.report()
        self.assertEqual(parse_report(serialize_report(report)), report)
        self.assertEqual(json.loads(Path('diagnostics/report.schema.json').read_text()), REPORT_SCHEMA)
        self.assertLess(len(serialize_report(report)), MAX_REPORT_BYTES)

    def test_reject_values_without_echo_or_logging(self):
        for field in self.report():
            with self.subTest(field=field):
                data = self.report() | {field: SECRET}
                with self.assertNoLogs():
                    with self.assertRaises(ReportError) as caught:
                        validate_report(data)
                self.assertEqual(str(caught.exception), 'invalid_diagnostic_report')
                self.assertNotIn(SECRET, repr(caught.exception))

    def test_unknown_nested_and_missing_fields(self):
        for extra in ('logs', 'stderr', 'owner', 'steamid', 'filename', 'attachments', 'body'):
            with self.assertRaises(ReportError):
                validate_report(self.report() | {extra: SECRET})
        for key in self.report():
            data = self.report(); del data[key]
            with self.assertRaises(ReportError):
                validate_report(data)
        with self.assertRaises(ReportError):
            validate_report(self.report() | {'reason': {'text': SECRET}})

    def test_strict_types_bounds_and_patterns(self):
        for key, values in {
            'schema_version': [True, 1.0, '1', 2],
            'http_status': [True, 200.0, '200', 99, 600],
            'venv_available': [0, 1, 'true'],
            'request_id': ['a'*31, 'a'*33, 'A'*32, 'a'*32+'\n'],
            'app_version': ['1.2', '1.2.3-dev', '1234.1.1', '1.2.3\n'],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ReportError):
                    validate_report(self.report() | {key: value})

    def test_parser_bounds_duplicate_keys_invalid_json(self):
        valid = serialize_report(self.report())
        for payload in (b'\xff', '', '[]', 'null', 'NaN', ' '*2049,
                        '{"schema_version":1,' + valid[1:],
                        '['*1000 + ']'*1000, valid.replace('null', 'NaN', 1),
                        valid + '\U0001f600'*600, {'logs': SECRET}):
            with self.assertNoLogs(), self.assertRaises(ReportError):
                parse_report(payload)

    def test_known_failures_and_no_implicit_collection(self):
        for reason in REASONS:
            self.assertEqual(build_report(component='deck', stage='pairing', reason=reason)['reason'], reason)
        report = self.report()
        self.assertIsNone(report['request_id'])
        self.assertIsNone(report['http_status'])
        self.assertEqual(report['app_version'], 'unknown')
        copied = validate_report(report); copied['reason'] = 'none'
        self.assertEqual(report['reason'], 'install_interrupted')

class ClientEventTests(unittest.TestCase):
    def test_explicit_client_event_has_only_report_vocabulary(self):
        from diagnostics.events import build_client_event, serialize_client_event
        event = build_client_event(component='deck', stage='service', reason='working_directory_unavailable')
        self.assertEqual(json.loads(serialize_client_event(event)), event)
        with self.assertRaises(ReportError):
            serialize_client_event(event | {'stderr': SECRET})
        with self.assertRaises(ReportError):
            build_client_event(component='server', stage='request')
        event['diagnostic']['reason'] = SECRET
        with self.assertNoLogs(), self.assertRaises(ReportError):
            serialize_client_event(event)
