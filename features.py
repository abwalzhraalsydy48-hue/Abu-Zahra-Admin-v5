#!/usr/bin/env python3
"""
Abu-Zahra Feature Toggle System
Runtime feature flags with conditions and gradual rollout.
"""

import os
import json
import time
import threading
import hashlib
import logging
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
from enum import Enum

log = logging.getLogger("abu-zahra.features")

# ============================================================================
# CONFIGURATION
# ============================================================================

DATA_DIR = Path(__file__).parent / "data"
FEATURE_FLAGS_FILE = DATA_DIR / "feature_flags.json"

# ============================================================================
# FEATURE CONDITION TYPES
# ============================================================================

class ConditionType(Enum):
    ALWAYS = "always"
    NEVER = "never"
    PERCENTAGE = "percentage"
    DEVICES = "devices"
    USERS = "users"
    TIME_RANGE = "time_range"
    ENVIRONMENT = "environment"
    CUSTOM = "custom"


@dataclass
class FeatureCondition:
    """Condition for feature flag evaluation."""
    type: str
    value: Any = None
    
    def evaluate(self, context: Dict) -> bool:
        """Evaluate condition against context."""
        if self.type == ConditionType.ALWAYS.value:
            return True
        
        elif self.type == ConditionType.NEVER.value:
            return False
        
        elif self.type == ConditionType.PERCENTAGE.value:
            # Rollout percentage (0-100)
            percentage = int(self.value) if self.value else 0
            if percentage >= 100:
                return True
            if percentage <= 0:
                return False
            
            # Hash-based consistent assignment
            key = context.get("device_id", context.get("user_id", str(time.time())))
            hash_val = int(hashlib.md5(f"{key}".encode()).hexdigest()[:8], 16)
            return (hash_val % 100) < percentage
        
        elif self.type == ConditionType.DEVICES.value:
            # Specific device IDs
            device_ids = self.value if isinstance(self.value, list) else []
            return context.get("device_id") in device_ids
        
        elif self.type == ConditionType.USERS.value:
            # Specific user IDs
            user_ids = self.value if isinstance(self.value, list) else []
            return context.get("user_id") in user_ids
        
        elif self.type == ConditionType.TIME_RANGE.value:
            # Time-based activation
            time_config = self.value if isinstance(self.value, dict) else {}
            now = time.time()
            
            start_time = time_config.get("start")
            end_time = time_config.get("end")
            
            if start_time and now < start_time:
                return False
            if end_time and now > end_time:
                return False
            return True
        
        elif self.type == ConditionType.ENVIRONMENT.value:
            # Environment-based
            environments = self.value if isinstance(self.value, list) else []
            current_env = os.environ.get("ENVIRONMENT", "development")
            return current_env in environments
        
        return False


