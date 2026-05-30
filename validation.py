#!/usr/bin/env python3
"""
Abu-Zahra API Validation Layer
Pydantic schemas for request/response validation.
"""

import re
import json
from typing import Dict, List, Optional, Any, Union, Literal
from dataclasses import dataclass, field
from enum import Enum
import logging

log = logging.getLogger("abu-zahra.validation")

# ============================================================================
# VALIDATION RESULT
# ============================================================================

@dataclass
class ValidationResult:
    """Result of validation."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    data: Dict = field(default_factory=dict)
    
    def add_error(self, field: str, message: str):
        self.valid = False
        self.errors.append(f"{field}: {message}")

# ============================================================================
# BASE VALIDATOR
# ============================================================================

class Validator:
    """Base validator class."""
    
    @staticmethod
    def validate_required(value: Any, field_name: str) -> Optional[str]:
        """Validate required field."""
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return f"الحقل '{field_name}' مطلوب"
        return None
    
    @staticmethod
    def validate_string(value: Any, min_len: int = None, max_len: int = None, pattern: str = None) -> Optional[str]:
        """Validate string field."""
        if not isinstance(value, str):
            return "يجب أن يكون نصاً"
        
        if min_len is not None and len(value) < min_len:
            return f"يجب أن يكون على الأقل {min_len} حرفاً"
        
        if max_len is not None and len(value) > max_len:
            return f"يجب ألا يتجاوز {max_len} حرفاً"
        
        if pattern and not re.match(pattern, value):
            return "الصيغة غير صحيحة"
        
        return None
    
    @staticmethod
    def validate_number(value: Any, min_val: float = None, max_val: float = None) -> Optional[str]:
        """Validate numeric field."""
        try:
            num = float(value)
        except (TypeError, ValueError):
            return "يجب أن يكون رقماً"
        
        if min_val is not None and num < min_val:
            return f"يجب أن يكون أكبر من أو يساوي {min_val}"
        
        if max_val is not None and num > max_val:
            return f"يجب أن يكون أصغر من أو يساوي {max_val}"
        
        return None
    
    @staticmethod
    def validate_integer(value: Any, min_val: int = None, max_val: int = None) -> Optional[str]:
        """Validate integer field."""
        try:
            num = int(value)
        except (TypeError, ValueError):
            return "يجب أن يكون رقماً صحيحاً"
        
        if min_val is not None and num < min_val:
            return f"يجب أن يكون أكبر من أو يساوي {min_val}"
        
        if max_val is not None and num > max_val:
            return f"يجب أن يكون أصغر من أو يساوي {max_val}"
        
        return None
    
    @staticmethod
    def validate_url(value: str) -> Optional[str]:
        """Validate URL."""
        if not value.startswith(("http://", "https://")):
            return "يجب أن يكون رابطاً صالحاً (http:// أو https://)"
        
        url_pattern = r'^https?://[^\s/$.?#].[^\s]*$'
        if not re.match(url_pattern, value):
            return "صيغة الرابط غير صحيحة"
        
        return None
    
    @staticmethod
    def validate_phone(value: str) -> Optional[str]:
        """Validate phone number."""
        # Clean the number
        clean = re.sub(r'[\s\-\(\)]', '', value)
        
        if not clean.startswith('+'):
            clean = '+' + clean
        
        if not re.match(r'^\+\d{8,15}$', clean):
            return "رقم الهاتف غير صحيح (يجب أن يكون بصيغة دولية)"
        
        return None
    
    @staticmethod
    def validate_email(value: str) -> Optional[str]:
        """Validate email address."""
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, value):
            return "البريد الإلكتروني غير صحيح"
        return None
    
    @staticmethod
    def validate_enum(value: Any, allowed: List[Any]) -> Optional[str]:
        """Validate enum value."""
        if value not in allowed:
            return f"يجب أن يكون أحد: {', '.join(str(a) for a in allowed)}"
        return None

# ============================================================================
# SCHEMA DEFINITIONS
# ============================================================================

class CommandSchema:
    """Schema for command validation."""
    
    # Valid command names
    VALID_COMMANDS = [
        # Data collection
        "get_sms", "get_calls", "get_contacts", "get_location", "get_notifications",
        "get_apps", "get_info", "get_battery", "get_gallery", "get_clipboard",
        "get_wifi_info", "get_network_info", "get_sim_info", "get_storage_info",
        "get_calendar", "get_browser_history",
        
        # Remote control
        "ping", "vibrate", "ring", "screenshot", "front_camera", "back_camera",
        "record_audio", "record_screen", "lock_phone", "unlock_phone", "reboot",
        "shutdown", "set_volume", "set_brightness", "set_wallpaper", "set_ringtone",
        "enable_wifi", "disable_wifi", "enable_bluetooth", "disable_bluetooth",
        "enable_mobile_data", "disable_mobile_data", "torch_on", "torch_off",
        "play_sound", "speak_text", "show_notification", "open_url",
        "send_sms", "make_call", "block_number", "unblock_number",
        
        # App management
        "open_app", "close_app", "install_app", "uninstall_app",
        "block_app", "unblock_app", "clear_app_data", "force_stop_app",
        
        # File management
        "list_files", "get_file", "delete_file", "rename_file",
        "copy_file", "move_file", "create_folder", "search_files",
        
        # Security
        "wipe_data", "factory_reset", "show_app", "hide_app",
        "change_passcode", "lock_phone",
        
        # Monitoring
        "keylogger_start", "keylogger_stop", "get_keylogger",
        "screen_record_start", "screen_record_stop",
        "location_live", "location_stop",
        
        # System
        "set_language", "set_timezone", "set_alarm", "dns_change"
    ]
    
    # Commands requiring specific parameters
    PARAM_REQUIRED_COMMANDS = {
        "send_sms": ["number", "message"],
        "make_call": ["number"],
        "block_number": ["number"],
        "unblock_number": ["number"],
        "open_app": ["package"],
        "close_app": ["package"],
        "uninstall_app": ["package"],
        "install_app": ["url"],
        "get_file": ["path"],
        "delete_file": ["path"],
        "open_url": ["url"],
        "set_wallpaper": ["url"],
        "set_ringtone": ["url"],
        "speak_text": ["text"],
        "show_notification": ["title", "message"],
        "set_volume": ["level"],
        "set_brightness": ["level"],
    }
    
    @classmethod
    def validate(cls, data: Dict) -> ValidationResult:
        """Validate command data."""
        result = ValidationResult(valid=True, data=data)
        
        # Device ID
        error = Validator.validate_required(data.get("device_id"), "device_id")
        if error:
            result.add_error("device_id", error)
        
        # Command
        error = Validator.validate_required(data.get("command"), "command")
        if error:
            result.add_error("command", error)
        elif data.get("command") not in cls.VALID_COMMANDS:
            result.add_error("command", "أمر غير معروف")
        
        # Parameters validation
        command = data.get("command")
        params = data.get("params", {})
        
        if command in cls.PARAM_REQUIRED_COMMANDS:
            required_params = cls.PARAM_REQUIRED_COMMANDS[command]
            for param in required_params:
                if param not in params or params[param] is None:
                    result.add_error("params", f"المعامل '{param}' مطلوب")
        
        # Specific parameter validation
        if command == "send_sms":
            if params.get("number"):
                error = Validator.validate_phone(params["number"])
                if error:
                    result.add_error("params.number", error)
            if params.get("message"):
                error = Validator.validate_string(params["message"], min_len=1, max_len=1000)
                if error:
                    result.add_error("params.message", error)
        
        elif command == "make_call":
            if params.get("number"):
                error = Validator.validate_phone(params["number"])
                if error:
                    result.add_error("params.number", error)
        
        elif command == "set_volume":
            if params.get("level") is not None:
                error = Validator.validate_number(params["level"], min_val=0, max_val=100)
                if error:
                    result.add_error("params.level", error)
        
        elif command == "set_brightness":
            if params.get("level") is not None:
                error = Validator.validate_number(params["level"], min_val=0, max_val=100)
                if error:
                    result.add_error("params.level", error)
        
        elif command == "open_url":
            if params.get("url"):
                error = Validator.validate_url(params["url"])
                if error:
                    result.add_error("params.url", error)
        
        elif command == "install_app":
            if params.get("url"):
                error = Validator.validate_url(params["url"])
                if error:
                    result.add_error("params.url", error)
        
        return result

class DeviceSchema:
    """Schema for device validation."""
    
    @classmethod
    def validate(cls, data: Dict) -> ValidationResult:
        """Validate device data."""
        result = ValidationResult(valid=True, data=data)
        
        # Device ID
        error = Validator.validate_required(data.get("id"), "id")
        if error:
            result.add_error("id", error)
        elif not re.match(r'^[a-zA-Z0-9_-]{8,64}$', str(data.get("id", ""))):
            result.add_error("id", "معرف الجهاز غير صحيح")
        
        # Name
        error = Validator.validate_required(data.get("name"), "name")
        if error:
            result.add_error("name", error)
        
        # Model
        if data.get("model"):
            error = Validator.validate_string(data["model"], max_len=100)
            if error:
                result.add_error("model", error)
        
        # Android version
        if data.get("android_version"):
            error = Validator.validate_string(data["android_version"], max_len=20)
            if error:
                result.add_error("android_version", error)
        
        # SDK version
        if data.get("sdk_version") is not None:
            error = Validator.validate_integer(data["sdk_version"], min_val=1, max_val=99)
            if error:
                result.add_error("sdk_version", error)
        
        # Battery level
        if data.get("battery_level") is not None:
            error = Validator.validate_integer(data["battery_level"], min_val=0, max_val=100)
            if error:
                result.add_error("battery_level", error)
        
        # Storage
        if data.get("storage_total") is not None:
            error = Validator.validate_integer(data["storage_total"], min_val=0)
            if error:
                result.add_error("storage_total", error)
        
        if data.get("storage_used") is not None:
            error = Validator.validate_integer(data["storage_used"], min_val=0)
            if error:
                result.add_error("storage_used", error)
        
        return result

class FileUploadSchema:
    """Schema for file upload validation."""
    
    ALLOWED_TYPES = {
        "image/jpeg", "image/png", "image/gif", "image/webp",
        "video/mp4", "video/3gp", "video/webm",
        "audio/mp3", "audio/mp4", "audio/mpeg", "audio/amr",
        "application/pdf", "application/zip",
        "text/plain", "text/csv",
        "application/vnd.android.package-archive"  # APK
    }
    
    MAX_SIZE = 100 * 1024 * 1024  # 100MB
    
    @classmethod
    def validate(cls, data: Dict) -> ValidationResult:
        """Validate file upload data."""
        result = ValidationResult(valid=True, data=data)
        
        # Device ID
        error = Validator.validate_required(data.get("device_id"), "device_id")
        if error:
            result.add_error("device_id", error)
        
        # File path
        error = Validator.validate_required(data.get("path"), "path")
        if error:
            result.add_error("path", error)
        
        # File name
        error = Validator.validate_required(data.get("filename"), "filename")
        if error:
            result.add_error("filename", error)
        
        # File size
        if data.get("size") is not None:
            error = Validator.validate_integer(data["size"], min_val=1, max_val=cls.MAX_SIZE)
            if error:
                result.add_error("size", f"حجم الملف يجب ألا يتجاوز {cls.MAX_SIZE // (1024*1024)} ميجابايت")
        
        # MIME type
        if data.get("mime_type"):
            error = Validator.validate_enum(data["mime_type"], list(cls.ALLOWED_TYPES))
            if error:
                result.add_error("mime_type", "نوع الملف غير مدعوم")
        
        return result

class LinkCodeSchema:
    """Schema for link code validation."""
    
    @classmethod
    def validate(cls, data: Dict) -> ValidationResult:
        """Validate link code data."""
        result = ValidationResult(valid=True, data=data)
        
        # Code
        error = Validator.validate_required(data.get("code"), "code")
        if error:
            result.add_error("code", error)
        elif not re.match(r'^[A-Z0-9]{6}$', str(data.get("code", ""))):
            result.add_error("code", "كود الربط غير صحيح (يجب أن يكون 6 أحرف/أرقام)")
        
        return result

class SessionSchema:
    """Schema for session validation."""
    
    @classmethod
    def validate_login(cls, data: Dict) -> ValidationResult:
        """Validate login request."""
        result = ValidationResult(valid=True, data=data)
        
        # Username
        error = Validator.validate_required(data.get("username"), "username")
        if error:
            result.add_error("username", error)
        
        # Password
        error = Validator.validate_required(data.get("password"), "password")
        if error:
            result.add_error("password", error)
        
        return result
    
    @classmethod
    def validate_token(cls, data: Dict) -> ValidationResult:
        """Validate token request."""
        result = ValidationResult(valid=True, data=data)
        
        # Token
        error = Validator.validate_required(data.get("token"), "token")
        if error:
            result.add_error("token", error)
        
        return result

# ============================================================================
# VALIDATION HELPER FUNCTIONS
# ============================================================================

def validate_command(data: Dict) -> ValidationResult:
    """Validate command data."""
    return CommandSchema.validate(data)

def validate_device(data: Dict) -> ValidationResult:
    """Validate device data."""
    return DeviceSchema.validate(data)

def validate_file_upload(data: Dict) -> ValidationResult:
    """Validate file upload data."""
    return FileUploadSchema.validate(data)

def validate_link_code(data: Dict) -> ValidationResult:
    """Validate link code data."""
    return LinkCodeSchema.validate(data)

def validate_login(data: Dict) -> ValidationResult:
    """Validate login request."""
    return SessionSchema.validate_login(data)

def sanitize_input(value: str, max_length: int = 1000) -> str:
    """Sanitize string input."""
    if not isinstance(value, str):
        return ""
    
    # Remove null bytes
    value = value.replace("\x00", "")
    
    # Trim whitespace
    value = value.strip()
    
    # Limit length
    if len(value) > max_length:
        value = value[:max_length]
    
    return value

def sanitize_dict(data: Dict, max_depth: int = 5) -> Dict:
    """Recursively sanitize a dictionary."""
    if max_depth <= 0:
        return {}
    
    result = {}
    for key, value in data.items():
        # Sanitize key
        key = sanitize_input(str(key), max_length=100)
        
        if isinstance(value, dict):
            result[key] = sanitize_dict(value, max_depth - 1)
        elif isinstance(value, list):
            result[key] = [
                sanitize_dict(v, max_depth - 1) if isinstance(v, dict)
                else sanitize_input(str(v)) if isinstance(v, str)
                else v
                for v in value[:100]  # Limit list size
            ]
        elif isinstance(value, str):
            result[key] = sanitize_input(value)
        else:
            result[key] = value
    
    return result
