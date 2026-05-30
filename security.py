#!/usr/bin/env python3
"""
Abu-Zahra Security Module
Secure command transport with encryption, signing, anti-replay, and token rotation.
"""

import os
import time
import uuid
import json
import hashlib
import hmac
import base64
import secrets
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import logging

log = logging.getLogger("abu-zahra.security")

# ============================================================================
# CONFIGURATION
# ============================================================================

# Keys directory
KEYS_DIR = Path(__file__).parent / "data" / "keys"
KEYS_DIR.mkdir(parents=True, exist_ok=True)

# Token settings
TOKEN_EXPIRY = 3600  # 1 hour
NONCE_EXPIRY = 300   # 5 minutes for replay protection

# ============================================================================
# CRYPTO UTILITIES
# ============================================================================

def generate_key(length: int = 32) -> bytes:
    """Generate a cryptographically secure random key."""
    return secrets.token_bytes(length)

def generate_key_pair() -> Tuple[bytes, bytes]:
    """Generate a key pair for signing (private, public)."""
    private_key = generate_key(64)
    public_key = hashlib.sha256(private_key).digest()
    return private_key, public_key

def derive_key(password: str, salt: bytes = None, iterations: int = 100000) -> Tuple[bytes, bytes]:
    """Derive a key from password using PBKDF2."""
    if salt is None:
        salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations, dklen=32)
    return key, salt

# ============================================================================
# XOR CIPHER (Simple but effective for basic encryption)
# ============================================================================

class XORCipher:
    """Simple XOR-based cipher for command encryption."""
    
    @staticmethod
    def encrypt(data: bytes, key: bytes) -> bytes:
        """Encrypt data using XOR."""
        key_len = len(key)
        return bytes([data[i] ^ key[i % key_len] for i in range(len(data))])
    
    @staticmethod
    def decrypt(data: bytes, key: bytes) -> bytes:
        """Decrypt data using XOR (same as encrypt)."""
        return XORCipher.encrypt(data, key)

# ============================================================================
# MESSAGE AUTHENTICATION
# ============================================================================

