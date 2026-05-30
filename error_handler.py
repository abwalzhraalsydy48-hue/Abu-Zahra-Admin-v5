#!/usr/bin/env python3
"""
Abu-Zahra Error Handling System
Global exception handling, error recovery, and fault tolerance.
"""

import sys
import time
import json
import traceback
import asyncio
import threading
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
import logging
from datetime import datetime

log = logging.getLogger("abu-zahra.error")

# ============================================================================
# ERROR TYPES
# ============================================================================

class ErrorSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ErrorCategory(Enum):
    NETWORK = "network"
    DATABASE = "database"
    DEVICE = "device"
    COMMAND = "command"
    PERMISSION = "permission"
    VALIDATION = "validation"
    SYSTEM = "system"
    EXTERNAL = "external"

# ============================================================================
# ERROR MODEL
# ============================================================================

@dataclass
class ErrorRecord:
    """Record of an error occurrence."""
    id: str
    error_type: str
    message: str
    category: str
    severity: str
    timestamp: float
    device_id: Optional[str] = None
    command_id: Optional[str] = None
    stack_trace: Optional[str] = None
    context: Dict = field(default_factory=dict)
    handled: bool = False
    retry_count: int = 0
    resolved: bool = False
    resolved_at: Optional[float] = None

# ============================================================================
# CUSTOM EXCEPTIONS
# ============================================================================

class AbuZahraError(Exception):
    """Base exception for Abu-Zahra system."""
    
    def __init__(self, message: str, category: str = ErrorCategory.SYSTEM.value, 
                 severity: str = ErrorSeverity.MEDIUM.value, **kwargs):
        super().__init__(message)
        self.message = message
        self.category = category
        self.severity = severity
        self.context = kwargs

class DeviceNotFoundError(AbuZahraError):
    """Device not found in registry."""
    
    def __init__(self, device_id: str):
        super().__init__(
            f"Device not found: {device_id}",
            category=ErrorCategory.DEVICE.value,
            severity=ErrorSeverity.MEDIUM.value,
            device_id=device_id
        )

class CommandError(AbuZahraError):
    """Command execution error."""
    
    def __init__(self, message: str, command: str = None, device_id: str = None):
        super().__init__(
            message,
            category=ErrorCategory.COMMAND.value,
            severity=ErrorSeverity.MEDIUM.value,
            command=command,
            device_id=device_id
        )

class PermissionDeniedError(AbuZahraError):
    """Permission denied error."""
    
    def __init__(self, permission: str, device_id: str = None):
        super().__init__(
            f"Permission denied: {permission}",
            category=ErrorCategory.PERMISSION.value,
            severity=ErrorSeverity.HIGH.value,
            permission=permission,
            device_id=device_id
        )

class ValidationError(AbuZahraError):
    """Validation error."""
    
    def __init__(self, message: str, field: str = None, value: Any = None):
        super().__init__(
            message,
            category=ErrorCategory.VALIDATION.value,
            severity=ErrorSeverity.LOW.value,
            field=field,
            value=str(value) if value else None
        )

class NetworkError(AbuZahraError):
    """Network communication error."""
    
    def __init__(self, message: str, endpoint: str = None):
        super().__init__(
            message,
            category=ErrorCategory.NETWORK.value,
            severity=ErrorSeverity.HIGH.value,
            endpoint=endpoint
        )

class DatabaseError(AbuZahraError):
    """Database operation error."""
    
    def __init__(self, message: str, operation: str = None):
        super().__init__(
            message,
            category=ErrorCategory.DATABASE.value,
            severity=ErrorSeverity.HIGH.value,
            operation=operation
        )

class RateLimitError(AbuZahraError):
    """Rate limit exceeded error."""
    
    def __init__(self, retry_after: float = 60):
        super().__init__(
            f"Rate limit exceeded. Retry after {retry_after} seconds",
            category=ErrorCategory.SYSTEM.value,
            severity=ErrorSeverity.LOW.value,
            retry_after=retry_after
        )

# ============================================================================
# ERROR HANDLER
# ============================================================================

