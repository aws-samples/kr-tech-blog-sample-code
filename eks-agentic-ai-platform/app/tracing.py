"""Langfuse v4 트레이싱 — OpenTelemetry 기반

Langfuse 키가 설정되어 있으면 @observe 데코레이터가 자동으로 span을 기록합니다.
키가 없으면 no-op으로 동작하여 앱 로직에 영향을 주지 않습니다.
"""

from contextlib import contextmanager

from app.config import LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_HOST

LANGFUSE_ENABLED = bool(LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY)

_client = None

if LANGFUSE_ENABLED:
    from langfuse import Langfuse
    from langfuse import observe as _observe
    from langfuse import propagate_attributes as _propagate_attributes

    def get_langfuse_client() -> "Langfuse | None":
        global _client
        if _client is not None:
            return _client
        _client = Langfuse(
            secret_key=LANGFUSE_SECRET_KEY,
            public_key=LANGFUSE_PUBLIC_KEY,
            host=LANGFUSE_HOST,
        )
        return _client

    observe = _observe
    propagate_attributes = _propagate_attributes

    # 앱 시작 시 클라이언트 초기화
    get_langfuse_client()
else:
    def get_langfuse_client():
        return None

    def observe(*args, **kwargs):
        """No-op @observe decorator"""
        def decorator(fn):
            return fn
        if args and callable(args[0]):
            return args[0]
        return decorator

    @contextmanager
    def propagate_attributes(**kwargs):
        """No-op propagate_attributes context manager"""
        yield
