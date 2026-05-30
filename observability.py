#!/usr/bin/env python3
"""
Abu-Zahra Observability Module
Prometheus metrics, Sentry integration, and performance monitoring.
"""

import os
import time
import asyncio
import threading
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from functools import wraps
import logging

# Prometheus client
from prometheus_client import (
    Counter, Gauge, Histogram, Info, Enum,
    CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST,
    start_http_server, REGISTRY
)

log = logging.getLogger("abu-zahra.observability")

# ============================================================================
# CONFIGURATION
# ============================================================================

PROMETHEUS_ENABLED = os.environ.get("PROMETHEUS_ENABLED", "true").lower() == "true"
PROMETHEUS_PORT = int(os.environ.get("PROMETHEUS_PORT", "9091"))
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")

# ============================================================================
# METRICS REGISTRY
# ============================================================================

# Create a custom registry for our metrics
registry = CollectorRegistry()

# ============================================================================
# DEVICE METRICS
# ============================================================================

devices_online = Gauge(
    'abuzahra_devices_online',
    'Number of devices currently online',
    registry=registry
)

devices_total = Gauge(
    'abuzahra_devices_total',
    'Total number of registered devices',
    registry=registry
)

devices_by_state = Gauge(
    'abuzahra_devices_by_state',
    'Number of devices by state',
    ['state'],
    registry=registry
)

device_battery_level = Gauge(
    'abuzahra_device_battery_level',
    'Battery level of device',
    ['device_id'],
    registry=registry
)

device_storage_used = Gauge(
    'abuzahra_device_storage_used_bytes',
    'Storage used by device in bytes',
    ['device_id'],
    registry=registry
)

device_last_seen = Gauge(
    'abuzahra_device_last_seen_timestamp',
    'Unix timestamp of device last seen',
    ['device_id'],
    registry=registry
)

# ============================================================================
# COMMAND METRICS
# ============================================================================

commands_total = Counter(
    'abuzahra_commands_total',
    'Total number of commands processed',
    ['command', 'source'],
    registry=registry
)

commands_success = Counter(
    'abuzahra_commands_success_total',
    'Number of successful commands',
    ['command'],
    registry=registry
)

commands_failed = Counter(
    'abuzahra_commands_failed_total',
    'Number of failed commands',
    ['command', 'error_type'],
    registry=registry
)

commands_queued = Gauge(
    'abuzahra_commands_queued',
    'Number of commands currently queued',
    ['device_id'],
    registry=registry
)

command_duration = Histogram(
    'abuzahra_command_duration_seconds',
    'Time to execute a command',
    ['command'],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
    registry=registry
)

command_queue_size = Gauge(
    'abuzahra_command_queue_size',
    'Size of command queue',
    ['priority'],
    registry=registry
)

# ============================================================================
# API METRICS
# ============================================================================

http_requests_total = Counter(
    'abuzahra_http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status'],
    registry=registry
)

http_request_duration = Histogram(
    'abuzahra_http_request_duration_seconds',
    'HTTP request duration',
    ['method', 'endpoint'],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=registry
)

http_requests_in_progress = Gauge(
    'abuzahra_http_requests_in_progress',
    'Number of HTTP requests in progress',
    ['method', 'endpoint'],
    registry=registry
)

# ============================================================================
# WEBSOCKET METRICS
# ============================================================================

websocket_connections = Gauge(
    'abuzahra_websocket_connections',
    'Number of active WebSocket connections',
    registry=registry
)

websocket_messages_sent = Counter(
    'abuzahra_websocket_messages_sent_total',
    'Total WebSocket messages sent',
    ['message_type'],
    registry=registry
)

websocket_messages_received = Counter(
    'abuzahra_websocket_messages_received_total',
    'Total WebSocket messages received',
    ['message_type'],
    registry=registry
)

websocket_errors = Counter(
    'abuzahra_websocket_errors_total',
    'Total WebSocket errors',
    ['error_type'],
    registry=registry
)

# ============================================================================
# SYSTEM METRICS
# ============================================================================

system_info = Info(
    'abuzahra_system',
    'System information',
    registry=registry
)