class ErrorHandler:
    """Centralized error handling."""
    
    def __init__(self, max_errors: int = 1000):
        self.max_errors = max_errors
        self._errors: List[ErrorRecord] = []
        self._handlers: Dict[str, Callable] = {}
        self._lock = threading.RLock()
        self._stats = {
            "total_errors": 0,
            "by_category": {},
            "by_severity": {}
        }
    
    def register_handler(self, error_type: str, handler: Callable):
        """Register a handler for a specific error type."""
        self._handlers[error_type] = handler
    
    def handle(self, error: Exception, context: Dict = None) -> ErrorRecord:
        """Handle an exception and create error record."""
        import uuid
        
        # Determine error details
        if isinstance(error, AbuZahraError):
            error_type = type(error).__name__
            message = error.message
            category = error.category
            severity = error.severity
            extra_context = error.context
        else:
            error_type = type(error).__name__
            message = str(error)
            category = ErrorCategory.SYSTEM.value
            severity = ErrorSeverity.MEDIUM.value
            extra_context = {}
        
        # Create error record
        record = ErrorRecord(
            id=str(uuid.uuid4()),
            error_type=error_type,
            message=message,
            category=category,
            severity=severity,
            timestamp=time.time(),
            stack_trace=traceback.format_exc(),
            context={**(context or {}), **extra_context}
        )
        
        # Extract device_id and command_id from context
        record.device_id = record.context.get("device_id")
        record.command_id = record.context.get("command_id")
        
        # Store error
        with self._lock:
            self._errors.append(record)
            if len(self._errors) > self.max_errors:
                self._errors = self._errors[-self.max_errors:]
            
            # Update stats
            self._stats["total_errors"] += 1
            self._stats["by_category"][category] = self._stats["by_category"].get(category, 0) + 1
            self._stats["by_severity"][severity] = self._stats["by_severity"].get(severity, 0) + 1
        
        # Log error
        if severity == ErrorSeverity.CRITICAL.value:
            log.critical("[%s] %s - %s", error_type, message, record.context)
        elif severity == ErrorSeverity.HIGH.value:
            log.error("[%s] %s - %s", error_type, message, record.context)
        elif severity == ErrorSeverity.MEDIUM.value:
            log.warning("[%s] %s", error_type, message)
        else:
            log.info("[%s] %s", error_type, message)
        
        # Call registered handler
        handler = self._handlers.get(error_type)
        if handler:
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(record))
                else:
                    handler(record)
                record.handled = True
            except Exception as e:
                log.error("Error handler failed: %s", e)
        
        return record
    
    def get_errors(self, category: str = None, severity: str = None, 
                   device_id: str = None, limit: int = 100) -> List[ErrorRecord]:
        """Get errors filtered by criteria."""
        with self._lock:
            errors = list(self._errors)
        
        if category:
            errors = [e for e in errors if e.category == category]
        if severity:
            errors = [e for e in errors if e.severity == severity]
        if device_id:
            errors = [e for e in errors if e.device_id == device_id]
        
        return errors[-limit:]
    
    def get_stats(self) -> Dict:
        """Get error statistics."""
        with self._lock:
            return {
                **self._stats,
                "recent_unresolved": sum(1 for e in self._errors if not e.resolved)
            }
    
    def resolve_error(self, error_id: str) -> bool:
        """Mark an error as resolved."""
        with self._lock:
            for error in self._errors:
                if error.id == error_id:
                    error.resolved = True
                    error.resolved_at = time.time()
                    return True
            return False
    
    def cleanup_resolved(self, max_age_hours: int = 24) -> int:
        """Clean up resolved errors."""
        cutoff = time.time() - (max_age_hours * 3600)
        with self._lock:
            initial_count = len(self._errors)
            self._errors = [
                e for e in self._errors 
                if not e.resolved or e.resolved_at > cutoff
            ]
            return initial_count - len(self._errors)

# ============================================================================
# RETRY MECHANISM
# ============================================================================

