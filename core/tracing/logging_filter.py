"""Filter de logging: agrega request_id/user_id a TODO log record sin
que cada `logger.info(...)` tenga que pasarlo manualmente."""
import logging

from core.tracing.context import get_request_id, get_user_id


class RequestTracingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        record.user_id = get_user_id()
        return True
