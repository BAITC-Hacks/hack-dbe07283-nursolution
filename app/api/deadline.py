"""Отсчёт бюджета с момента передачи HTTP-запроса приложению ASGI."""
from time import monotonic


class RequestClockMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope.setdefault("state", {})["request_started"] = monotonic()
        await self.app(scope, receive, send)