system_uptime = Gauge(
    'abuzahra_uptime_seconds',
    'System uptime in seconds',
    registry=registry
)

database_connections = Gauge(
    'abuzahra_database_connections',
    'Number of database connections',
    ['state'],
    registry=registry
)

cache_hits = Counter(
    'abuzahra_cache_hits_total',
    'Total cache hits',
    registry=registry
)

cache_misses = Counter(
    'abuzahra_cache_misses_total',
    'Total cache misses',
    registry=registry
)

cache_size = Gauge(
    'abuzahra_cache_size',
    'Number of items in cache',
    registry=registry
)

# ============================================================================
# TELEGRAM BOT METRICS
# ============================================================================

telegram_messages_sent = Counter(
    'abuzahra_telegram_messages_sent_total',
    'Total Telegram messages sent',
    registry=registry
)

telegram_messages_received = Counter(
    'abuzahra_telegram_messages_received_total',
    'Total Telegram messages received',
    registry=registry
)

telegram_api_calls = Counter(
    'abuzahra_telegram_api_calls_total',
    'Total Telegram API calls',
    ['method'],
    registry=registry
)

telegram_api_errors = Counter(
    'abuzahra_telegram_api_errors_total',
    'Total Telegram API errors',
    ['method', 'error_code'],
    registry=registry
)

# ============================================================================
# FILE METRICS
# ============================================================================

files_uploaded = Counter(
    'abuzahra_files_uploaded_total',
    'Total files uploaded',
    ['device_id', 'mime_type'],
    registry=registry
)

file_upload_size = Histogram(
    'abuzahra_file_upload_size_bytes',
    'File upload size in bytes',
    buckets=(1024, 10*1024, 100*1024, 1024*1024, 10*1024*1024, 100*1024*1024),
    registry=registry
)

# ============================================================================
# ALERT METRICS
# ============================================================================

alerts_triggered = Counter(
    'abuzahra_alerts_triggered_total',
    'Total alerts triggered',
    ['severity', 'alert_type'],
    registry=registry
)

alerts_unacknowledged = Gauge(
    'abuzahra_alerts_unacknowledged',
    'Number of unacknowledged alerts',
    registry=registry
)

# ============================================================================
# OBSERVABILITY MANAGER
# ============================================================================

