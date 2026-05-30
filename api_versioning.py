#!/usr/bin/env python3
"""
Abu-Zahra API Versioning System
Versioned API endpoints with backward compatibility and deprecation management.
"""

import os
import time
import logging
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from aiohttp import web

log = logging.getLogger("abu-zahra.api")

# ============================================================================
# API VERSIONS
# ============================================================================

API_VERSIONS = {
    "v1": {
        "version": "1.0.0",
        "released": "2024-01-01",
        "status": "stable",
        "deprecated": False,
        "sunset_date": None,
        "description": "Initial API version with core functionality"
    },
    "v2": {
        "version": "2.0.0",
        "released": "2025-01-01",
        "status": "current",
        "deprecated": False,
        "sunset_date": None,
        "description": "Enhanced API with WebSocket, features, and improved performance"
    }
}

CURRENT_VERSION = "v2"
DEFAULT_VERSION = "v1"
DEPRECATED_VERSIONS = []

# ============================================================================
# VERSION COMPARISON
# ============================================================================

def parse_version(version: str) -> Tuple[int, int, int]:
    """Parse version string to tuple."""
    parts = version.replace('v', '').split('.')
    return (
        int(parts[0]) if len(parts) > 0 else 0,
        int(parts[1]) if len(parts) > 1 else 0,
        int(parts[2]) if len(parts) > 2 else 0
    )

def compare_versions(v1: str, v2: str) -> int:
    """Compare two versions. Returns -1, 0, or 1."""
    t1 = parse_version(v1)
    t2 = parse_version(v2)
    
    if t1 < t2:
        return -1
    elif t1 > t2:
        return 1
    return 0

# ============================================================================
# API RESPONSE WRAPPER
# ============================================================================

