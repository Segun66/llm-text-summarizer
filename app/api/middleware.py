import logging
from time import perf_counter
from uuid import UUID, uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.utils.logging import log_event, request_id_context


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        for name, value in scope.get("headers", []):
            if name.lower() == b"x-request-id":
                try:
                    request_id = str(UUID(value.decode("ascii")))
                except (ValueError, UnicodeError):
                    pass
                break
        token = request_id_context.set(request_id)
        started = perf_counter()
        status_code = 500
        error_type = None
        log_event("request_started", "http")

        async def send_response(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                message = {**message, "headers": [*headers, (b"x-request-id", request_id.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        except Exception as error:
            error_type = type(error).__name__
            raise
        finally:
            log_event(
                "request_finished",
                "http",
                level=logging.ERROR if error_type else logging.INFO,
                status_code=status_code,
                duration_ms=(perf_counter() - started) * 1000,
                error_type=error_type,
            )
            request_id_context.reset(token)
