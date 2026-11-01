import asyncio
import io
import json
import logging
import unittest
from unittest.mock import patch

from remote_server.observability import (ObservabilityMiddleware, classify_request,
    configure_safe_stdout, emit_event, origin_class, request_id, valid_event)

SECRET = 'SENTINEL:/home/deck/private.sav?steamid=76561198000000001&code=oauth&token=device'
ORIGIN = 'https://example.test'

class ObservabilityTests(unittest.IsolatedAsyncioTestCase):
    def scope(self):
        return {'type': 'http', 'method': 'POST', 'path': SECRET, 'raw_path': SECRET.encode(),
                'query_string': SECRET.encode(), 'headers': [
                    (b'origin', SECRET.encode()), (b'authorization', SECRET.encode()),
                    (b'cookie', SECRET.encode()), (b'x-request-id', b'a'*32)]}

    async def invoke(self, app, scope=None, emit=None):
        events, sent = [], []
        async def receive():
            raise AssertionError('observability must not read request body')
        async def send(message):
            sent.append(message)
        await ObservabilityMiddleware(app, expected_origin=ORIGIN, emit=emit or events.append)(scope or self.scope(), receive, send)
        return events, sent

    async def test_safe_fields_and_header_correlation(self):
        async def app(scope, receive, send):
            self.assertIsNotNone(request_id())
            classify_request(category='pairing', reason='pairing_expired')
            await send({'type': 'http.response.start', 'status': 403,
                        'headers': [(b'x-request-id', SECRET.encode()), (b'set-cookie', SECRET.encode())]})
            await send({'type': 'http.response.body', 'body': SECRET.encode()})
        events, sent = await self.invoke(app)
        event = events[0]
        self.assertTrue(valid_event(event))
        self.assertNotIn(SECRET, json.dumps(events))
        self.assertEqual(event['reason'], 'pairing_expired')
        self.assertEqual(event['category'], 'pairing')
        self.assertEqual(event['origin'], 'other')
        self.assertNotEqual(event['request_id'], 'a'*32)
        self.assertEqual(dict(sent[0]['headers'])[b'x-request-id'].decode(), event['request_id'])
        self.assertEqual(dict(sent[0]['headers'])[b'set-cookie'], SECRET.encode())
        self.assertEqual(sent[1]['body'], SECRET.encode())
        self.assertIsNone(request_id())

    async def test_concurrent_requests_and_child_context_are_isolated(self):
        async def app(scope, receive, send):
            before = request_id()
            classify_request(category='pairing')
            async def child():
                classify_request(category='oauth')
            await asyncio.create_task(child())
            await asyncio.sleep(0)
            self.assertEqual(before, request_id())
            await send({'type': 'http.response.start', 'status': 200})
        results = await asyncio.gather(*(self.invoke(app) for _ in range(40)))
        events = [result[0][0] for result in results]
        self.assertEqual(len({event['request_id'] for event in events}), 40)
        self.assertTrue(all(event['category'] == 'pairing' for event in events))
        self.assertIsNone(request_id())

    async def test_exception_is_not_formatted_or_swallowed(self):
        events = []
        error = RuntimeError(SECRET)
        async def app(scope, receive, send):
            raise error
        with self.assertRaises(RuntimeError) as caught:
            await self.invoke(app, emit=events.append)
        self.assertIs(caught.exception, error)
        self.assertEqual(events[0]['reason'], 'internal_error')
        self.assertNotIn(SECRET, json.dumps(events))
        self.assertIsNone(request_id())

    async def test_cancellation_and_stream_failure(self):
        for error, reason in [(asyncio.CancelledError(), 'request_cancelled'), (RuntimeError(SECRET), 'internal_error')]:
            events = []
            async def app(scope, receive, send):
                await send({'type': 'http.response.start', 'status': 200})
                raise error
            with self.assertRaises(type(error)):
                await self.invoke(app, emit=events.append)
            self.assertEqual(events[0]['status'], 200)
            self.assertEqual(events[0]['reason'], reason)
            self.assertIsNone(request_id())

    async def test_auth_decisions_and_sink_failure_preserved(self):
        for status in (401, 403, 422, 429):
            async def app(scope, receive, send):
                await send({'type': 'http.response.start', 'status': status})
            def broken(event):
                raise OSError(SECRET)
            _, sent = await self.invoke(app, emit=broken)
            self.assertEqual(sent[0]['status'], status)
            self.assertIsNone(request_id())

    async def test_no_event_for_non_http(self):
        async def app(scope, receive, send):
            self.assertIsNone(request_id())
        self.assertEqual(await self.invoke(app, {'type': 'lifespan'}), ([], []))

    async def test_unknown_method_and_unclassified_route(self):
        async def app(scope, receive, send):
            await send({'type': 'http.response.start', 'status': 404})
        events, _ = await self.invoke(app, self.scope() | {'method': SECRET})
        self.assertEqual(events[0]['method'], 'OTHER')
        self.assertEqual(events[0]['category'], 'unknown')
        self.assertNotIn(SECRET, json.dumps(events))

    def test_origin_classification_is_not_authorization(self):
        for headers, expected in [([], 'absent'), ([(b'origin', b'null')], 'null'),
            ([(b'origin', ORIGIN.encode())], 'exact'),
            ([(b'origin', (ORIGIN+'/').encode())], 'other'),
            ([(b'origin', ORIGIN.encode())]*2, 'other')]:
            self.assertEqual(origin_class(headers, ORIGIN.encode()), expected)

    def test_invalid_classification_rejected_without_echo(self):
        for args in ({'category': SECRET}, {'reason': SECRET}, {'category': []}):
            with self.assertRaises(ValueError) as caught:
                classify_request(**args)
            self.assertNotIn(SECRET, str(caught.exception))

    async def test_stdout_only_allowlisted_events_even_with_httpx_debug(self):
        async def app(scope, receive, send):
            await send({'type': 'http.response.start', 'status': 200})
        events, _ = await self.invoke(app)
        names = ['', 'game_assist.safe_events', 'httpx', 'httpcore', 'uvicorn', 'uvicorn.error', 'uvicorn.access']
        names += [n for n in logging.Logger.manager.loggerDict if n.startswith(('httpx.', 'httpcore.', 'uvicorn.')) and n not in names]
        saved = [(logging.getLogger(n), logging.getLogger(n).handlers[:], logging.getLogger(n).level,
                  logging.getLogger(n).propagate, logging.getLogger(n).disabled) for n in names]
        output = io.StringIO()
        try:
            configure_safe_stdout(output)
            logging.getLogger().setLevel(logging.DEBUG)
            for name in ('httpx', 'httpcore', 'httpcore.connection', 'uvicorn.access', 'unknown_library'):
                logger = logging.getLogger(name)
                logger.debug('HTTP Request %s', SECRET)
                logger.warning(SECRET)
            logging.getLogger('game_assist.safe_events').info(SECRET)
            logging.getLogger('game_assist.safe_events').info(events[0], exc_info=(RuntimeError, RuntimeError(SECRET), None))
            emit_event(events[0])
            self.assertEqual(json.loads(output.getvalue()), events[0])
            self.assertNotIn(SECRET, output.getvalue())
        finally:
            for logger, handlers, level, propagate, disabled in saved:
                logger.handlers[:] = handlers
                logger.setLevel(level); logger.propagate = propagate; logger.disabled = disabled

    async def test_real_httpx_transport_url_never_reaches_sink(self):
        try:
            import httpx
        except ImportError:
            self.skipTest('httpx not installed')
        output = io.StringIO()
        root = logging.getLogger(); handlers = root.handlers[:]; level = root.level
        # Filter on the actual root sink, including HTTPX's formatted URL at INFO.
        from remote_server.observability import SafeEventFilter, SafeEventFormatter
        sink = logging.StreamHandler(output); sink.addFilter(SafeEventFilter()); sink.setFormatter(SafeEventFormatter())
        try:
            root.handlers[:] = [sink]; root.setLevel(logging.DEBUG)
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
                await client.get('https://example.test/private?steamid=76561198000000001&key=SENTINEL')
            self.assertEqual(output.getvalue(), '')
        finally:
            root.handlers[:] = handlers; root.setLevel(level)