@dataclass
class APIResponse:
    """Standardized API response."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    meta: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        response = {
            "success": self.success,
            "api_version": CURRENT_VERSION
        }
        
        if self.data is not None:
            response["data"] = self.data
        
        if self.error:
            response["error"] = self.error
            if self.error_code:
                response["error_code"] = self.error_code
        
        response["meta"] = {
            "timestamp": time.time(),
            **self.meta
        }
        
        return response

def api_response(data: Any = None, success: bool = True, error: str = None, 
                 error_code: str = None, **meta) -> Dict:
    """Create a standardized API response."""
    return APIResponse(
        success=success,
        data=data,
        error=error,
        error_code=error_code,
        meta=meta
    ).to_dict()

def api_error(error: str, error_code: str = None, status: int = 400, **meta) -> web.Response:
    """Create an error response."""
    return web.json_response(
        api_response(success=False, error=error, error_code=error_code, **meta),
        status=status
    )

def api_success(data: Any = None, **meta) -> web.Response:
    """Create a success response."""
    return web.json_response(
        api_response(success=True, data=data, **meta)
    )

# ============================================================================
# VERSION ROUTER
# ============================================================================

class VersionRouter:
    """Routes requests to versioned handlers."""
    
    def __init__(self):
        self._routes: Dict[str, Dict[str, Callable]] = {}
        self._deprecated: Dict[str, Dict[str, str]] = {}
        self._middlewares: List[Callable] = []
    
    def register(self, version: str, path: str, handler: Callable, 
                 methods: List[str] = None, deprecated: bool = False, 
                 deprecation_message: str = None):
        """Register a versioned route."""
        key = f"{path}:{':'.join(methods or ['GET'])}"
        
        if version not in self._routes:
            self._routes[version] = {}
        
        self._routes[version][key] = handler
        
        if deprecated:
            if version not in self._deprecated:
                self._deprecated[version] = {}
            self._deprecated[version][key] = deprecation_message or "This endpoint is deprecated"
        
        log.debug("Registered API route: %s %s (%s)", version, path, methods)
    
    def get_handler(self, version: str, path: str, method: str) -> Tuple[Optional[Callable], Optional[str]]:
        """Get handler for a versioned route."""
        key = f"{path}:{method}"
        
        # Check if version exists
        if version not in self._routes:
            return None, f"API version '{version}' not found"
        
        # Check if route exists in version
        if key not in self._routes[version]:
            # Try to fallback to earlier version
            for v in sorted(API_VERSIONS.keys(), reverse=True):
                if v in self._routes and key in self._routes[v]:
                    return self._routes[v][key], None
            return None, f"Route '{path}' not found in API version '{version}'"
        
        return self._routes[version][key], None
    
    def is_deprecated(self, version: str, path: str, method: str) -> Tuple[bool, Optional[str]]:
        """Check if a route is deprecated."""
        key = f"{path}:{method}"
        if version in self._deprecated and key in self._deprecated[version]:
            return True, self._deprecated[version][key]
        return False, None
    
    def add_middleware(self, middleware: Callable):
        """Add middleware for all versioned routes."""
        self._middlewares.append(middleware)
    
    def get_versions(self) -> Dict:
        """Get all API versions info."""
        return {
            "current": CURRENT_VERSION,
            "versions": API_VERSIONS,
            "deprecated": DEPRECATED_VERSIONS
        }


# Global router
version_router = VersionRouter()

# ============================================================================
# VERSION DECORATORS
# ============================================================================

def api_version(version: str, deprecated: bool = False, deprecation_message: str = None):
    """
    Decorator to mark a handler as versioned.
    
    Usage:
        @api_version("v2")
        async def get_devices_v2(request):
            return api_success({"devices": []})
    """
    def decorator(func):
        func._api_version = version
        func._deprecated = deprecated
        func._deprecation_message = deprecation_message
        
        @wraps(func)
        async def wrapper(request, *args, **kwargs):
            # Add deprecation header if applicable
            response = await func(request, *args, **kwargs)
            
            if deprecated and isinstance(response, web.Response):
                response.headers['X-API-Deprecated'] = 'true'
                if deprecation_message:
                    response.headers['X-API-Deprecation-Message'] = deprecation_message
            
            return response
        
        return wrapper
    return decorator

def versioned_route(path: str, methods: List[str] = None):
    """
    Decorator to register a versioned route.
    
    Usage:
        @versioned_route("/devices", ["GET"])
        @api_version("v1")
        async def get_devices(request):
            return api_success({"devices": []})
    """
    def decorator(func):
        version = getattr(func, '_api_version', DEFAULT_VERSION)
        deprecated = getattr(func, '_deprecated', False)
        deprecation_message = getattr(func, '_deprecation_message', None)
        
        version_router.register(
            version=version,
            path=path,
            handler=func,
            methods=methods,
            deprecated=deprecated,
            deprecation_message=deprecation_message
        )
        
        @wraps(func)
        async def wrapper(request, *args, **kwargs):
            return await func(request, *args, **kwargs)
        
        return wrapper
    return decorator

# ============================================================================
# VERSION EXTRACTION
# ============================================================================

def extract_version(request: web.Request) -> str:
    """Extract API version from request."""
    # Try path-based versioning first: /api/v1/devices
    path = request.path
    if path.startswith('/api/'):
        parts = path.split('/')
        if len(parts) >= 3 and parts[2].startswith('v'):
            return parts[2]
    
    # Try header-based versioning: X-API-Version: v1
    version = request.headers.get('X-API-Version')
    if version and version in API_VERSIONS:
        return version
    
    # Try query parameter: ?version=v1
    version = request.query.get('version')
    if version and version in API_VERSIONS:
        return version
    
    # Default version
    return DEFAULT_VERSION

def strip_version_from_path(path: str) -> str:
    """Remove version prefix from path."""
    if path.startswith('/api/v'):
        parts = path.split('/')
        if len(parts) >= 3 and parts[2].startswith('v'):
            return '/' + '/'.join(parts[3:])
    return path

# ============================================================================
# API MIDDLEWARE
# ============================================================================

@web.middleware
async def api_versioning_middleware(request: web.Request, handler):
    """Middleware to handle API versioning."""
    # Extract version
    version = extract_version(request)
    request['api_version'] = version
    
    # Check if version is deprecated
    if version in DEPRECATED_VERSIONS:
        log.warning("Deprecated API version used: %s", version)
    
    # Add version to response headers
    response = await handler(request)
    
    if isinstance(response, web.Response):
        response.headers['X-API-Version'] = version
        
        # Check for deprecated endpoint
        path = strip_version_from_path(request.path)
        is_deprecated, message = version_router.is_deprecated(version, path, request.method)
        
        if is_deprecated:
            response.headers['X-API-Deprecated'] = 'true'
            if message:
                response.headers['X-API-Deprecation-Message'] = message
    
    return response

@web.middleware
async def api_error_middleware(request: web.Request, handler):
    """Middleware for standardized error handling."""
    try:
        return await handler(request)
    except web.HTTPException as e:
        return web.json_response(
            api_response(
                success=False,
                error=e.reason or str(e),
                error_code=f"HTTP_{e.status}"
            ),
            status=e.status
        )
    except Exception as e:
        log.exception("Unhandled API error: %s", e)
        return web.json_response(
            api_response(
                success=False,
                error="Internal server error",
                error_code="INTERNAL_ERROR"
            ),
            status=500
        )

# ============================================================================
# API ROUTES
# ============================================================================

async def api_versions_handler(request: web.Request) -> web.Response:
    """Handler for /api/versions endpoint."""
    return api_success(version_router.get_versions())

async def api_health_handler(request: web.Request) -> web.Response:
    """Handler for /health endpoint."""
    return api_success({
        "status": "healthy",
        "version": CURRENT_VERSION,
        "uptime": time.time() - request.app.get('start_time', time.time())
    })

# ============================================================================
# API RESPONSE PAGINATION
# ============================================================================

def paginated_response(items: List, total: int, page: int = 1, 
                       per_page: int = 50, **meta) -> Dict:
    """Create a paginated API response."""
    total_pages = (total + per_page - 1) // per_page if per_page > 0 else 0
    
    return api_response(
        data={
            "items": items,
            "pagination": {
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
                "has_more": page < total_pages
            }
        },
        **meta
    )

# ============================================================================
# API REQUEST VALIDATION
# ============================================================================

def validate_request(schema: Dict):
    """
    Decorator to validate request against schema.
    
    Usage:
        @validate_request({
            "device_id": {"type": "string", "required": True},
            "command": {"type": "string", "required": True}
        })
        async def send_command(request):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(request, *args, **kwargs):
            try:
                data = await request.json()
            except:
                return api_error("Invalid JSON body", "INVALID_JSON", 400)
            
            errors = []
            
            for field, rules in schema.items():
                value = data.get(field)
                
                # Check required
                if rules.get("required") and value is None:
                    errors.append(f"Field '{field}' is required")
                    continue
                
                if value is not None:
                    # Check type
                    expected_type = rules.get("type")
                    if expected_type:
                        type_map = {
                            "string": str,
                            "integer": int,
                            "number": (int, float),
                            "boolean": bool,
                            "array": list,
                            "object": dict
                        }
                        if expected_type in type_map:
                            if not isinstance(value, type_map[expected_type]):
                                errors.append(f"Field '{field}' must be of type {expected_type}")
                    
                    # Check min/max
                    if "min" in rules and isinstance(value, (int, float)):
                        if value < rules["min"]:
                            errors.append(f"Field '{field}' must be >= {rules['min']}")
                    
                    if "max" in rules and isinstance(value, (int, float)):
                        if value > rules["max"]:
                            errors.append(f"Field '{field}' must be <= {rules['max']}")
                    
                    if "min_length" in rules and isinstance(value, str):
                        if len(value) < rules["min_length"]:
                            errors.append(f"Field '{field}' must have at least {rules['min_length']} characters")
                    
                    if "max_length" in rules and isinstance(value, str):
                        if len(value) > rules["max_length"]:
                            errors.append(f"Field '{field}' must have at most {rules['max_length']} characters")
                    
                    # Check enum
                    if "enum" in rules:
                        if value not in rules["enum"]:
                            errors.append(f"Field '{field}' must be one of: {rules['enum']}")
            
            if errors:
                return api_error(
                    error="Validation failed",
                    error_code="VALIDATION_ERROR",
                    status=400,
                    details=errors
                )
            
            request["validated_data"] = data
            return await func(request, *args, **kwargs)
        
        return wrapper
    return decorator

# ============================================================================
# RATE LIMITING
# ============================================================================

def rate_limit(requests_per_minute: int = 60, burst: int = 10):
    """
    Decorator to rate limit API endpoints.
    """
    from .security import RateLimiter
    
    limiter = RateLimiter(rate=requests_per_minute, burst=burst)
    
    def decorator(func):
        @wraps(func)
        async def wrapper(request, *args, **kwargs):
            # Get identifier (IP or user)
            identifier = request.remote or "unknown"
            
            allowed, info = limiter.check_rate(identifier)
            
            if not allowed:
                return web.json_response(
                    api_response(
                        success=False,
                        error="Rate limit exceeded",
                        error_code="RATE_LIMITED",
                        retry_after=info.get("reset_after", 60)
                    ),
                    status=429
                )
            
            response = await func(request, *args, **kwargs)
            
            # Add rate limit headers
            if isinstance(response, web.Response):
                response.headers['X-RateLimit-Limit'] = str(requests_per_minute)
                response.headers['X-RateLimit-Remaining'] = str(info.get("remaining", 0))
            
            return response
        
        return wrapper
    return decorator
