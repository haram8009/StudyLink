"""Optional direct SDK tracing; telemetry must never swallow business errors."""
import os
import sys
from contextlib import contextmanager


class Observation:
    def __init__(self, span=None):
        self.span = span

    def update(self, **values):
        if self.span is not None:
            try:
                self.span.update(**values)
            except Exception:
                pass


def _client():
    if os.getenv('LANGFUSE_ENABLED', '0') != '1':
        return None
    from langfuse import get_client
    return get_client()


@contextmanager
def observe(name, *, as_type='span', **values):
    manager = None
    observation = Observation()
    try:
        client = _client()
        if client is not None:
            candidate = client.start_as_current_observation(name=name, as_type=as_type, **values)
            observation = Observation(candidate.__enter__())
            manager = candidate
    except Exception:
        pass
    try:
        yield observation
    except BaseException:
        error = sys.exc_info()
        if manager is not None:
            try:
                manager.__exit__(*error)
            except Exception:
                pass
        raise
    else:
        if manager is not None:
            try:
                manager.__exit__(None, None, None)
            except Exception:
                pass


def flush():
    try:
        client = _client()
        if client is not None:
            client.flush()
    except Exception:
        pass


def current_trace_id():
    try:
        client = _client()
        return client.get_current_trace_id() if client is not None else None
    except Exception:
        return None
