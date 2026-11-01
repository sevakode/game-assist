"""Explicit offline client events using the same bounded report vocabulary."""
import json
from .report import ReportError, build_report, validate_report


def build_client_event(**facts):
    report = build_report(**facts)
    if report['component'] not in ('web', 'deck'):
        raise ReportError('invalid_client_component')
    return {'event': 'client_step', 'diagnostic': report}


def serialize_client_event(event):
    if (type(event) is not dict or set(event) != {'event', 'diagnostic'}
            or type(event['event']) is not str or event['event'] != 'client_step'):
        raise ReportError('invalid_client_event')
    report = validate_report(event['diagnostic'])
    if report['component'] not in ('web', 'deck'):
        raise ReportError('invalid_client_component')
    return json.dumps({'event': 'client_step', 'diagnostic': report}, sort_keys=True, separators=(',', ':'))
