"""OpenTelemetry hook (F1-T08): integration point only.

``TelemetryMiddleware`` (``app.api.telemetry``) opens one server span per request through the
OpenTelemetry API. Without a configured provider the API tracer is a no-op, so F1 has no
exporter, no credentials, no external monitoring and makes no network calls. A provider can be
supplied later through ``set_tracer_provider``. Spans carry only the method, the route
template (never the raw path), the status code, the request id and the error type; no query
strings, headers, addresses, bodies or exception messages.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.trace import Tracer, TracerProvider

INSTRUMENTATION_NAME = "autotramita"

_provider: TracerProvider | None = None


def set_tracer_provider(provider: TracerProvider | None) -> None:
    """Use ``provider`` for request spans; ``None`` returns to the OpenTelemetry default."""
    global _provider
    _provider = provider


def get_tracer() -> Tracer:
    provider = _provider if _provider is not None else trace.get_tracer_provider()
    return provider.get_tracer(INSTRUMENTATION_NAME)
