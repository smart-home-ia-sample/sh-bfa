from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from smart_home_common import get_or_create_correlation_id, new_id
from smart_home_common.correlation import CORRELATION_HEADER, REQUEST_ID_HEADER
from smart_home_common.logging_config import log_context


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        correlation_id = get_or_create_correlation_id(request.headers.get(CORRELATION_HEADER))
        request_id = new_id()

        with log_context(correlation_id=correlation_id, request_id=request_id):
            request.state.correlation_id = correlation_id
            request.state.request_id = request_id
            response = await call_next(request)

        response.headers[CORRELATION_HEADER] = correlation_id
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
