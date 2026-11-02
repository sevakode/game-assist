"""Privacy-minimal ASGI events. Never copy body, URL or exception text.

This is an allowlisted event channel, not a general-purpose log sanitizer.
Explicit startup configuration is required; importing this module changes nothing.
"""
from contextvars import ContextVar
import asyncio
import json
import logging
import re
import secrets
import sys
import time

from diagnostics.report import ID_PATTERN, REASONS

LOGGER_NAME = 'game_assist.safe_events'
CATEGORIES = frozenset(('unknown', 'health', 'browser', 'oauth', 'pairing', 'device', 'mcp', 'diagnostics', 'pair_start', 'pair_poll', 'pair_approval'))
METHODS = frozenset(('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'))

ROUTE_CATEGORIES = {
    '/healthz': 'health', '/mcp': 'mcp',
    '/v1/devices/pair/start': 'pair_start', '/v1/devices/pair/poll': 'pair_poll',
    '/devices/review': 'pair_approval', '/devices/approve': 'pair_approval', '/v1/device/observations': 'device',
    '/authorize': 'oauth', '/token': 'oauth', '/register': 'oauth', '/revoke': 'oauth',
    '/oauth/consent': 'oauth', '/login': 'oauth', '/steam/callback': 'oauth',
    '/.well-known/oauth-authorization-server': 'oauth',
    '/.well-known/oauth-protected-resource/mcp': 'oauth',
    '/diagnostics': 'diagnostics', '/assets/diagnostics.js': 'diagnostics',
}
for _route in ('/', '/games', '/start', '/setup', '/data-handling', '/import',
               '/v1/browser/observations', '/connect/claude', '/logout',
               '/account/library/permission', '/account/library/refresh',
               '/account/achievements/refresh', '/account/games/add',
               '/account/games', '/account/games/permissions', '/account/games/revoke',
               '/account/notifications', '/account/notifications/read', '/account/revoke'):
    ROUTE_CATEGORIES[_route] = 'browser'


def category_for_path(path):
    """Exact static lookup; unmatched paths never become event text."""
    return ROUTE_CATEGORIES.get(path, 'unknown')

_current = ContextVar('ga_observability', default=None)


def request_id():
    state = _current.get()
    return state['request_id'] if state is not None else None


def classify_request(*, category=None, reason=None):
    """Handlers pass constants only, after their existing security decisions."""
    if category is not None and (type(category) is not str or category not in CATEGORIES):
        raise ValueError('invalid_event_category')
    if reason is not None and (type(reason) is not str or reason not in REASONS):
        raise ValueError('invalid_event_reason')
    state = _current.get()
    if state is not None:
        # Copy rather than mutating state inherited by child tasks.
        _current.set(dict(state, **({'category': category} if category else {}),
                          **({'reason': reason} if reason else {})))


def origin_class(headers, expected_origin):
    values = [v for k, v in headers if k.lower() == b'origin']
    if not values:
        return 'absent'
    if len(values) != 1:
        return 'other'
    if values[0] == b'null':
        return 'null'
    return 'exact' if values[0] == expected_origin else 'other'


def valid_event(event):
    if type(event) is not dict or set(event) != {
        'event', 'component', 'request_id', 'category', 'method', 'status',
        'reason', 'duration_ms', 'origin',
    }:
        return False
    if any(type(event[k]) is not str for k in ('event', 'component', 'request_id', 'category', 'method', 'reason', 'origin')):
        return False
    return (event['event'] == 'http_request' and event['component'] == 'server'
        and re.fullmatch(ID_PATTERN, event['request_id']) is not None
        and event['category'] in CATEGORIES and event['method'] in METHODS | {'OTHER'}
        and type(event['status']) is int and 100 <= event['status'] <= 599
        and event['reason'] in REASONS
        and type(event['duration_ms']) is int and 0 <= event['duration_ms'] <= 86400000
        and event['origin'] in ('exact', 'null', 'absent', 'other'))


class SafeEventFilter(logging.Filter):
    def filter(self, record):
        # Reject all arbitrary logs, including verbose transport logs, on THIS sink.
        return (record.name == LOGGER_NAME and not record.args
                and record.exc_info is None and record.stack_info is None
                and valid_event(record.msg))


class SafeEventFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(record.msg, sort_keys=True, separators=(',', ':'))


def configure_safe_stdout(stream=None):
    """Opt-in sole root sink; drops other logs, does not redact unknown handlers.

    Review other handlers, direct stderr writes and proxy access logs separately.
    Call after logging setup; later reconfiguration can undo this protection.
    """
    handler = logging.StreamHandler(sys.stdout if stream is None else stream)
    handler.addFilter(SafeEventFilter())
    handler.setFormatter(SafeEventFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    # Existing named HTTP loggers may have their own unfiltered handlers.
    names = {LOGGER_NAME, 'httpx', 'httpcore', 'uvicorn', 'uvicorn.error', 'uvicorn.access'}
    names.update(name for name in logging.Logger.manager.loggerDict
                 if name.startswith(('httpx.', 'httpcore.', 'uvicorn.')))
    for name in names:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.disabled = False
        logger.setLevel(logging.NOTSET)
    return handler


def emit_event(event):
    if not valid_event(event):
        raise ValueError('invalid_observability_event')
    logging.getLogger(LOGGER_NAME).info(dict(event))


class ObservabilityMiddleware:
    def __init__(self, app, *, expected_origin, emit=emit_event):
        self.app = app
        self.expected_origin = expected_origin.encode('ascii')
        self.emit = emit

    def __getattr__(self, name):
        # Preserve Starlette's state/routes interface while wrapping its outer
        # ServerErrorMiddleware, so even generated 500 responses get a request ID.
        return getattr(self.app, name)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        rid = secrets.token_hex(16)  # Never accept an inbound correlation ID.
        token = _current.set({'request_id': rid, 'category': category_for_path(scope.get('path', '')), 'reason': 'none'})
        start = time.monotonic()
        status = 500
        failed = False
        cancelled = False

        async def wrapped_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                message = dict(message)
                message['headers'] = [(k, v) for k, v in message.get('headers', [])
                                      if k.lower() != b'x-request-id'] + [(b'x-request-id', rid.encode('ascii'))]
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception:
            failed = True
            raise
        finally:
            state = _current.get()
            reason = state['reason']
            if cancelled:
                reason = 'request_cancelled'
            elif failed:
                reason = 'internal_error'
            elif reason == 'none' and status >= 400:
                reason = {400: 'invalid_request', 401: 'unauthenticated', 403: 'unknown',
                          404: 'not_found', 500: 'internal_error', 422: 'invalid_request', 429: 'rate_limited'}.get(status, 'unknown')
            event = dict(event='http_request', component='server', request_id=rid,
                category=state['category'], method=scope.get('method') if scope.get('method') in METHODS else 'OTHER',
                status=status, reason=reason,
                duration_ms=min(86400000, max(0, int((time.monotonic() - start) * 1000))),
                origin=origin_class(scope.get('headers', []), self.expected_origin))
            _current.reset(token)
            try:
                self.emit(event)
            except Exception:
                # Observability must never replace an auth decision or app exception.
                pass
