#!/usr/bin/env python3
"""
Abu-Zahra Database Layer
SQLite/PostgreSQL abstraction with proper models, indexing, and audit trails.
"""

import sqlite3
import json
import time
import uuid
import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Any, Union
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from enum import Enum
import logging

log = logging.getLogger("abu-zahra.db")

# ============================================================================
# CONFIGURATION
# ============================================================================

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "abuzahra.db"

# ============================================================================
# ENUMS
# ============================================================================

class DeviceState(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    IDLE = "idle"
    BUSY = "busy"
    LOW_BATTERY = "low_battery"
    CHARGING = "charging"

class CommandState(Enum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    RETRYING = "retrying"

class Priority(Enum):
    CRITICAL = 3
    HIGH = 2
    NORMAL = 1
    LOW = 0

class EventType(Enum):
    DEVICE_LINKED = "device_linked"
    DEVICE_UNLINKED = "device_unlinked"
    DEVICE_ONLINE = "device_online"
    DEVICE_OFFLINE = "device_offline"
    COMMAND_QUEUED = "command_queued"
    COMMAND_EXECUTED = "command_executed"
    COMMAND_FAILED = "command_failed"
    FILE_UPLOADED = "file_uploaded"
    ALERT_TRIGGERED = "alert_triggered"
    SYSTEM_ERROR = "system_error"

# ============================================================================
# MODELS
# ============================================================================

@dataclass
class Device:
    id: str
    name: str
    model: str
    android_version: str
    manufacturer: str
    sdk_version: int
    phone_number: Optional[str]
    country: Optional[str]
    carrier: Optional[str]
    state: str = "offline"
    last_seen: float = 0.0
    linked_at: float = 0.0
    battery_level: int = 0
    battery_charging: bool = False
    storage_total: int = 0
    storage_used: int = 0
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    permissions: Dict = None
    settings: Dict = None
    metadata: Dict = None
    
    def __post_init__(self):
        if self.permissions is None:
            self.permissions = {}
        if self.settings is None:
            self.settings = {}
        if self.metadata is None:
            self.metadata = {}

@dataclass
class Command:
    id: str
    device_id: str
    command: str
    params: Dict
    state: str = "queued"
    priority: int = 1
    created_at: float = 0.0
    delivered_at: Optional[float] = None
    executed_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Dict] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: int = 300
    source: str = "telegram"  # telegram, web, api
    source_chat_id: Optional[int] = None
    
    def __post_init__(self):
        if self.created_at == 0:
            self.created_at = time.time()

@dataclass
class Event:
    id: str
    device_id: Optional[str]
    event_type: str
    data: Dict
    timestamp: float
    severity: str = "info"  # info, warning, error, critical
    
    @staticmethod
    def create(device_id: str, event_type: str, data: Dict, severity: str = "info"):
        return Event(
            id=str(uuid.uuid4()),
            device_id=device_id,
            event_type=event_type,
            data=data,
            timestamp=time.time(),
            severity=severity
        )

@dataclass
class Session:
    id: str
    device_id: str
    session_token: str
    created_at: float
    expires_at: float
    last_activity: float
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    is_active: bool = True

@dataclass
class AuditLog:
    id: str
    action: str
    entity_type: str
    entity_id: str
    old_value: Optional[Dict]
    new_value: Optional[Dict]
    actor: str
    timestamp: float
    ip_address: Optional[str] = None
    metadata: Optional[Dict] = None

# ============================================================================
# DATABASE MANAGER
# ============================================================================

class DatabaseManager:
    """Thread-safe SQLite database manager with connection pooling."""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, db_path: str = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_path: str = None):
        if self._initialized:
            return
        
        self.db_path = db_path or str(DB_PATH)
        self._local = threading.local()
        self._initialized = True
        self._init_database()
        log.info("Database initialized at %s", self.db_path)
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=10000")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.connection = conn
        return self._local.connection
    
    @contextmanager
    def transaction(self):
        """Context manager for database transactions."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.error("Transaction failed: %s", e)
            raise
    
    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a query and return cursor."""
        conn = self._get_connection()
        return conn.execute(query, params)
    
    def executemany(self, query: str, params_list: List[tuple]) -> sqlite3.Cursor:
        """Execute a query with multiple parameter sets."""
        conn = self._get_connection()
        return conn.executemany(query, params_list)
    
    def _init_database(self):
        """Initialize database schema."""
        with self.transaction() as conn:
            # Devices table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    model TEXT,
                    android_version TEXT,
                    manufacturer TEXT,
                    sdk_version INTEGER DEFAULT 0,
                    phone_number TEXT,
                    country TEXT,
                    carrier TEXT,
                    state TEXT DEFAULT 'offline',
                    last_seen REAL DEFAULT 0,
                    linked_at REAL DEFAULT 0,
                    battery_level INTEGER DEFAULT 0,
                    battery_charging INTEGER DEFAULT 0,
                    storage_total INTEGER DEFAULT 0,
                    storage_used INTEGER DEFAULT 0,
                    latitude REAL,
                    longitude REAL,
                    permissions TEXT DEFAULT '{}',
                    settings TEXT DEFAULT '{}',
                    metadata TEXT DEFAULT '{}',
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    updated_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)
            
            # Commands table with indexing
            conn.execute("""
                CREATE TABLE IF NOT EXISTS commands (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    command TEXT NOT NULL,
                    params TEXT DEFAULT '{}',
                    state TEXT DEFAULT 'queued',
                    priority INTEGER DEFAULT 1,
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    delivered_at REAL,
                    executed_at REAL,
                    completed_at REAL,
                    result TEXT,
                    error TEXT,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    timeout_seconds INTEGER DEFAULT 300,
                    source TEXT DEFAULT 'telegram',
                    source_chat_id INTEGER,
                    FOREIGN KEY (device_id) REFERENCES devices(id)
                )
            """)
            
            # Events table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    device_id TEXT,
                    event_type TEXT NOT NULL,
                    data TEXT DEFAULT '{}',
                    timestamp REAL DEFAULT (strftime('%s', 'now')),
                    severity TEXT DEFAULT 'info',
                    FOREIGN KEY (device_id) REFERENCES devices(id)
                )
            """)
            
            # Sessions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    device_id TEXT,
                    session_token TEXT UNIQUE NOT NULL,
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    expires_at REAL,
                    last_activity REAL,
                    ip_address TEXT,
                    user_agent TEXT,
                    is_active INTEGER DEFAULT 1,
                    FOREIGN KEY (device_id) REFERENCES devices(id)
                )
            """)
            
            # Audit logs table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    actor TEXT NOT NULL,
                    timestamp REAL DEFAULT (strftime('%s', 'now')),
                    ip_address TEXT,
                    metadata TEXT
                )
            """)
            
            # Files table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    size INTEGER DEFAULT 0,
                    mime_type TEXT,
                    hash TEXT,
                    uploaded_at REAL DEFAULT (strftime('%s', 'now')),
                    upload_path TEXT,
                    metadata TEXT DEFAULT '{}',
                    FOREIGN KEY (device_id) REFERENCES devices(id)
                )
            """)
            
            # Location history table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS location_history (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    accuracy REAL,
                    altitude REAL,
                    speed REAL,
                    bearing REAL,
                    timestamp REAL DEFAULT (strftime('%s', 'now')),
                    battery_level INTEGER,
                    source TEXT DEFAULT 'gps',
                    FOREIGN KEY (device_id) REFERENCES devices(id)
                )
            """)
            
            # Heartbeats table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS heartbeats (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    timestamp REAL DEFAULT (strftime('%s', 'now')),
                    battery_level INTEGER,
                    battery_charging INTEGER,
                    network_type TEXT,
                    signal_strength INTEGER,
                    memory_total INTEGER,
                    memory_used INTEGER,
                    cpu_usage REAL,
                    FOREIGN KEY (device_id) REFERENCES devices(id)
                )
            """)
            
            # Alerts table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    severity TEXT DEFAULT 'warning',
                    message TEXT,
                    data TEXT DEFAULT '{}',
                    triggered_at REAL DEFAULT (strftime('%s', 'now')),
                    acknowledged INTEGER DEFAULT 0,
                    acknowledged_at REAL,
                    acknowledged_by TEXT,
                    FOREIGN KEY (device_id) REFERENCES devices(id)
                )
            """)
            
            # Workflows table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    trigger_type TEXT NOT NULL,
                    trigger_config TEXT DEFAULT '{}',
                    actions TEXT DEFAULT '[]',
                    enabled INTEGER DEFAULT 1,
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    last_triggered_at REAL,
                    trigger_count INTEGER DEFAULT 0
                )
            """)
            
            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_commands_device ON commands(device_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_commands_state ON commands(state)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_commands_created ON commands(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_device ON events(device_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_state ON devices(state)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_last_seen ON devices(last_seen)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_location_device ON location_history(device_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_location_timestamp ON location_history(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_heartbeats_device ON heartbeats(device_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_device ON alerts(device_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_acknowledged ON alerts(acknowledged)")

# ============================================================================
# DEVICE REPOSITORY
# ============================================================================

class DeviceRepository:
    """Repository for device CRUD operations."""
    
    def __init__(self, db: DatabaseManager = None):
        self.db = db or DatabaseManager()
    
    def create(self, device: Device) -> Device:
        """Create a new device."""
        with self.db.transaction() as conn:
            conn.execute("""
                INSERT INTO devices (
                    id, name, model, android_version, manufacturer, sdk_version,
                    phone_number, country, carrier, state, last_seen, linked_at,
                    battery_level, battery_charging, storage_total, storage_used,
                    latitude, longitude, permissions, settings, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                device.id, device.name, device.model, device.android_version,
                device.manufacturer, device.sdk_version, device.phone_number,
                device.country, device.carrier, device.state, device.last_seen,
                device.linked_at, device.battery_level, int(device.battery_charging),
                device.storage_total, device.storage_used, device.latitude,
                device.longitude, json.dumps(device.permissions),
                json.dumps(device.settings), json.dumps(device.metadata)
            ))
        return device
    
    def get(self, device_id: str) -> Optional[Device]:
        """Get a device by ID."""
        row = self.db.execute(
            "SELECT * FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
        if row:
            return self._row_to_device(row)
        return None
    
    def get_all(self, state: str = None) -> List[Device]:
        """Get all devices, optionally filtered by state."""
        if state:
            rows = self.db.execute(
                "SELECT * FROM devices WHERE state = ? ORDER BY last_seen DESC",
                (state,)
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM devices ORDER BY last_seen DESC"
            ).fetchall()
        return [self._row_to_device(row) for row in rows]
    
    def update(self, device_id: str, **kwargs) -> bool:
        """Update device fields."""
        if not kwargs:
            return False
        
        fields = []
        values = []
        for key, value in kwargs.items():
            if key in ('permissions', 'settings', 'metadata'):
                value = json.dumps(value)
            elif key == 'battery_charging':
                value = int(value)
            fields.append(f"{key} = ?")
            values.append(value)
        
        fields.append("updated_at = ?")
        values.append(time.time())
        values.append(device_id)
        
        with self.db.transaction() as conn:
            conn.execute(
                f"UPDATE devices SET {', '.join(fields)} WHERE id = ?",
                tuple(values)
            )
        return True
    
    def delete(self, device_id: str) -> bool:
        """Delete a device."""
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        return True
    
    def update_heartbeat(self, device_id: str, data: Dict) -> bool:
        """Update device heartbeat and health data."""
        now = time.time()
        with self.db.transaction() as conn:
            # Update device
            conn.execute("""
                UPDATE devices SET 
                    last_seen = ?,
                    battery_level = ?,
                    battery_charging = ?,
                    state = CASE 
                        WHEN ? = 0 AND battery_level < 15 THEN 'low_battery'
                        WHEN ? = 1 THEN 'charging'
                        ELSE 'online'
                    END,
                    updated_at = ?
                WHERE id = ?
            """, (
                now,
                data.get('battery_level', 0),
                int(data.get('battery_charging', False)),
                int(data.get('battery_charging', False)),
                int(data.get('battery_charging', False)),
                now,
                device_id
            ))
            
            # Insert heartbeat record
            conn.execute("""
                INSERT INTO heartbeats (
                    id, device_id, timestamp, battery_level, battery_charging,
                    network_type, signal_strength, memory_total, memory_used, cpu_usage
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()), device_id, now,
                data.get('battery_level'),
                int(data.get('battery_charging', False)),
                data.get('network_type'),
                data.get('signal_strength'),
                data.get('memory_total'),
                data.get('memory_used'),
                data.get('cpu_usage')
            ))
        return True
    
    def _row_to_device(self, row) -> Device:
        """Convert database row to Device object."""
        return Device(
            id=row['id'],
            name=row['name'],
            model=row['model'],
            android_version=row['android_version'],
            manufacturer=row['manufacturer'],
            sdk_version=row['sdk_version'],
            phone_number=row['phone_number'],
            country=row['country'],
            carrier=row['carrier'],
            state=row['state'],
            last_seen=row['last_seen'],
            linked_at=row['linked_at'],
            battery_level=row['battery_level'],
            battery_charging=bool(row['battery_charging']),
            storage_total=row['storage_total'],
            storage_used=row['storage_used'],
            latitude=row['latitude'],
            longitude=row['longitude'],
            permissions=json.loads(row['permissions'] or '{}'),
            settings=json.loads(row['settings'] or '{}'),
            metadata=json.loads(row['metadata'] or '{}')
        )

# ============================================================================
# COMMAND REPOSITORY
# ============================================================================

class CommandRepository:
    """Repository for command CRUD operations."""
    
    def __init__(self, db: DatabaseManager = None):
        self.db = db or DatabaseManager()
    
    def create(self, cmd: Command) -> Command:
        """Create a new command."""
        with self.db.transaction() as conn:
            conn.execute("""
                INSERT INTO commands (
                    id, device_id, command, params, state, priority,
                    created_at, max_retries, timeout_seconds, source, source_chat_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cmd.id, cmd.device_id, cmd.command, json.dumps(cmd.params),
                cmd.state, cmd.priority, cmd.created_at, cmd.max_retries,
                cmd.timeout_seconds, cmd.source, cmd.source_chat_id
            ))
        return cmd
    
    def get(self, cmd_id: str) -> Optional[Command]:
        """Get a command by ID."""
        row = self.db.execute(
            "SELECT * FROM commands WHERE id = ?", (cmd_id,)
        ).fetchone()
        if row:
            return self._row_to_command(row)
        return None
    
    def get_pending(self, device_id: str = None, limit: int = 50) -> List[Command]:
        """Get pending commands, optionally filtered by device."""
        if device_id:
            rows = self.db.execute("""
                SELECT * FROM commands 
                WHERE device_id = ? AND state IN ('queued', 'retrying')
                ORDER BY priority DESC, created_at ASC
                LIMIT ?
            """, (device_id, limit)).fetchall()
        else:
            rows = self.db.execute("""
                SELECT * FROM commands 
                WHERE state IN ('queued', 'retrying')
                ORDER BY priority DESC, created_at ASC
                LIMIT ?
            """, (limit,)).fetchall()
        return [self._row_to_command(row) for row in rows]
    
    def get_next_for_device(self, device_id: str) -> Optional[Command]:
        """Get the next command for a device (priority queue)."""
        row = self.db.execute("""
            SELECT * FROM commands 
            WHERE device_id = ? AND state IN ('queued', 'retrying')
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
        """, (device_id,)).fetchone()
        if row:
            return self._row_to_command(row)
        return None
    
    def update_state(self, cmd_id: str, state: str, result: Dict = None, error: str = None) -> bool:
        """Update command state."""
        now = time.time()
        with self.db.transaction() as conn:
            updates = ["state = ?"]
            params = [state]
            
            if state == "delivered":
                updates.append("delivered_at = ?")
                params.append(now)
            elif state == "executing":
                updates.append("executed_at = ?")
                params.append(now)
            elif state in ("success", "failed", "timeout", "cancelled"):
                updates.append("completed_at = ?")
                params.append(now)
            
            if result is not None:
                updates.append("result = ?")
                params.append(json.dumps(result))
            
            if error is not None:
                updates.append("error = ?")
                params.append(error)
            
            params.append(cmd_id)
            conn.execute(
                f"UPDATE commands SET {', '.join(updates)} WHERE id = ?",
                tuple(params)
            )
        return True
    
    def increment_retry(self, cmd_id: str) -> int:
        """Increment retry count and return new count."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT retry_count FROM commands WHERE id = ?", (cmd_id,)
            ).fetchone()
            new_count = row['retry_count'] + 1
            conn.execute(
                "UPDATE commands SET retry_count = ?, state = 'retrying' WHERE id = ?",
                (new_count, cmd_id)
            )
        return new_count
    
    def cleanup_old(self, days: int = 7) -> int:
        """Delete old completed commands."""
        cutoff = time.time() - (days * 86400)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM commands WHERE state IN ('success', 'failed', 'timeout', 'cancelled') AND completed_at < ?",
                (cutoff,)
            )
            return cursor.rowcount
    
    def _row_to_command(self, row) -> Command:
        """Convert database row to Command object."""
        return Command(
            id=row['id'],
            device_id=row['device_id'],
            command=row['command'],
            params=json.loads(row['params'] or '{}'),
            state=row['state'],
            priority=row['priority'],
            created_at=row['created_at'],
            delivered_at=row['delivered_at'],
            executed_at=row['executed_at'],
            completed_at=row['completed_at'],
            result=json.loads(row['result']) if row['result'] else None,
            error=row['error'],
            retry_count=row['retry_count'],
            max_retries=row['max_retries'],
            timeout_seconds=row['timeout_seconds'],
            source=row['source'],
            source_chat_id=row['source_chat_id']
        )

# ============================================================================
# EVENT REPOSITORY
# ============================================================================

class EventRepository:
    """Repository for event logging."""
    
    def __init__(self, db: DatabaseManager = None):
        self.db = db or DatabaseManager()
    
    def log(self, event: Event) -> Event:
        """Log an event."""
        with self.db.transaction() as conn:
            conn.execute("""
                INSERT INTO events (id, device_id, event_type, data, timestamp, severity)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                event.id, event.device_id, event.event_type,
                json.dumps(event.data), event.timestamp, event.severity
            ))
        return event
    
    def get_recent(self, device_id: str = None, limit: int = 100) -> List[Event]:
        """Get recent events."""
        if device_id:
            rows = self.db.execute("""
                SELECT * FROM events WHERE device_id = ?
                ORDER BY timestamp DESC LIMIT ?
            """, (device_id, limit)).fetchall()
        else:
            rows = self.db.execute("""
                SELECT * FROM events ORDER BY timestamp DESC LIMIT ?
            """, (limit,)).fetchall()
        return [self._row_to_event(row) for row in rows]
    
    def get_by_type(self, event_type: str, limit: int = 100) -> List[Event]:
        """Get events by type."""
        rows = self.db.execute("""
            SELECT * FROM events WHERE event_type = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (event_type, limit)).fetchall()
        return [self._row_to_event(row) for row in rows]
    
    def cleanup_old(self, days: int = 30) -> int:
        """Delete old events."""
        cutoff = time.time() - (days * 86400)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM events WHERE timestamp < ?", (cutoff,)
            )
            return cursor.rowcount
    
    def _row_to_event(self, row) -> Event:
        return Event(
            id=row['id'],
            device_id=row['device_id'],
            event_type=row['event_type'],
            data=json.loads(row['data'] or '{}'),
            timestamp=row['timestamp'],
            severity=row['severity']
        )

# ============================================================================
# AUDIT LOG REPOSITORY
# ============================================================================

class AuditRepository:
    """Repository for audit trails."""
    
    def __init__(self, db: DatabaseManager = None):
        self.db = db or DatabaseManager()
    
    def log(self, audit: AuditLog) -> AuditLog:
        """Log an audit entry."""
        with self.db.transaction() as conn:
            conn.execute("""
                INSERT INTO audit_logs (
                    id, action, entity_type, entity_id, old_value, new_value,
                    actor, timestamp, ip_address, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                audit.id, audit.action, audit.entity_type, audit.entity_id,
                json.dumps(audit.old_value) if audit.old_value else None,
                json.dumps(audit.new_value) if audit.new_value else None,
                audit.actor, audit.timestamp, audit.ip_address,
                json.dumps(audit.metadata) if audit.metadata else None
            ))
        return audit
    
    def get_for_entity(self, entity_type: str, entity_id: str, limit: int = 100) -> List[AuditLog]:
        """Get audit log for an entity."""
        rows = self.db.execute("""
            SELECT * FROM audit_logs 
            WHERE entity_type = ? AND entity_id = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (entity_type, entity_id, limit)).fetchall()
        return [self._row_to_audit(row) for row in rows]
    
    def _row_to_audit(self, row) -> AuditLog:
        return AuditLog(
            id=row['id'],
            action=row['action'],
            entity_type=row['entity_type'],
            entity_id=row['entity_id'],
            old_value=json.loads(row['old_value']) if row['old_value'] else None,
            new_value=json.loads(row['new_value']) if row['new_value'] else None,
            actor=row['actor'],
            timestamp=row['timestamp'],
            ip_address=row['ip_address'],
            metadata=json.loads(row['metadata']) if row['metadata'] else None
        )

# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

db = DatabaseManager()
device_repo = DeviceRepository(db)
command_repo = CommandRepository(db)
event_repo = EventRepository(db)
audit_repo = AuditRepository(db)
