#!/usr/bin/env python3
"""
Abu-Zahra Disaster Recovery & Backup System
Automated backups, restore plans, failover, and database replication.
"""

import os
import sys
import json
import time
import shutil
import hashlib
import tarfile
import asyncio
import threading
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import logging

log = logging.getLogger("abu-zahra.backup")

# ============================================================================
# CONFIGURATION
# ============================================================================

DATA_DIR = Path(__file__).parent / "data"
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/opt/abuzahra/backups"))
LOGS_DIR = DATA_DIR / "logs"

# Backup settings
BACKUP_RETENTION_DAYS = int(os.environ.get("BACKUP_RETENTION_DAYS", "30"))
BACKUP_INTERVAL_HOURS = int(os.environ.get("BACKUP_INTERVAL_HOURS", "6"))
MAX_BACKUPS = int(os.environ.get("MAX_BACKUPS", "100"))
COMPRESSION_LEVEL = int(os.environ.get("BACKUP_COMPRESSION_LEVEL", "6"))

# ============================================================================
# BACKUP TYPES
# ============================================================================

class BackupType(Enum):
    FULL = "full"
    INCREMENTAL = "incremental"
    DIFFERENTIAL = "differential"
    DATABASE = "database"
    FILES = "files"
    CONFIG = "config"

class BackupStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    VERIFIED = "verified"

# ============================================================================
# BACKUP RECORD
# ============================================================================

@dataclass
class BackupRecord:
    """Record of a backup operation."""
    id: str
    type: BackupType
    status: BackupStatus
    created_at: float
    completed_at: Optional[float] = None
    size_bytes: int = 0
    file_path: str = ""
    checksum: str = ""
    error: str = ""
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "size_bytes": self.size_bytes,
            "file_path": self.file_path,
            "checksum": self.checksum,
            "error": self.error,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'BackupRecord':
        return cls(
            id=data["id"],
            type=BackupType(data["type"]),
            status=BackupStatus(data["status"]),
            created_at=data["created_at"],
            completed_at=data.get("completed_at"),
            size_bytes=data.get("size_bytes", 0),
            file_path=data.get("file_path", ""),
            checksum=data.get("checksum", ""),
            error=data.get("error", ""),
            metadata=data.get("metadata", {})
        )

# ============================================================================
# BACKUP MANAGER
# ============================================================================