@dataclass
class FeatureFlag:
    """A feature flag definition."""
    name: str
    enabled: bool = False
    description: str = ""
    conditions: List[Dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    created_by: str = ""
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "description": self.description,
            "conditions": self.conditions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'FeatureFlag':
        return cls(
            name=data["name"],
            enabled=data.get("enabled", False),
            description=data.get("description", ""),
            conditions=data.get("conditions", []),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            created_by=data.get("created_by", ""),
            metadata=data.get("metadata", {})
        )
    
    def is_active(self, context: Dict = None) -> bool:
        """Check if feature is active for given context."""
        if not self.enabled:
            return False
        
        if not self.conditions:
            return True
        
        context = context or {}
        
        # All conditions must pass (AND logic)
        for cond_data in self.conditions:
            condition = FeatureCondition(
                type=cond_data.get("type"),
                value=cond_data.get("value")
            )
            if not condition.evaluate(context):
                return False
        
        return True


# ============================================================================
# FEATURE FLAG MANAGER
# ============================================================================

class FeatureFlagManager:
    """Manages feature flags with persistence and caching."""
    
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
        
        self._flags: Dict[str, FeatureFlag] = {}
        self._cache: Dict[str, bool] = {}
        self._cache_ttl = 60  # seconds
        self._last_cache_update = 0
        self._watchers: List[Callable] = []
        self._lock = threading.RLock()
        
        self._load_flags()
        self._initialized = True
        
        log.info("Feature flag manager initialized with %d flags", len(self._flags))
    
    def _load_flags(self):
        """Load flags from file."""
        if FEATURE_FLAGS_FILE.exists():
            try:
                with open(FEATURE_FLAGS_FILE, 'r') as f:
                    data = json.load(f)
                    for name, flag_data in data.items():
                        self._flags[name] = FeatureFlag.from_dict(flag_data)
            except Exception as e:
                log.error("Failed to load feature flags: %s", e)
        
        # Initialize default flags
        self._init_default_flags()
    
    def _init_default_flags(self):
        """Initialize default feature flags."""
        defaults = [
            ("websocket_realtime", True, "Enable real-time WebSocket updates"),
            ("location_tracking", True, "Enable continuous location tracking"),
            ("auto_backup", False, "Enable automatic device backups"),
            ("push_notifications", True, "Enable push notifications"),
            ("analytics", True, "Enable usage analytics"),
            ("beta_features", False, "Enable beta features"),
            ("api_v2", True, "Enable API v2 endpoints"),
            ("encrypted_commands", True, "Enable encrypted command transport"),
            ("media_streaming", True, "Enable media streaming"),
            ("dark_mode", True, "Enable dark mode support"),
            ("command_cancellation", True, "Enable command cancellation"),
            ("batch_operations", True, "Enable batch device operations"),
            ("audit_logging", True, "Enable detailed audit logging"),
            ("rate_limiting", True, "Enable API rate limiting"),
            ("geo_fencing", False, "Enable geo-fencing features"),
            ("scheduled_commands", True, "Enable scheduled commands"),
            ("command_templates", True, "Enable command templates"),
        ]
        
        for name, enabled, description in defaults:
            if name not in self._flags:
                self._flags[name] = FeatureFlag(
                    name=name,
                    enabled=enabled,
                    description=description
                )
        
        self._save_flags()
    
    def _save_flags(self):
        """Save flags to file."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            data = {name: flag.to_dict() for name, flag in self._flags.items()}
            with open(FEATURE_FLAGS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.error("Failed to save feature flags: %s", e)
    
    def get_flag(self, name: str) -> Optional[FeatureFlag]:
        """Get a feature flag by name."""
        with self._lock:
            return self._flags.get(name)
    
    def is_enabled(self, name: str, context: Dict = None) -> bool:
        """Check if a feature is enabled."""
        with self._lock:
            flag = self._flags.get(name)
            if not flag:
                log.warning("Unknown feature flag: %s", name)
                return False
            
            return flag.is_active(context)
    
    def is_enabled_for_device(self, name: str, device_id: str) -> bool:
        """Check if a feature is enabled for a specific device."""
        return self.is_enabled(name, {"device_id": device_id})
    
    def is_enabled_for_user(self, name: str, user_id: str) -> bool:
        """Check if a feature is enabled for a specific user."""
        return self.is_enabled(name, {"user_id": user_id})
    
    def set_flag(self, name: str, enabled: bool, description: str = None) -> FeatureFlag:
        """Set a feature flag's enabled state."""
        with self._lock:
            flag = self._flags.get(name)
            if flag:
                flag.enabled = enabled
                flag.updated_at = time.time()
                if description:
                    flag.description = description
            else:
                flag = FeatureFlag(
                    name=name,
                    enabled=enabled,
                    description=description or ""
                )
                self._flags[name] = flag
            
            self._save_flags()
            self._notify_watchers(name, flag)
            
            log.info("Feature flag '%s' set to %s", name, enabled)
            return flag
    
    def set_conditions(self, name: str, conditions: List[Dict]) -> bool:
        """Set conditions for a feature flag."""
        with self._lock:
            flag = self._flags.get(name)
            if not flag:
                return False
            
            flag.conditions = conditions
            flag.updated_at = time.time()
            self._save_flags()
            self._notify_watchers(name, flag)
            
            log.info("Conditions updated for feature '%s'", name)
            return True
    
    def set_rollout_percentage(self, name: str, percentage: int) -> bool:
        """Set rollout percentage for a feature flag."""
        return self.set_conditions(name, [
            {"type": ConditionType.PERCENTAGE.value, "value": percentage}
        ])
    
    def enable_for_devices(self, name: str, device_ids: List[str]) -> bool:
        """Enable a feature for specific devices."""
        return self.set_conditions(name, [
            {"type": ConditionType.DEVICES.value, "value": device_ids}
        ])
    
    def enable_for_users(self, name: str, user_ids: List[str]) -> bool:
        """Enable a feature for specific users."""
        return self.set_conditions(name, [
            {"type": ConditionType.USERS.value, "value": user_ids}
        ])
    
    def delete_flag(self, name: str) -> bool:
        """Delete a feature flag."""
        with self._lock:
            if name in self._flags:
                del self._flags[name]
                self._save_flags()
                log.info("Feature flag '%s' deleted", name)
                return True
            return False
    
    def get_all_flags(self) -> Dict[str, FeatureFlag]:
        """Get all feature flags."""
        with self._lock:
            return dict(self._flags)
    
    def get_enabled_flags(self) -> List[str]:
        """Get list of enabled feature flags."""
        with self._lock:
            return [name for name, flag in self._flags.items() if flag.enabled]
    
    def get_flags_for_device(self, device_id: str) -> Dict[str, bool]:
        """Get all flag states for a device."""
        with self._lock:
            return {
                name: flag.is_active({"device_id": device_id})
                for name, flag in self._flags.items()
            }
    
    def add_watcher(self, callback: Callable):
        """Add a callback to be notified of flag changes."""
        self._watchers.append(callback)
    
    def _notify_watchers(self, name: str, flag: FeatureFlag):
        """Notify watchers of flag change."""
        for watcher in self._watchers:
            try:
                watcher(name, flag)
            except Exception as e:
                log.error("Feature flag watcher error: %s", e)
    
    def export_flags(self) -> str:
        """Export flags as JSON string."""
        with self._lock:
            data = {name: flag.to_dict() for name, flag in self._flags.items()}
            return json.dumps(data, indent=2)
    
    def import_flags(self, json_data: str, merge: bool = True) -> int:
        """Import flags from JSON string."""
        try:
            data = json.loads(json_data)
            count = 0
            
            with self._lock:
                for name, flag_data in data.items():
                    if merge and name in self._flags:
                        # Update existing flag
                        existing = self._flags[name]
                        existing.enabled = flag_data.get("enabled", existing.enabled)
                        existing.conditions = flag_data.get("conditions", existing.conditions)
                        existing.updated_at = time.time()
                    else:
                        # Create new flag
                        self._flags[name] = FeatureFlag.from_dict(flag_data)
                    count += 1
                
                self._save_flags()
            
            log.info("Imported %d feature flags", count)
            return count
            
        except Exception as e:
            log.error("Failed to import feature flags: %s", e)
            return 0


# ============================================================================
# FEATURE FLAG DECORATOR
# ============================================================================

def feature_flag(name: str, fallback: Any = None):
    """
    Decorator to gate function execution on feature flag.
    
    Usage:
        @feature_flag("beta_features", fallback="Feature not available")
        async def beta_function():
            return "Beta feature!"
    """
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if features.is_enabled(name):
                return await func(*args, **kwargs)
            if callable(fallback):
                return fallback(*args, **kwargs)
            return fallback
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if features.is_enabled(name):
                return func(*args, **kwargs)
            if callable(fallback):
                return fallback(*args, **kwargs)
            return fallback
        
        import functools
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

features = FeatureFlagManager()


# ============================================================================
# API HELPERS
# ============================================================================

def get_feature_flags_api() -> Dict:
    """Get all feature flags for API response."""
    return {
        "flags": {
            name: {
                "enabled": flag.enabled,
                "description": flag.description,
                "conditions": flag.conditions
            }
            for name, flag in features.get_all_flags().items()
        },
        "count": len(features.get_all_flags()),
        "enabled_count": len(features.get_enabled_flags())
    }


def set_feature_flag_api(name: str, enabled: bool, conditions: List[Dict] = None) -> Dict:
    """Set a feature flag via API."""
    flag = features.set_flag(name, enabled)
    
    if conditions:
        features.set_conditions(name, conditions)
        flag = features.get_flag(name)
    
    return {
        "success": True,
        "flag": flag.to_dict() if flag else None
    }
