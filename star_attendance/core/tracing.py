"""OpenTelemetry tracing configuration for Star ASN.

Provides distributed tracing for the API, worker, and bot services.
Exports traces to an OTLP endpoint (e.g., Jaeger, Grafana Tempo).

Enable by setting OTEL_EXPORTER_OTLP_ENDPOINT environment variable.
If not set, tracing is disabled (no-op tracer).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("otel")


def setup_tracing(service_name: str = "star-asn") -> None:
    """Initialize OpenTelemetry tracing if configured.

    Requires OTEL_EXPORTER_OTLP_ENDPOINT to be set (e.g., http://localhost:4317).
    If not set, tracing is silently disabled.
    """
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.info("OpenTelemetry: No OTLP endpoint configured. Tracing disabled.")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": "1.0.0",
                "deployment.environment": os.getenv("OTEL_DEPLOYMENT_ENVIRONMENT", "production"),
            }
        )

        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        logger.info(f"OpenTelemetry: Tracing enabled for '{service_name}' → {endpoint}")

    except ImportError:
        logger.warning("OpenTelemetry packages not installed. Tracing disabled.")
    except Exception as exc:
        logger.warning(f"OpenTelemetry setup failed: {exc}. Tracing disabled.")


def instrument_fastapi(app: object) -> None:
    """Instrument a FastAPI application with OpenTelemetry."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)  # type: ignore
        logger.info("OpenTelemetry: FastAPI instrumented.")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-fastapi not available.")
    except Exception as exc:
        logger.warning(f"FastAPI instrumentation failed: {exc}")


def instrument_httpx() -> None:
    """Instrument httpx client with OpenTelemetry."""
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()  # type: ignore
        logger.info("OpenTelemetry: httpx instrumented.")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-httpx not available.")
    except Exception as exc:
        logger.warning(f"httpx instrumentation failed: {exc}")


def instrument_asyncpg() -> None:
    """Instrument asyncpg with OpenTelemetry."""
    try:
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor

        AsyncPGInstrumentor().instrument()  # type: ignore
        logger.info("OpenTelemetry: asyncpg instrumented.")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-asyncpg not available.")
    except Exception as exc:
        logger.warning(f"asyncpg instrumentation failed: {exc}")