class ObservabilityManager:
    """Centralized observability management."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.start_time = time.time()
        self._setup_sentry()
        self._initialized = True

        log.info("Observability manager initialized")

    def _setup_sentry(self):
        """Setup Sentry error tracking."""
        if SENTRY_DSN:
            try:
                import sentry_sdk
                sentry_sdk.init(
                    dsn=SENTRY_DSN,
                    traces_sample_rate=0.1,
                    profiles_sample_rate=0.1,
                )
                log.info("Sentry initialized")
            except ImportError:
                log.warning("Sentry SDK not installed")

    def update_system_info(self, version: str, environment: str):
        """Update system info metric."""
        system_info.info({
            'version': version,
            'environment': environment
        })

    def update_uptime(self):
        """Update uptime metric."""
        system_uptime.set(time.time() - self.start_time)

    # Device metrics
    def set_devices_online(self, count: int):
        devices_online.set(count)

    def set_devices_total(self, count: int):
        devices_total.set(count)

    def set_devices_by_state(self, state: str, count: int):
        devices_by_state.labels(state=state).set(count)

    def update_device_metrics(self, device_id: str, battery: int, storage_used: int, last_seen: float):
        device_battery_level.labels(device_id=device_id).set(battery)
        device_storage_used.labels(device_id=device_id).set(storage_used)
        device_last_seen.labels(device_id=device_id).set(last_seen)

    # Command metrics
    def record_command(self, command: str, source: str = "telegram"):
        commands_total.labels(command=command, source=source).inc()

    def record_command_success(self, command: str):
        commands_success.labels(command=command).inc()

    def record_command_failure(self, command: str, error_type: str = "unknown"):
        commands_failed.labels(command=command, error_type=error_type).inc()

    def observe_command_duration(self, command: str, duration: float):
        command_duration.labels(command=command).observe(duration)

    def set_command_queue_size(self, priority: str, size: int):
        command_queue_size.labels(priority=priority).set(size)

    # HTTP metrics
    def record_http_request(self, method: str, endpoint: str, status: int, duration: float):
        http_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
        http_request_duration.labels(method=method, endpoint=endpoint).observe(duration)

    def start_http_request(self, method: str, endpoint: str):
        http_requests_in_progress.labels(method=method, endpoint=endpoint).inc()

    def end_http_request(self, method: str, endpoint: str):
        http_requests_in_progress.labels(method=method, endpoint=endpoint).dec()

    # WebSocket metrics
    def set_websocket_connections(self, count: int):
        websocket_connections.set(count)

    def record_ws_message_sent(self, message_type: str):
        websocket_messages_sent.labels(message_type=message_type).inc()

    def record_ws_message_received(self, message_type: str):
        websocket_messages_received.labels(message_type=message_type).inc()

    def record_ws_error(self, error_type: str):
        websocket_errors.labels(error_type=error_type).inc()

    # Cache metrics
    def record_cache_hit(self):
        cache_hits.inc()

    def record_cache_miss(self):
        cache_misses.inc()

    def set_cache_size(self, size: int):
        cache_size.set(size)

    # Telegram metrics
    def record_telegram_message_sent(self):
        telegram_messages_sent.inc()

    def record_telegram_message_received(self):
        telegram_messages_received.inc()

    def record_telegram_api_call(self, method: str):
        telegram_api_calls.labels(method=method).inc()

    def record_telegram_api_error(self, method: str, error_code: int):
        telegram_api_errors.labels(method=method, error_code=str(error_code)).inc()

    # File metrics
    def record_file_upload(self, device_id: str, mime_type: str, size: int):
        files_uploaded.labels(device_id=device_id, mime_type=mime_type).inc()
        file_upload_size.observe(size)

    # Alert metrics
    def record_alert(self, severity: str, alert_type: str):
        alerts_triggered.labels(severity=severity, alert_type=alert_type).inc()

    def set_unacknowledged_alerts(self, count: int):
        alerts_unacknowledged.set(count)


# ============================================================================
# TIMING DECORATORS
# ============================================================================

def timed_command(command: str):
    """Decorator to time command execution."""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                observability.record_command_success(command)
                return result
            except Exception as e:
                observability.record_command_failure(command, type(e).__name__)
                raise
            finally:
                duration = time.time() - start
                observability.observe_command_duration(command, duration)
                observability.record_command(command)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                observability.record_command_success(command)
                return result
            except Exception as e:
                observability.record_command_failure(command, type(e).__name__)
                raise
            finally:
                duration = time.time() - start
                observability.observe_command_duration(command, duration)
                observability.record_command(command)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator


def timed_http(endpoint: str):
    """Decorator to time HTTP requests."""
    def decorator(func):
        @wraps(func)
        async def wrapper(request, *args, **kwargs):
            method = request.method if hasattr(request, 'method') else 'GET'
            observability.start_http_request(method, endpoint)

            start = time.time()
            try:
                result = await func(request, *args, **kwargs)
                status = result.status if hasattr(result, 'status') else 200
                return result
            finally:
                duration = time.time() - start
                observability.end_http_request(method, endpoint)
                observability.record_http_request(method, endpoint, status, duration)

        return wrapper
    return decorator


# ============================================================================
# METRICS ENDPOINT HANDLER
# ============================================================================

async def metrics_handler(request):
    """Handler for /metrics endpoint."""
    from aiohttp import web

    # Update uptime
    observability.update_uptime()

    # Generate metrics
    metrics_output = generate_latest(registry)
    return web.Response(
        body=metrics_output,
        content_type=CONTENT_TYPE_LATEST
    )


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

observability = ObservabilityManager()


# ============================================================================
# STARTUP FUNCTION
# ============================================================================

def start_prometheus_server():
    """Start Prometheus HTTP server."""
    if PROMETHEUS_ENABLED:
        try:
            start_http_server(PROMETHEUS_PORT, registry=registry)
            log.info("Prometheus metrics server started on port %d", PROMETHEUS_PORT)
        except Exception as e:
            log.error("Failed to start Prometheus server: %s", e)
