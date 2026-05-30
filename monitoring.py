#!/usr/bin/env python3
"""
Abu-Zahra Logging and Monitoring System
Structured logging with rotation, metrics, and alerting.
"""

import os
import sys
import time
import json
import logging
import threading
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import deque
import gzip
import shutil

# ============================================================================
# CONFIGURATION
# ============================================================================

LOGS_DIR = Path(__file__).parent / "data" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# LOG LEVELS
# ============================================================================

class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

# ============================================================================
# STRUCTURED LOG RECORD
# ============================================================================

@dataclass
class StructuredLogRecord:
    """Structured log record."""
    timestamp: float
    level: str
    logger: str
    message: str
    device_id: Optional[str] = None
    command_id: Optional[str] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    stack_trace: Optional[str] = None
    extra: Dict = field(default_factory=dict)
    
    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)
    
    def to_logfmt(self) -> str:
        parts = [
            f"time={datetime.fromtimestamp(self.timestamp).isoformat()}",
            f"level={self.level}",
            f"logger={self.logger}",
            f'msg="{self.message}"'
        ]
        if self.device_id:
            parts.append(f"device={self.device_id}")
        if self.command_id:
            parts.append(f"cmd={self.command_id}")
        if self.duration_ms:
            parts.append(f"duration={self.duration_ms}ms")
        if self.error:
            parts.append(f'error="{self.error}"')
        return " ".join(parts)

# ============================================================================
# STRUCTURED LOG HANDLER
# ============================================================================

class StructuredLogHandler(logging.Handler):
    """Custom log handler for structured logging."""
    
    def __init__(self, log_file: str = None, max_bytes: int = 10*1024*1024, backup_count: int = 5):
        super().__init__()
        self.log_file = Path(log_file) if log_file else LOGS_DIR / "abuzahra.jsonl"
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._lock = threading.RLock()
    
    def emit(self, record: logging.LogRecord):
        """Emit a structured log record."""
        try:
            # Create structured record
            structured = StructuredLogRecord(
                timestamp=record.created,
                level=record.levelname,
                logger=record.name,
                message=record.getMessage()
            )
            
            # Extract extra fields
            if hasattr(record, 'device_id'):
                structured.device_id = record.device_id
            if hasattr(record, 'command_id'):
                structured.command_id = record.command_id
            if hasattr(record, 'duration_ms'):
                structured.duration_ms = record.duration_ms
            if hasattr(record, 'extra'):
                structured.extra = record.extra
            
            # Handle exceptions
            if record.exc_info:
                structured.error = str(record.exc_info[1])
                structured.stack_trace = ''.join(traceback.format_exception(*record.exc_info))
            
            # Write to file
            with self._lock:
                self._write_record(structured)
            
        except Exception:
            self.handleError(record)
    
    def _write_record(self, record: StructuredLogRecord):
        """Write record to log file with rotation."""
        # Check for rotation
        if self.log_file.exists() and self.log_file.stat().st_size > self.max_bytes:
            self._rotate()
        
        # Append record
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(record.to_json() + '\n')
    
    def _rotate(self):
        """Rotate log files."""
        for i in range(self.backup_count - 1, 0, -1):
            old_file = self.log_file.with_suffix(f'.{i}.jsonl')
            new_file = self.log_file.with_suffix(f'.{i+1}.jsonl')
            if old_file.exists():
                old_file.rename(new_file)
        
        # Compress and rotate current
        current = self.log_file
        compressed = self.log_file.with_suffix('.1.jsonl.gz')
        with open(current, 'rb') as f_in:
            with gzip.open(compressed, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        current.unlink()

# ============================================================================
# LOGGING MANAGER
# ============================================================================

class LoggingManager:
    """Centralized logging configuration."""
    
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
        
        self.log_dir = LOGS_DIR
        self._handlers: Dict[str, logging.Handler] = {}
        self._setup_default_logging()
        self._initialized = True
    
    def _setup_default_logging(self):
        """Setup default logging configuration."""
        # Root logger
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        
        # Console handler
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        ))
        root.addHandler(console)
        
        # Structured file handler
        structured = StructuredLogHandler()
        structured.setLevel(logging.DEBUG)
        root.addHandler(structured)
        self._handlers['structured'] = structured
        
        # Error log handler
        error_handler = logging.FileHandler(self.log_dir / "errors.log")
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s\n%(exc_info)s'
        ))
        root.addHandler(error_handler)
        self._handlers['error'] = error_handler
    
    def get_logger(self, name: str) -> logging.Logger:
        """Get a logger instance."""
        return logging.getLogger(name)
    
    def log_command(self, logger: logging.Logger, level: int, message: str, 
                    device_id: str = None, command_id: str = None, duration_ms: float = None,
                    **extra):
        """Log a command-related message."""
        record = logger.makeRecord(
            logger.name, level, "", 0, message, (), None
        )
        if device_id:
            record.device_id = device_id
        if command_id:
            record.command_id = command_id
        if duration_ms:
            record.duration_ms = duration_ms
        if extra:
            record.extra = extra
        logger.handle(record)
    
    def get_log_stats(self) -> Dict:
        """Get logging statistics."""
        stats = {
            "log_dir": str(self.log_dir),
            "files": []
        }
        
        for log_file in self.log_dir.glob("*.jsonl*"):
            stats["files"].append({
                "name": log_file.name,
                "size": log_file.stat().st_size,
                "modified": log_file.stat().st_mtime
            })
        
        return stats