def with_retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0,
               exceptions: tuple = (Exception,)):
    """Decorator for retry logic with exponential backoff."""
    
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        log.warning("Retry %d/%d for %s: %s", 
                                   attempt + 1, max_attempts, func.__name__, e)
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
            
            raise last_exception
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        log.warning("Retry %d/%d for %s: %s",
                                   attempt + 1, max_attempts, func.__name__, e)
                        time.sleep(current_delay)
                        current_delay *= backoff
            
            raise last_exception
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator

# ============================================================================
# CIRCUIT BREAKER
# ============================================================================

class CircuitBreaker:
    """Circuit breaker for fault tolerance."""
    
    STATE_CLOSED = "closed"
    STATE_OPEN = "open"
    STATE_HALF_OPEN = "half_open"
    
    def __init__(self, name: str, failure_threshold: int = 5, 
                 recovery_timeout: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = self.STATE_CLOSED
        self._failure_count = 0
        self._last_failure_time = 0
        self._lock = threading.RLock()
    
    def is_available(self) -> bool:
        """Check if circuit is available."""
        with self._lock:
            if self._state == self.STATE_CLOSED:
                return True
            
            if self._state == self.STATE_OPEN:
                # Check if recovery timeout has passed
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = self.STATE_HALF_OPEN
                    log.info("Circuit breaker '%s' entering half-open state", self.name)
                    return True
                return False
            
            # Half-open: allow one request
            return True
    
    def record_success(self):
        """Record a successful operation."""
        with self._lock:
            if self._state == self.STATE_HALF_OPEN:
                self._state = self.STATE_CLOSED
                self._failure_count = 0
                log.info("Circuit breaker '%s' recovered", self.name)
    
    def record_failure(self):
        """Record a failed operation."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == self.STATE_HALF_OPEN:
                self._state = self.STATE_OPEN
                log.warning("Circuit breaker '%s' reopened after failure in half-open", self.name)
            elif self._failure_count >= self.failure_threshold:
                self._state = self.STATE_OPEN
                log.warning("Circuit breaker '%s' opened after %d failures", 
                           self.name, self._failure_count)
    
    def get_state(self) -> Dict:
        """Get circuit breaker state."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state,
                "failure_count": self._failure_count,
                "last_failure_time": self._last_failure_time
            }

# ============================================================================
# GLOBAL ERROR HANDLER
# ============================================================================

error_handler = ErrorHandler()

# Circuit breakers for different services
circuit_breakers = {
    "firebase": CircuitBreaker("firebase", failure_threshold=5, recovery_timeout=60),
    "telegram": CircuitBreaker("telegram", failure_threshold=3, recovery_timeout=30),
    "device_api": CircuitBreaker("device_api", failure_threshold=10, recovery_timeout=30),
}

def handle_exception(exc_type, exc_value, exc_traceback):
    """Global exception handler."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    error = exc_value
    context = {
        "source": "unhandled_exception",
        "traceback": ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    }
    
    error_handler.handle(error, context)

# Install global exception handler
sys.excepthook = handle_exception

# ============================================================================
# DECORATORS
# ============================================================================

def safe_execute(default_return=None):
    """Decorator to safely execute a function and handle errors."""
    
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                error_handler.handle(e, {"function": func.__name__})
                return default_return
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_handler.handle(e, {"function": func.__name__})
                return default_return
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator

def with_circuit_breaker(breaker_name: str):
    """Decorator to use circuit breaker."""
    
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            breaker = circuit_breakers.get(breaker_name)
            if breaker and not breaker.is_available():
                raise NetworkError(f"Circuit breaker '{breaker_name}' is open")
            
            try:
                result = await func(*args, **kwargs)
                if breaker:
                    breaker.record_success()
                return result
            except Exception as e:
                if breaker:
                    breaker.record_failure()
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            breaker = circuit_breakers.get(breaker_name)
            if breaker and not breaker.is_available():
                raise NetworkError(f"Circuit breaker '{breaker_name}' is open")
            
            try:
                result = func(*args, **kwargs)
                if breaker:
                    breaker.record_success()
                return result
            except Exception as e:
                if breaker:
                    breaker.record_failure()
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator
