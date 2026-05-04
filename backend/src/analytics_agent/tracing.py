"""
OTEL tracing setup.

Supported env vars (all standard OTEL):
  OTEL_EXPORTER_OTLP_ENDPOINT   e.g. http://localhost:4317 or https://api.honeycomb.io
  OTEL_EXPORTER_OTLP_HEADERS    e.g. x-honeycomb-team=abc123
  OTEL_SERVICE_NAME              default: datahub-analytics-agent
  OTEL_TRACES_EXPORTER           default: otlp (set to "none" to disable)

A TracerProvider is always created so that the MixpanelSpanProcessor (telemetry)
captures business spans even when no OTEL endpoint is configured. The OTLP
exporter is only added when OTEL_EXPORTER_OTLP_ENDPOINT is set.

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
    otel_active = bool(endpoint) and exporter_env != "none"

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        from analytics_agent.telemetry import mixpanel_processor

        service_name = os.environ.get("OTEL_SERVICE_NAME", "datahub-analytics-agent")
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))

        if otel_active:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
                )
            )

            # Auto-instrument FastAPI (request/response spans)
            if app is not None:
                from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

                FastAPIInstrumentor.instrument_app(app)

            # Auto-instrument LangChain/LangGraph (LLM + tool call spans with gen_ai.* attributes).
            # wrapt 2.x renamed wrap_function_wrapper's first param from 'module' → 'target'
            # (positional-only). The langchain instrumentor still calls it with module= as a
            # keyword arg. Patch the name in the instrumentor's own module namespace so the
            # already-bound reference is fixed.
            try:
                from opentelemetry.instrumentation.langchain import LangchainInstrumentor

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

            logger.info(
                "OTEL tracing enabled — service=%s endpoint=%s", service_name, endpoint
            )
        else:
            logger.debug(
                "OTEL export disabled (OTEL_EXPORTER_OTLP_ENDPOINT not set); "
                "TracerProvider still active for telemetry spans"
            )

        # Always register the Mixpanel processor — it ignores spans whose name
        # is not in KNOWN_SPAN_NAMES, so overhead on unrelated spans is minimal.
        provider.add_span_processor(mixpanel_processor)
        trace.set_tracer_provider(provider)

    except ImportError as e:
        logger.warning("OTEL packages not available, tracing disabled: %s", e)
    except Exception as e:
        logger.warning("OTEL setup failed, tracing disabled: %s", e)