# ============================================================================
# METRICS
# ============================================================================

@dataclass
class Metric:
    """A single metric measurement."""
    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    tags: Dict[str, str] = field(default_factory=dict)
    metric_type: str = "gauge"  # gauge, counter, histogram

class MetricsCollector:
    """Collects and aggregates metrics."""
    
    def __init__(self, max_history: int = 10000):
        self.max_history = max_history
        self._metrics: Dict[str, deque] = {}
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}
        self._lock = threading.RLock()
    
    def record(self, name: str, value: float, tags: Dict[str, str] = None):
        """Record a metric value."""
        with self._lock:
            metric = Metric(name=name, value=value, tags=tags or {})
            
            if name not in self._metrics:
                self._metrics[name] = deque(maxlen=self.max_history)
            self._metrics[name].append(metric)
    
    def increment(self, name: str, amount: float = 1, tags: Dict[str, str] = None):
        """Increment a counter."""
        with self._lock:
            if name not in self._counters:
                self._counters[name] = 0
            self._counters[name] += amount
            self.record(name, self._counters[name], tags)
    
    def gauge(self, name: str, value: float, tags: Dict[str, str] = None):
        """Set a gauge value."""
        with self._lock:
            self._gauges[name] = value
            self.record(name, value, tags)
    
    def histogram(self, name: str, value: float, tags: Dict[str, str] = None):
        """Record a histogram value."""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(value)
            
            # Keep last 1000 values
            if len(self._histograms[name]) > 1000:
                self._histograms[name] = self._histograms[name][-1000:]
            
            self.record(name, value, tags)
    
    def timing(self, name: str, duration_ms: float, tags: Dict[str, str] = None):
        """Record a timing metric."""
        self.histogram(f"{name}.timing", duration_ms, tags)
    
    def get_counter(self, name: str) -> float:
        """Get counter value."""
        return self._counters.get(name, 0)
    
    def get_gauge(self, name: str) -> float:
        """Get gauge value."""
        return self._gauges.get(name, 0)
    
    def get_histogram_stats(self, name: str) -> Dict:
        """Get histogram statistics."""
        values = self._histograms.get(name, [])
        if not values:
            return {"count": 0}
        
        sorted_values = sorted(values)
        count = len(sorted_values)
        
        return {
            "count": count,
            "min": sorted_values[0],
            "max": sorted_values[-1],
            "mean": sum(sorted_values) / count,
            "p50": sorted_values[int(count * 0.5)],
            "p95": sorted_values[int(count * 0.95)],
            "p99": sorted_values[int(count * 0.99)]
        }
    
    def get_all_metrics(self) -> Dict:
        """Get all metrics summary."""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    name: self.get_histogram_stats(name)
                    for name in self._histograms
                }
            }

# ============================================================================
# ALERTING
# ============================================================================

@dataclass
class Alert:
    """An alert."""
    id: str
    name: str
    severity: str  # info, warning, error, critical
    message: str
    device_id: Optional[str]
    timestamp: float
    acknowledged: bool = False
    acknowledged_at: Optional[float] = None
    metadata: Dict = field(default_factory=dict)