class MessageAuthenticator:
    """HMAC-based message authentication."""
    
    def __init__(self, key: bytes = None):
        self.key = key or generate_key()
    
    def sign(self, data: bytes) -> str:
        """Sign data and return signature."""
        signature = hmac.new(self.key, data, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(signature).decode()
    
    def verify(self, data: bytes, signature: str) -> bool:
        """Verify data signature."""
        try:
            expected = base64.urlsafe_b64decode(signature.encode())
            actual = hmac.new(self.key, data, hashlib.sha256).digest()
            return hmac.compare_digest(expected, actual)
        except Exception:
            return False
    
    def sign_json(self, data: Dict) -> str:
        """Sign JSON data."""
        return self.sign(json.dumps(data, sort_keys=True).encode())
    
    def verify_json(self, data: Dict, signature: str) -> bool:
        """Verify JSON data signature."""
        return self.verify(json.dumps(data, sort_keys=True).encode(), signature)

# ============================================================================
# NONCE MANAGER (Anti-Replay)
# ============================================================================

class NonceManager:
    """Manages nonces for replay protection."""
    
    def __init__(self, expiry: int = NONCE_EXPIRY):
        self.expiry = expiry
        self._nonces: Dict[str, float] = {}
        self._lock = threading.RLock()
    
    def generate(self) -> str:
        """Generate a new nonce."""
        nonce = secrets.token_urlsafe(32)
        with self._lock:
            self._nonces[nonce] = time.time()
        return nonce
    
    def validate(self, nonce: str) -> bool:
        """Validate a nonce (must be unique and not expired)."""
        with self._lock:
            if nonce not in self._nonces:
                return False
            
            # Check if expired
            created = self._nonces[nonce]
            if time.time() - created > self.expiry:
                del self._nonces[nonce]
                return False
            
            # Nonce is valid, remove it (single use)
            del self._nonces[nonce]
            return True
    
    def cleanup(self) -> int:
        """Remove expired nonces."""
        now = time.time()
        with self._lock:
            expired = [n for n, t in self._nonces.items() if now - t > self.expiry]
            for nonce in expired:
                del self._nonces[nonce]
        return len(expired)
    
    def get_stats(self) -> Dict:
        """Get nonce statistics."""
        with self._lock:
            return {
                "active_nonces": len(self._nonces),
                "expiry_seconds": self.expiry
            }

# ============================================================================
# SECURE COMMAND TRANSPORT
# ============================================================================

@dataclass
class SecureCommand:
    """Encrypted and signed command."""
    id: str
    device_id: str
    encrypted_payload: str
    signature: str
    nonce: str
    timestamp: float
    version: int = 1
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "device_id": self.device_id,
            "encrypted_payload": self.encrypted_payload,
            "signature": self.signature,
            "nonce": self.nonce,
            "timestamp": self.timestamp,
            "version": self.version
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SecureCommand':
        return cls(
            id=data["id"],
            device_id=data["device_id"],
            encrypted_payload=data["encrypted_payload"],
            signature=data["signature"],
            nonce=data["nonce"],
            timestamp=data["timestamp"],
            version=data.get("version", 1)
        )

class SecureCommandTransport:
    """Handles secure command encryption and transport."""
    
    def __init__(self):
        self._device_keys: Dict[str, bytes] = {}
        self._master_key = generate_key()
        self._authenticator = MessageAuthenticator(self._master_key)
        self._nonce_manager = NonceManager()
        self._lock = threading.RLock()
    
    def register_device(self, device_id: str, key: bytes = None) -> bytes:
        """Register a device with its encryption key."""
        key = key or generate_key()
        with self._lock:
            self._device_keys[device_id] = key
        log.info("Registered encryption key for device: %s", device_id)
        return key
    
    def unregister_device(self, device_id: str) -> bool:
        """Remove device encryption key."""
        with self._lock:
            return self._device_keys.pop(device_id, None) is not None
    
    def rotate_key(self, device_id: str) -> bytes:
        """Rotate device encryption key."""
        new_key = generate_key()
        with self._lock:
            self._device_keys[device_id] = new_key
        log.info("Rotated encryption key for device: %s", device_id)
        return new_key
    
    def encrypt_command(self, device_id: str, command: Dict) -> Optional[SecureCommand]:
        """Encrypt and sign a command."""
        with self._lock:
            key = self._device_keys.get(device_id)
            if not key:
                log.warning("No key for device: %s", device_id)
                return None
        
        # Prepare payload
        payload = json.dumps({
            "command": command,
            "timestamp": time.time(),
            "nonce": self._nonce_manager.generate()
        }).encode()
        
        # Encrypt
        encrypted = XORCipher.encrypt(payload, key)
        encrypted_payload = base64.urlsafe_b64encode(encrypted).decode()
        
        # Sign
        signature = self._authenticator.sign(encrypted)
        
        return SecureCommand(
            id=str(uuid.uuid4()),
            device_id=device_id,
            encrypted_payload=encrypted_payload,
            signature=signature,
            nonce=secrets.token_urlsafe(16),
            timestamp=time.time()
        )
    
    def decrypt_command(self, secure_cmd: SecureCommand) -> Optional[Dict]:
        """Decrypt and verify a command."""
        with self._lock:
            key = self._device_keys.get(secure_cmd.device_id)
            if not key:
                log.warning("No key for device: %s", secure_cmd.device_id)
                return None
        
        # Decode encrypted payload
        try:
            encrypted = base64.urlsafe_b64decode(secure_cmd.encrypted_payload.encode())
        except Exception:
            log.error("Failed to decode encrypted payload")
            return None
        
        # Verify signature
        if not self._authenticator.verify(encrypted, secure_cmd.signature):
            log.error("Invalid signature for command: %s", secure_cmd.id)
            return None
        
        # Decrypt
        decrypted = XORCipher.decrypt(encrypted, key)
        
        try:
            payload = json.loads(decrypted.decode())
        except Exception:
            log.error("Failed to decrypt command")
            return None
        
        # Validate nonce
        if not self._nonce_manager.validate(payload.get("nonce", "")):
            log.error("Invalid or replayed nonce")
            return None
        
        return payload.get("command")
    
    def get_stats(self) -> Dict:
        """Get transport statistics."""
        return {
            "registered_devices": len(self._device_keys),
            "nonce_stats": self._nonce_manager.get_stats()
        }

# ============================================================================
# TOKEN MANAGER
# ============================================================================

@dataclass
class Token:
    """Authentication token."""
    token: str
    device_id: str
    created_at: float
    expires_at: float
    permissions: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        return time.time() > self.expires_at
    
    def to_dict(self) -> Dict:
        return {
            "token": self.token,
            "device_id": self.device_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "permissions": self.permissions,
            "metadata": self.metadata
        }

class TokenManager:
    """Manages authentication tokens."""
    
    def __init__(self, expiry: int = TOKEN_EXPIRY):
        self.expiry = expiry
        self._tokens: Dict[str, Token] = {}
        self._device_tokens: Dict[str, str] = {}  # device_id -> token
        self._lock = threading.RLock()
    
    def create_token(self, device_id: str, permissions: List[str] = None, metadata: Dict = None) -> Token:
        """Create a new token for a device."""
        token_str = secrets.token_urlsafe(48)
        now = time.time()
        
        token = Token(
            token=token_str,
            device_id=device_id,
            created_at=now,
            expires_at=now + self.expiry,
            permissions=permissions or [],
            metadata=metadata or {}
        )
        
        with self._lock:
            # Invalidate old token
            old_token = self._device_tokens.get(device_id)
            if old_token and old_token in self._tokens:
                del self._tokens[old_token]
            
            self._tokens[token_str] = token
            self._device_tokens[device_id] = token_str
        
        log.info("Created token for device: %s", device_id)
        return token
    
    def validate_token(self, token_str: str) -> Optional[Token]:
        """Validate a token."""
        with self._lock:
            token = self._tokens.get(token_str)
            if not token:
                return None
            
            if token.is_expired():
                del self._tokens[token_str]
                self._device_tokens.pop(token.device_id, None)
                return None
            
            return token
    
    def revoke_token(self, token_str: str) -> bool:
        """Revoke a token."""
        with self._lock:
            token = self._tokens.pop(token_str, None)
            if token:
                self._device_tokens.pop(token.device_id, None)
                return True
            return False
    
    def revoke_device_tokens(self, device_id: str) -> int:
        """Revoke all tokens for a device."""
        count = 0
        with self._lock:
            token_str = self._device_tokens.pop(device_id, None)
            if token_str and token_str in self._tokens:
                del self._tokens[token_str]
                count = 1
        return count
    
    def refresh_token(self, token_str: str) -> Optional[Token]:
        """Refresh a token (extend expiry)."""
        with self._lock:
            token = self._tokens.get(token_str)
            if not token or token.is_expired():
                return None
            
            token.expires_at = time.time() + self.expiry
            return token
    
    def cleanup_expired(self) -> int:
        """Remove expired tokens."""
        now = time.time()
        expired = []
        
        with self._lock:
            for token_str, token in self._tokens.items():
                if token.expires_at < now:
                    expired.append(token_str)
            
            for token_str in expired:
                token = self._tokens.pop(token_str)
                self._device_tokens.pop(token.device_id, None)
        
        if expired:
            log.info("Cleaned up %d expired tokens", len(expired))
        
        return len(expired)
    
    def get_stats(self) -> Dict:
        """Get token statistics."""
        with self._lock:
            return {
                "active_tokens": len(self._tokens),
                "device_tokens": len(self._device_tokens),
                "expiry_seconds": self.expiry
            }

# ============================================================================
# RATE LIMITER
# ============================================================================

class RateLimiter:
    """Token bucket rate limiter."""
    
    def __init__(
        self,
        rate: int = 100,  # requests per minute
        burst: int = 20,  # burst size
        per_device: bool = True
    ):
        self.rate = rate
        self.burst = burst
        self.per_device = per_device
        self._buckets: Dict[str, Dict] = {}
        self._lock = threading.RLock()
    
    def _get_bucket_key(self, identifier: str, device_id: str = None) -> str:
        if self.per_device and device_id:
            return f"{identifier}:{device_id}"
        return identifier
    
    def check_rate(self, identifier: str, device_id: str = None) -> Tuple[bool, Dict]:
        """Check if request is within rate limit."""
        key = self._get_bucket_key(identifier, device_id)
        now = time.time()
        
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = {
                    "tokens": self.burst,
                    "last_update": now
                }
            
            bucket = self._buckets[key]
            
            # Refill tokens
            elapsed = now - bucket["last_update"]
            refill = elapsed * (self.rate / 60)
            bucket["tokens"] = min(self.burst, bucket["tokens"] + refill)
            bucket["last_update"] = now
            
            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                return True, {
                    "allowed": True,
                    "remaining": int(bucket["tokens"]),
                    "reset_after": 60 / self.rate
                }
            else:
                return False, {
                    "allowed": False,
                    "remaining": 0,
                    "reset_after": (1 - bucket["tokens"]) * 60 / self.rate
                }
    
    def get_stats(self) -> Dict:
        """Get rate limiter statistics."""
        with self._lock:
            return {
                "tracked_entities": len(self._buckets),
                "rate_per_minute": self.rate,
                "burst_size": self.burst
            }

# ============================================================================
# SECURITY MANAGER
# ============================================================================

class SecurityManager:
    """Central security management."""
    
    def __init__(self):
        self.transport = SecureCommandTransport()
        self.tokens = TokenManager()
        self.nonces = NonceManager()
        self.rate_limiter = RateLimiter(rate=100, burst=20)
        self._lock = threading.RLock()
    
    def register_device(self, device_id: str) -> Dict:
        """Register a device for secure communication."""
        key = self.transport.register_device(device_id)
        token = self.tokens.create_token(device_id)
        
        return {
            "device_id": device_id,
            "encryption_key": base64.urlsafe_b64encode(key).decode(),
            "auth_token": token.token,
            "expires_at": token.expires_at
        }
    
    def unregister_device(self, device_id: str):
        """Unregister a device."""
        self.transport.unregister_device(device_id)
        self.tokens.revoke_device_tokens(device_id)
    
    def check_request(self, token_str: str, device_id: str = None) -> Tuple[bool, Optional[Token]]:
        """Check if request is authenticated and not rate limited."""
        # Validate token
        token = self.tokens.validate_token(token_str)
        if not token:
            return False, None
        
        # Check rate limit
        allowed, _ = self.rate_limiter.check_rate(token.device_id, device_id)
        if not allowed:
            return False, token
        
        return True, token
    
    def get_stats(self) -> Dict:
        """Get security statistics."""
        return {
            "transport": self.transport.get_stats(),
            "tokens": self.tokens.get_stats(),
            "nonces": self.nonces.get_stats(),
            "rate_limiter": self.rate_limiter.get_stats()
        }
    
    def cleanup(self) -> Dict:
        """Run cleanup tasks."""
        return {
            "expired_tokens": self.tokens.cleanup_expired(),
            "expired_nonces": self.nonces.cleanup()
        }

# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

security_manager = SecurityManager()

# ============================================================================
# DECORATORS
# ============================================================================

def secure_endpoint(func):
    """Decorator to secure an API endpoint."""
    async def wrapper(request, *args, **kwargs):
        auth = request.headers.get("Authorization", "")
        token = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else ""
        
        if not token:
            return {"ok": False, "error": "Missing token"}, 401
        
        allowed, token_obj = security_manager.check_request(token)
        if not allowed:
            return {"ok": False, "error": "Unauthorized or rate limited"}, 401
        
        request["token"] = token_obj
        return await func(request, *args, **kwargs)
    
    return wrapper

def rate_limit(rate: int = 100, burst: int = 20):
    """Decorator for custom rate limiting."""
    limiter = RateLimiter(rate=rate, burst=burst)
    
    def decorator(func):
        async def wrapper(request, *args, **kwargs):
            identifier = request.remote or "unknown"
            allowed, info = limiter.check_rate(identifier)
            
            if not allowed:
                return {"ok": False, "error": "Rate limit exceeded", "retry_after": info.get("reset_after")}, 429
            
            return await func(request, *args, **kwargs)
        
        return wrapper
    
    return decorator
