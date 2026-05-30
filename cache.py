#!/usr/bin/env python3
"""
Abu-Zahra Cache Layer
In-memory caching with TTL, LRU eviction, and device state caching.
"""

import time
import threading
import hashlib
import json
import asyncio
from collections import OrderedDict
from typing import Any, Optional, Dict, List, Callable
from functools import wraps
import logging

log = logging.getLogger("abu-zahra.cache")

# ============================================================================
# LRU CACHE WITH TTL
# ============================================================================

class LRUCache:
    """Thread-safe LRU cache with TTL support."""
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict = OrderedDict()
        self._lock = threading.RLock()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "expirations": 0
        }
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        with self._lock:
            if key not in self._cache:
                self._stats["misses"] += 1
                return None
            
            entry = self._cache[key]
            
            # Check expiration
            if entry["expires_at"] and time.time() > entry["expires_at"]:
                del self._cache[key]
                self._stats["expirations"] += 1
                self._stats["misses"] += 1
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._stats["hits"] += 1
            return entry["value"]
    
    def set(self, key: str, value: Any, ttl: int = None) -> None:
        """Set value in cache."""
        with self._lock:
            expires_at = None
            if ttl is not None or self.default_ttl > 0:
                expires_at = time.time() + (ttl or self.default_ttl)
            
            # Remove if exists (to update position)
            if key in self._cache:
                del self._cache[key]
            
            # Evict if at capacity
            while len(self._cache) >= self.max_size:
                oldest = next(iter(self._cache))
                del self._cache[oldest]
                self._stats["evictions"] += 1
            
            self._cache[key] = {
                "value": value,
                "expires_at": expires_at,
                "created_at": time.time()
            }
    
    def delete(self, key: str) -> bool:
        """Delete value from cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
    
    def cleanup_expired(self) -> int:
        """Remove all expired entries."""
        now = time.time()
        expired = 0
        with self._lock:
            keys_to_delete = [
                k for k, v in self._cache.items()
                if v["expires_at"] and now > v["expires_at"]
            ]
            for key in keys_to_delete:
                del self._cache[key]
                expired += 1
            self._stats["expirations"] += expired
        return expired
    
    def get_stats(self) -> Dict:
        """Get cache statistics."""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = self._stats["hits"] / total if total > 0 else 0
            return {
                **self._stats,
                "size": len(self._cache),
                "max_size": self.max_size,
                "hit_rate": round(hit_rate, 4)
            }

# ============================================================================
# DEVICE STATE CACHE
# ============================================================================

class DeviceStateCache:
    """Specialized cache for device state with shadow state support."""
    
    def __init__(self, ttl: int = 60):
        self._cache = LRUCache(max_size=500, default_ttl=ttl)
        self._shadow_state: Dict[str, Dict] = {}
        self._lock = threading.RLock()
    
    def update_device_state(self, device_id: str, state: Dict) -> None:
        """Update device state in cache."""
        self._cache.set(f"device:{device_id}:state", state, ttl=60)
        
        # Update shadow state
        with self._lock:
            if device_id not in self._shadow_state:
                self._shadow_state[device_id] = {}
            self._shadow_state[device_id].update(state)
            self._shadow_state[device_id]["last_updated"] = time.time()
    
    def get_device_state(self, device_id: str) -> Optional[Dict]:
        """Get device state from cache."""
        cached = self._cache.get(f"device:{device_id}:state")
        if cached:
            return cached
        
        # Fallback to shadow state
        with self._lock:
            return self._shadow_state.get(device_id)
    
    def get_shadow_state(self, device_id: str) -> Optional[Dict]:
        """Get the last known (shadow) state of a device."""
        with self._lock:
            return self._shadow_state.get(device_id)
    
    def set_shadow_state(self, device_id: str, state: Dict) -> None:
        """Set the shadow state for a device."""
        with self._lock:
            self._shadow_state[device_id] = {
                **state,
                "last_updated": time.time()
            }
    
    def clear_device(self, device_id: str) -> None:
        """Clear all cached data for a device."""
        self._cache.delete(f"device:{device_id}:state")
        with self._lock:
            self._shadow_state.pop(device_id, None)

# ============================================================================
# RESPONSE CACHE
# ============================================================================

class ResponseCache:
    """Cache for API responses."""
    
    def __init__(self):
        self._cache = LRUCache(max_size=2000, default_ttl=120)
    
    def get_or_set(self, key: str, factory: Callable[[], Any], ttl: int = None) -> Any:
        """Get from cache or compute and cache."""
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        
        value = factory()
        self._cache.set(key, value, ttl)
        return value
    
    async def get_or_set_async(self, key: str, factory: Callable[[], Any], ttl: int = None) -> Any:
        """Async version of get_or_set."""
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        
        if asyncio.iscoroutinefunction(factory):
            value = await factory()
        else:
            value = factory()
        
        self._cache.set(key, value, ttl)
        return value
    
    def invalidate(self, pattern: str = None) -> int:
        """Invalidate cache entries matching pattern."""
        if pattern is None:
            self._cache.clear()
            return -1
        
        # Simple prefix matching
        count = 0
        for key in list(self._cache._cache.keys()):
            if key.startswith(pattern):
                self._cache.delete(key)
                count += 1
        return count

# ============================================================================
# COMMAND CACHE
# ============================================================================

class CommandCache:
    """Cache for pending commands."""
    
    def __init__(self):
        self._pending: Dict[str, List[Dict]] = {}
        self._lock = threading.RLock()
    
    def add_pending(self, device_id: str, command: Dict) -> None:
        """Add a pending command to cache."""
        with self._lock:
            if device_id not in self._pending:
                self._pending[device_id] = []
            self._pending[device_id].append(command)
    
    def get_pending(self, device_id: str) -> List[Dict]:
        """Get pending commands for a device."""
        with self._lock:
            return list(self._pending.get(device_id, []))
    
    def remove_pending(self, device_id: str, command_id: str) -> bool:
        """Remove a pending command."""
        with self._lock:
            if device_id in self._pending:
                self._pending[device_id] = [
                    c for c in self._pending[device_id]
                    if c.get("id") != command_id
                ]
                return True
            return False
    
    def clear_device(self, device_id: str) -> None:
        """Clear all pending commands for a device."""
        with self._lock:
            self._pending.pop(device_id, None)

# ============================================================================
# CACHE DECORATOR
# ============================================================================

def cached(ttl: int = 300, key_prefix: str = ""):
    """Decorator for caching function results."""
    _cache = LRUCache(max_size=500, default_ttl=ttl)
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            key_data = f"{key_prefix}:{func.__name__}:{args}:{sorted(kwargs.items())}"
            key = hashlib.md5(key_data.encode()).hexdigest()
            
            cached_result = _cache.get(key)
            if cached_result is not None:
                return cached_result
            
            result = func(*args, **kwargs)
            _cache.set(key, result)
            return result
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            key_data = f"{key_prefix}:{func.__name__}:{args}:{sorted(kwargs.items())}"
            key = hashlib.md5(key_data.encode()).hexdigest()
            
            cached_result = _cache.get(key)
            if cached_result is not None:
                return cached_result
            
            result = await func(*args, **kwargs)
            _cache.set(key, result)
            return result
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper
    
    return decorator

# ============================================================================
# GLOBAL CACHE INSTANCES
# ============================================================================

# General purpose cache
memory_cache = LRUCache(max_size=5000, default_ttl=300)

# Device state cache
device_cache = DeviceStateCache(ttl=60)

# API response cache
response_cache = ResponseCache()

# Command cache
command_cache = CommandCache()

# ============================================================================
# CACHE MANAGER
# ============================================================================

class CacheManager:
    """Centralized cache management."""
    
    @staticmethod
    def get_stats() -> Dict:
        """Get statistics for all caches."""
        return {
            "memory_cache": memory_cache.get_stats(),
            "device_cache_size": len(device_cache._shadow_state),
            "pending_commands": sum(len(cmds) for cmds in command_cache._pending.values())
        }
    
    @staticmethod
    def cleanup_all() -> Dict:
        """Cleanup all caches."""
        return {
            "expired_entries": memory_cache.cleanup_expired(),
            "timestamp": time.time()
        }
    
    @staticmethod
    def clear_all() -> None:
        """Clear all caches."""
        memory_cache.clear()
        device_cache._shadow_state.clear()
        command_cache._pending.clear()
        log.info("All caches cleared")

# ============================================================================
# BACKGROUND CLEANUP TASK
# ============================================================================

async def cache_cleanup_task(interval: int = 60):
    """Background task to cleanup expired cache entries."""
    while True:
        try:
            expired = memory_cache.cleanup_expired()
            if expired > 0:
                log.debug("Cleaned up %d expired cache entries", expired)
        except Exception as e:
            log.error("Cache cleanup error: %s", e)
        
        await asyncio.sleep(interval)