class AlertManager:
    """Manages alerts and notifications."""
    
    def __init__(self, max_alerts: int = 1000):
        self.max_alerts = max_alerts
        self._alerts: deque = deque(maxlen=max_alerts)
        self._handlers: List[Callable] = []
        self._lock = threading.RLock()
    
    def register_handler(self, handler: Callable):
        """Register an alert handler."""
        self._handlers.append(handler)
    
    def trigger(self, name: str, severity: str, message: str, 
                device_id: str = None, metadata: Dict = None) -> Alert:
        """Trigger a new alert."""
        alert = Alert(
            id=str(uuid.uuid4()) if 'uuid' in dir() else f"alert_{time.time()}",
            name=name,
            severity=severity,
            message=message,
            device_id=device_id,
            timestamp=time.time(),
            metadata=metadata or {}
        )
        
        with self._lock:
            self._alerts.append(alert)
        
        # Notify handlers
        for handler in self._handlers:
            try:
                handler(alert)
            except Exception as e:
                logging.error(f"Alert handler error: {e}")
        
        return alert
    
    def acknowledge(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        with self._lock:
            for alert in self._alerts:
                if alert.id == alert_id:
                    alert.acknowledged = True
                    alert.acknowledged_at = time.time()
                    return True
        return False
    
    def get_alerts(self, severity: str = None, device_id: str = None, 
                   acknowledged: bool = None, limit: int = 100) -> List[Alert]:
        """Get alerts filtered by criteria."""
        with self._lock:
            alerts = list(self._alerts)
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        if device_id:
            alerts = [a for a in alerts if a.device_id == device_id]
        if acknowledged is not None:
            alerts = [a for a in alerts if a.acknowledged == acknowledged]
        
        return alerts[-limit:]
    
    def get_unacknowledged_count(self) -> int:
        """Get count of unacknowledged alerts."""
        with self._lock:
            return sum(1 for a in self._alerts if not a.acknowledged)

# ============================================================================
# HEALTH CHECK
# ============================================================================

class HealthChecker:
    """System health checker."""
    
    def __init__(self):
        self._checks: Dict[str, Callable] = {}
        self._results: Dict[str, Dict] = {}
        self._lock = threading.RLock()
    
    def register_check(self, name: str, check_func: Callable[[], bool]):
        """Register a health check."""
        self._checks[name] = check_func
    
    async def run_checks(self) -> Dict:
        """Run all health checks."""
        results = {}
        
        for name, check_func in self._checks.items():
            try:
                if asyncio.iscoroutinefunction(check_func):
                    healthy = await check_func()
                else:
                    healthy = check_func()
                
                results[name] = {
                    "healthy": healthy,
                    "timestamp": time.time()
                }
            except Exception as e:
                results[name] = {
                    "healthy": False,
                    "error": str(e),
                    "timestamp": time.time()
                }
        
        with self._lock:
            self._results = results
        
        return results
    
    def get_status(self) -> Dict:
        """Get overall health status."""
        with self._lock:
            if not self._results:
                return {"status": "unknown", "checks": {}}
            
            all_healthy = all(r.get("healthy", False) for r in self._results.values())
            
            return {
                "status": "healthy" if all_healthy else "unhealthy",
                "checks": self._results
            }

# ============================================================================
# MONITORING DASHBOARD DATA
# ============================================================================

class MonitoringDashboard:
    """Provides data for monitoring dashboard."""
    
    def __init__(self):
        self.metrics = MetricsCollector()
        self.alerts = AlertManager()
        self.health = HealthChecker()
    
    def record_api_request(self, endpoint: str, method: str, status_code: int, duration_ms: float):
        """Record an API request metric."""
        self.metrics.increment(f"api.requests.{endpoint}")
        self.metrics.increment(f"api.status.{status_code}")
        self.metrics.timing(f"api.{endpoint}", duration_ms, {"method": method})
    
    def record_command(self, command: str, device_id: str, success: bool, duration_ms: float):
        """Record a command execution metric."""
        self.metrics.increment(f"commands.{command}.total")
        if success:
            self.metrics.increment(f"commands.{command}.success")
        else:
            self.metrics.increment(f"commands.{command}.failed")
        self.metrics.timing(f"commands.{command}", duration_ms, {"device_id": device_id})
    
    def record_device_heartbeat(self, device_id: str, battery: int, storage: float):
        """Record device health metrics."""
        self.metrics.gauge(f"device.{device_id}.battery", battery)
        self.metrics.gauge(f"device.{device_id}.storage_used", storage)
    
    def trigger_alert(self, name: str, severity: str, message: str, device_id: str = None):
        """Trigger an alert."""
        self.alerts.trigger(name, severity, message, device_id)
    
    def get_dashboard_data(self) -> Dict:
        """Get all monitoring data for dashboard."""
        return {
            "metrics": self.metrics.get_all_metrics(),
            "alerts": {
                "unacknowledged": self.alerts.get_unacknowledged_count(),
                "recent": [asdict(a) for a in self.alerts.get_alerts(limit=20)]
            },
            "health": self.health.get_status()
        }

# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

import asyncio
import uuid

logging_manager = LoggingManager()
metrics = MetricsCollector()
alerts = AlertManager()
health_checker = HealthChecker()
monitoring = MonitoringDashboard()

# Convenience function
def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance."""
    return logging_manager.get_logger(name)

# Decorator for timing functions
def timed(name: str = None):
    """Decorator to time function execution."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                return func(*args, **kwargs)
            finally:
                duration = (time.time() - start) * 1000
                metric_name = name or f"{func.__module__}.{func.__name__}"
                metrics.timing(metric_name, duration)
        return wrapper
    return decorator
