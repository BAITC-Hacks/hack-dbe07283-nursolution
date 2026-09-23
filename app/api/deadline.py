"""Отсчёт бюджета с момента передачи HTTP-запроса приложению ASGI."""
from time import monotonic
import json
import logging
from uuid import uuid4

logger = logging.getLogger('uvicorn.error')


class RequestClockMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        started = monotonic()
        state = scope.setdefault('state', {})
        state['request_started'] = started
        state['request_id'] = uuid4().hex
        status = 500

        async def tracked_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                message.setdefault('headers', []).append((b'x-request-id', state['request_id'].encode()))
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        finally:
            if scope['path'] == '/match':
                elapsed = monotonic() - started
                matcher = getattr(scope['app'].state, 'matcher', None)
                if matcher is not None:
                    metrics = matcher.explanations.metrics
                    metrics.increment(f'http_match_{status // 100}xx')
                    metrics.observe('http_match', elapsed)
                logger.info(json.dumps(dict(event='match_completed', request_id=state['request_id'],
                                            status=status, seconds=round(elapsed, 4))))
