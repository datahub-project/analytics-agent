"""
OTEL tracing setup. No-op when OTEL_EXPORTER_OTLP_ENDPOINT is not set.

Supported env vars (all standard OTEL):
  OTEL_EXPORTER_OTLP_ENDPOINT   e.g. http://localhost:4317 or https://api.honeycomb.io
  OTEL_EXPORTER_OTLP_HEADERS    e.g. x-honeycomb-team=abc123
  OTEL_SERVICE_NAME              default: analytics_agent
  OTEL_TRACES_EXPORTER           default: otlp (set to "none" to disable)

LangChain/LangGraph spans follow the gen_ai.* semantic conventions:
  gen_ai.system, gen_ai.request.model,
  gen_ai.usage.input_tokens, gen_ai.usage.output_tokens
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def setup_tracing(app=None) -> None:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    exporter_env = os.environ.get("OTEL_TRACES_EXPORTER", "otlp")

    if not endpoint or exporter_env == "none":
        logger.debug("OTEL tracing disabled (OTEL_EXPORTER_OTLP_ENDPOINT not set)")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.langchain import LangchainInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        service_name = os.environ.get("OTEL_SERVICE_NAME", "datahub-analytics-agent")

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces"))
        )
        trace.set_tracer_provider(provider)

        # Auto-instrument FastAPI (request/response spans)
        if app is not None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app)

        # Auto-instrument LangChain/LangGraph (LLM + tool call spans with gen_ai.* attributes).
        # wrapt 2.x renamed wrap_function_wrapper's first param from 'module' → 'target'
        # (positional-only). The langchain instrumentor still calls it with module= as a
        # keyword arg. Shim it in-place for the duration of instrument() then restore.
        # wrapt 2.x renamed wrap_function_wrapper's first param from 'module' → 'target'.
        # The langchain instrumentor uses `from wrapt import wrap_function_wrapper` then
        # calls it with module= as a keyword arg. Patch the name in the instrumentor's
        # own module namespace (not on wrapt itself) so the already-bound reference is fixed.
        try:
            import opentelemetry.instrumentation.langchain as _lc_mod
            import wrapt as _wrapt

            _orig_wrapt = _wrapt.wrap_function_wrapper

            def _compat(target=None, name=None, wrapper=None, module=None, **kw):
                return _orig_wrapt(target or module, name, wrapper, **kw)

            _orig_lc = getattr(_lc_mod, "wrap_function_wrapper", None)
            _lc_mod.wrap_function_wrapper = _compat
            try:
                LangchainInstrumentor().instrument()
            finally:
                if _orig_lc is not None:
                    _lc_mod.wrap_function_wrapper = _orig_lc
                else:
                    delattr(_lc_mod, "wrap_function_wrapper")
            logger.info("OTEL LangChain instrumentation active")
        except Exception as e:
            logger.warning("OTEL LangChain instrumentation skipped: %s", e)

        logger.info("OTEL tracing enabled — service=%s endpoint=%s", service_name, endpoint)

    except ImportError as e:
        logger.warning("OTEL packages not available, tracing disabled: %s", e)
    except Exception as e:
        logger.warning("OTEL setup failed, tracing disabled: %s", e)