class BackupManager:
    """Manages backup operations."""
    
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
        
        self.backup_dir = BACKUP_DIR
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        self.records_file = self.backup_dir / "backup_records.json"
        self.records: Dict[str, BackupRecord] = {}
        
        self._load_records()
        self._running = False
        self._task = None
        self._initialized = True
        
        log.info("Backup manager initialized")

    def _load_records(self):
        """Load backup records from file."""
        if self.records_file.exists():
            try:
                with open(self.records_file, 'r') as f:
                    data = json.load(f)
                    for bid, record in data.items():
                        self.records[bid] = BackupRecord.from_dict(record)
                log.info("Loaded %d backup records", len(self.records))
            except Exception as e:
                log.error("Failed to load backup records: %s", e)

    def _save_records(self):
        """Save backup records to file."""
        try:
            data = {bid: record.to_dict() for bid, record in self.records.items()}
            with open(self.records_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.error("Failed to save backup records: %s", e)

    def create_backup(self, backup_type: BackupType = BackupType.FULL, 
                      metadata: Dict = None) -> BackupRecord:
        """Create a new backup."""
        import uuid
        
        record = BackupRecord(
            id=str(uuid.uuid4()),
            type=backup_type,
            status=BackupStatus.PENDING,
            created_at=time.time(),
            metadata=metadata or {}
        )
        
        self.records[record.id] = record
        self._save_records()
        
        log.info("Created backup record: %s (%s)", record.id, backup_type.value)
        return record

    def execute_backup(self, record: BackupRecord) -> bool:
        """Execute a backup operation."""
        record.status = BackupStatus.IN_PROGRESS
        self._save_records()
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"backup_{record.type.value}_{timestamp}_{record.id[:8]}.tar.gz"
            backup_path = self.backup_dir / backup_filename
            
            # Create backup based on type
            if record.type == BackupType.FULL:
                self._create_full_backup(backup_path)
            elif record.type == BackupType.DATABASE:
                self._create_database_backup(backup_path)
            elif record.type == BackupType.FILES:
                self._create_files_backup(backup_path)
            elif record.type == BackupType.CONFIG:
                self._create_config_backup(backup_path)
            else:
                self._create_full_backup(backup_path)
            
            # Calculate checksum
            checksum = self._calculate_checksum(backup_path)
            
            # Update record
            record.status = BackupStatus.COMPLETED
            record.completed_at = time.time()
            record.file_path = str(backup_path)
            record.size_bytes = backup_path.stat().st_size
            record.checksum = checksum
            
            log.info("Backup completed: %s (%.2f MB)", record.id, record.size_bytes / 1024 / 1024)
            return True
            
        except Exception as e:
            record.status = BackupStatus.FAILED
            record.error = str(e)
            log.error("Backup failed: %s - %s", record.id, e)
            return False
        
        finally:
            self._save_records()

    def _create_full_backup(self, backup_path: Path):
        """Create a full system backup."""
        with tarfile.open(backup_path, "w:gz", compresslevel=COMPRESSION_LEVEL) as tar:
            # Add data directory
            if DATA_DIR.exists():
                tar.add(DATA_DIR, arcname="data")
            
            # Add logs
            if LOGS_DIR.exists():
                tar.add(LOGS_DIR, arcname="logs")
            
            # Add config files
            for config_file in Path(".").glob("*.json"):
                if config_file.name != "backup_records.json":
                    tar.add(config_file, arcname=f"config/{config_file.name}")

    def _create_database_backup(self, backup_path: Path):
        """Create a database backup."""
        db_file = DATA_DIR / "abuzahra.db"
        
        if not db_file.exists():
            raise FileNotFoundError("Database file not found")
        
        with tarfile.open(backup_path, "w:gz", compresslevel=COMPRESSION_LEVEL) as tar:
            tar.add(db_file, arcname="database/abuzahra.db")
            
            # Add device data
            devices_file = DATA_DIR / "devices.json"
            if devices_file.exists():
                tar.add(devices_file, arcname="database/devices.json")

    def _create_files_backup(self, backup_path: Path):
        """Create a files backup."""
        upload_dir = Path("/opt/abuzahra/uploads")
        
        with tarfile.open(backup_path, "w:gz", compresslevel=COMPRESSION_LEVEL) as tar:
            if upload_dir.exists():
                tar.add(upload_dir, arcname="uploads")

    def _create_config_backup(self, backup_path: Path):
        """Create a configuration backup."""
        with tarfile.open(backup_path, "w:gz", compresslevel=COMPRESSION_LEVEL) as tar:
            for config_file in Path(".").glob("*.json"):
                tar.add(config_file, arcname=f"config/{config_file.name}")
            
            # Add environment file if exists
            env_file = Path(".env")
            if env_file.exists():
                tar.add(env_file, arcname="config/.env")

    def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def verify_backup(self, backup_id: str) -> bool:
        """Verify backup integrity."""
        record = self.records.get(backup_id)
        if not record:
            return False
        
        backup_path = Path(record.file_path)
        if not backup_path.exists():
            return False
        
        # Verify checksum
        current_checksum = self._calculate_checksum(backup_path)
        if current_checksum != record.checksum:
            log.error("Backup checksum mismatch: %s", backup_id)
            return False
        
        # Verify archive integrity
        try:
            with tarfile.open(backup_path, "r:gz") as tar:
                # Try to get names - this validates the archive
                tar.getnames()
        except Exception as e:
            log.error("Backup archive corrupted: %s - %s", backup_id, e)
            return False
        
        record.status = BackupStatus.VERIFIED
        self._save_records()
        
        log.info("Backup verified: %s", backup_id)
        return True

    def restore_backup(self, backup_id: str, restore_path: Path = None) -> bool:
        """Restore from a backup."""
        record = self.records.get(backup_id)
        if not record:
            log.error("Backup not found: %s", backup_id)
            return False
        
        if record.status not in [BackupStatus.COMPLETED, BackupStatus.VERIFIED]:
            log.error("Backup not ready for restore: %s", backup_id)
            return False
        
        backup_path = Path(record.file_path)
        if not backup_path.exists():
            log.error("Backup file not found: %s", backup_path)
            return False
        
        restore_path = restore_path or DATA_DIR
        
        try:
            # Create restore point before restore
            self._create_restore_point()
            
            # Extract backup
            with tarfile.open(backup_path, "r:gz") as tar:
                tar.extractall(restore_path)
            
            log.info("Backup restored: %s to %s", backup_id, restore_path)
            return True
            
        except Exception as e:
            log.error("Restore failed: %s - %s", backup_id, e)
            return False

    def _create_restore_point(self):
        """Create a restore point before restore."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        restore_point_name = f"restore_point_{timestamp}"
        restore_point_path = self.backup_dir / restore_point_name
        
        shutil.copytree(DATA_DIR, restore_point_path)
        log.info("Created restore point: %s", restore_point_name)

    def cleanup_old_backups(self) -> int:
        """Remove old backups based on retention policy."""
        cutoff_time = time.time() - (BACKUP_RETENTION_DAYS * 86400)
        removed_count = 0
        
        to_remove = []
        
        for backup_id, record in self.records.items():
            if record.created_at < cutoff_time:
                to_remove.append(backup_id)
        
        # Keep at least some backups
        if len(to_remove) > len(self.records) - 5:
            to_remove = to_remove[:len(self.records) - 5]
        
        for backup_id in to_remove:
            record = self.records[backup_id]
            
            # Delete backup file
            try:
                backup_path = Path(record.file_path)
                if backup_path.exists():
                    backup_path.unlink()
            except Exception as e:
                log.warning("Failed to delete backup file: %s - %s", backup_id, e)
            
            # Remove record
            del self.records[backup_id]
            removed_count += 1
        
        if removed_count > 0:
            self._save_records()
            log.info("Cleaned up %d old backups", removed_count)
        
        return removed_count

    def get_backups(self) -> List[BackupRecord]:
        """Get all backup records."""
        return list(self.records.values())

    def get_backup(self, backup_id: str) -> Optional[BackupRecord]:
        """Get a specific backup record."""
        return self.records.get(backup_id)

    def start_scheduled_backups(self):
        """Start scheduled backup task."""
        self._running = True
        self._task = asyncio.create_task(self._backup_scheduler())
        log.info("Started scheduled backups (interval: %d hours)", BACKUP_INTERVAL_HOURS)

    def stop_scheduled_backups(self):
        """Stop scheduled backup task."""
        self._running = False
        if self._task:
            self._task.cancel()
        log.info("Stopped scheduled backups")

    async def _backup_scheduler(self):
        """Background task for scheduled backups."""
        while self._running:
            try:
                # Wait for next backup
                await asyncio.sleep(BACKUP_INTERVAL_HOURS * 3600)
                
                # Create backup
                record = self.create_backup(BackupType.FULL)
                await asyncio.get_event_loop().run_in_executor(
                    None, self.execute_backup, record
                )
                
                # Cleanup old backups
                await asyncio.get_event_loop().run_in_executor(
                    None, self.cleanup_old_backups
                )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Scheduled backup error: %s", e)


# ============================================================================
# FAILOVER MANAGER
# ============================================================================

class FailoverManager:
    """Manages failover and high availability."""
    
    def __init__(self):
        self.primary_server = os.environ.get("PRIMARY_SERVER", "")
        self.failover_servers = os.environ.get("FAILOVER_SERVERS", "").split(",")
        self.health_check_interval = 30
        self._is_primary = True
        self._running = False
        self._task = None
    
    async def start_health_monitor(self):
        """Start health monitoring for failover."""
        self._running = True
        self._task = asyncio.create_task(self._health_monitor())
        log.info("Started failover health monitor")
    
    async def stop_health_monitor(self):
        """Stop health monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
    
    async def _health_monitor(self):
        """Monitor server health and trigger failover if needed."""
        while self._running:
            try:
                # Check primary server health
                if self.primary_server:
                    is_healthy = await self._check_server_health(self.primary_server)
                    
                    if not is_healthy and self._is_primary:
                        log.warning("Primary server unhealthy, initiating failover")
                        await self._initiate_failover()
                
                await asyncio.sleep(self.health_check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Health monitor error: %s", e)
    
    async def _check_server_health(self, server: str) -> bool:
        """Check if a server is healthy."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{server}/health", timeout=5) as resp:
                    return resp.status == 200
        except:
            return False
    
    async def _initiate_failover(self):
        """Initiate failover to backup server."""
        for server in self.failover_servers:
            if server and await self._check_server_health(server):
                log.info("Failing over to: %s", server)
                # Update DNS or load balancer here
                self._is_primary = False
                return
        
        log.error("No healthy failover server available")


# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

backup_manager = BackupManager()
failover_manager = FailoverManager()


# ============================================================================
# API HANDLERS
# ============================================================================

async def api_create_backup(request):
    """API handler to create a backup."""
    backup_type = BackupType(request.query.get("type", "full"))
    
    record = backup_manager.create_backup(backup_type)
    success = backup_manager.execute_backup(record)
    
    if success:
        return {
            "success": True,
            "backup": record.to_dict()
        }
    return {
        "success": False,
        "error": record.error
    }

async def api_list_backups(request):
    """API handler to list backups."""
    backups = [r.to_dict() for r in backup_manager.get_backups()]
    return {
        "success": True,
        "backups": backups,
        "count": len(backups)
    }

async def api_restore_backup(request):
    """API handler to restore a backup."""
    backup_id = request.match_info.get("backup_id")
    success = backup_manager.restore_backup(backup_id)
    
    return {
        "success": success,
        "backup_id": backup_id
    }
