#!/usr/bin/env python3
"""
Abu-Zahra Upload/Download Manager
Resumable transfers, parallel transfers, transfer queue, bandwidth control.
"""

import os
import time
import uuid
import json
import asyncio
import hashlib
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import logging
import aiohttp
from aiohttp import web
import aiofiles

log = logging.getLogger("abu-zahra.transfer")

# ============================================================================
# CONFIGURATION
# ============================================================================

UPLOADS_DIR = Path(__file__).parent / "data" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

CHUNK_SIZE = 1024 * 1024  # 1MB chunks
MAX_CONCURRENT_TRANSFERS = 5
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500MB

# ============================================================================
# TRANSFER STATES
# ============================================================================

class TransferState(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TransferType(Enum):
    UPLOAD = "upload"
    DOWNLOAD = "download"

# ============================================================================
# TRANSFER MODEL
# ============================================================================

@dataclass
class Transfer:
    """Transfer operation."""
    id: str
    device_id: str
    transfer_type: str
    filename: str
    source_path: Optional[str]
    destination_path: str
    total_size: int = 0
    transferred_size: int = 0
    state: str = "pending"
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    speed_bps: float = 0
    progress: float = 0
    error: Optional[str] = None
    checksum: Optional[str] = None
    chunk_size: int = CHUNK_SIZE
    chunks_total: int = 0
    chunks_transferred: int = 0
    retry_count: int = 0
    max_retries: int = 3
    priority: int = 1
    metadata: Dict = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.total_size > 0 and self.chunk_size > 0:
            self.chunks_total = (self.total_size + self.chunk_size - 1) // self.chunk_size

# ============================================================================
# TRANSFER QUEUE
# ============================================================================

class TransferQueue:
    """Priority queue for transfers."""
    
    def __init__(self, max_concurrent: int = MAX_CONCURRENT_TRANSFERS):
        self.max_concurrent = max_concurrent
        self._queue: List[Transfer] = []
        self._active: Dict[str, Transfer] = {}
        self._lock = threading.RLock()
        self._stats = {
            "total_queued": 0,
            "total_completed": 0,
            "total_failed": 0,
            "bytes_transferred": 0
        }
    
    def enqueue(self, transfer: Transfer) -> str:
        """Add a transfer to the queue."""
        with self._lock:
            self._queue.append(transfer)
            self._queue.sort(key=lambda t: -t.priority)  # Higher priority first
            self._stats["total_queued"] += 1
        log.info("Transfer queued: %s (%s)", transfer.id, transfer.filename)
        return transfer.id
    
    def get_next(self) -> Optional[Transfer]:
        """Get next transfer to process."""
        with self._lock:
            if len(self._active) >= self.max_concurrent:
                return None
            
            for transfer in self._queue:
                if transfer.state == TransferState.PENDING.value:
                    transfer.state = TransferState.IN_PROGRESS.value
                    transfer.started_at = time.time()
                    self._active[transfer.id] = transfer
                    return transfer
            
            return None
    
    def complete(self, transfer_id: str) -> bool:
        """Mark a transfer as completed."""
        with self._lock:
            transfer = self._active.pop(transfer_id, None)
            if transfer:
                transfer.state = TransferState.COMPLETED.value
                transfer.completed_at = time.time()
                transfer.progress = 100.0
                self._stats["total_completed"] += 1
                self._stats["bytes_transferred"] += transfer.transferred_size
                return True
            return False
    
    def fail(self, transfer_id: str, error: str) -> bool:
        """Mark a transfer as failed."""
        with self._lock:
            transfer = self._active.pop(transfer_id, None)
            if transfer:
                transfer.state = TransferState.FAILED.value
                transfer.error = error
                transfer.completed_at = time.time()
                self._stats["total_failed"] += 1
                return True
            return False
    
    def pause(self, transfer_id: str) -> bool:
        """Pause a transfer."""
        with self._lock:
            if transfer_id in self._active:
                self._active[transfer_id].state = TransferState.PAUSED.value
                return True
            return False
    
    def resume(self, transfer_id: str) -> bool:
        """Resume a paused transfer."""
        with self._lock:
            for transfer in self._queue:
                if transfer.id == transfer_id and transfer.state == TransferState.PAUSED.value:
                    transfer.state = TransferState.PENDING.value
                    return True
            return False
    
    def cancel(self, transfer_id: str) -> bool:
        """Cancel a transfer."""
        with self._lock:
            # Check active
            transfer = self._active.pop(transfer_id, None)
            if transfer:
                transfer.state = TransferState.CANCELLED.value
                return True
            
            # Check queue
            for i, transfer in enumerate(self._queue):
                if transfer.id == transfer_id:
                    transfer.state = TransferState.CANCELLED.value
                    return True
            
            return False
    
    def get_transfer(self, transfer_id: str) -> Optional[Transfer]:
        """Get a transfer by ID."""
        with self._lock:
            if transfer_id in self._active:
                return self._active[transfer_id]
            for transfer in self._queue:
                if transfer.id == transfer_id:
                    return transfer
            return None
    
    def get_active_count(self) -> int:
        """Get count of active transfers."""
        return len(self._active)
    
    def get_pending_count(self) -> int:
        """Get count of pending transfers."""
        with self._lock:
            return sum(1 for t in self._queue if t.state == TransferState.PENDING.value)
    
    def get_stats(self) -> Dict:
        """Get queue statistics."""
        with self._lock:
            return {
                **self._stats,
                "active": len(self._active),
                "pending": self.get_pending_count(),
                "max_concurrent": self.max_concurrent
            }

# ============================================================================
# UPLOAD MANAGER
# ============================================================================

class UploadManager:
    """Manages file uploads with resumable support."""
    
    def __init__(self, upload_dir: Path = None):
        self.upload_dir = upload_dir or UPLOADS_DIR
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self._uploads: Dict[str, Dict] = {}
        self._lock = threading.RLock()
    
    def create_upload_session(
        self,
        device_id: str,
        filename: str,
        total_size: int,
        checksum: str = None,
        chunk_size: int = CHUNK_SIZE
    ) -> Dict:
        """Create a new upload session."""
        upload_id = str(uuid.uuid4())
        
        # Create device upload directory
        device_dir = self.upload_dir / device_id
        device_dir.mkdir(parents=True, exist_ok=True)
        
        # Create temp file for upload
        temp_path = device_dir / f"{upload_id}.tmp"
        final_path = device_dir / filename
        
        upload_info = {
            "id": upload_id,
            "device_id": device_id,
            "filename": filename,
            "total_size": total_size,
            "transferred_size": 0,
            "chunk_size": chunk_size,
            "chunks_total": (total_size + chunk_size - 1) // chunk_size if total_size > 0 else 0,
            "chunks_received": [],
            "temp_path": str(temp_path),
            "final_path": str(final_path),
            "checksum": checksum,
            "created_at": time.time(),
            "updated_at": time.time(),
            "state": "pending"
        }
        
        with self._lock:
            self._uploads[upload_id] = upload_info
        
        log.info("Created upload session: %s (size=%d)", upload_id, total_size)
        return upload_info
    
    async def receive_chunk(
        self,
        upload_id: str,
        chunk_index: int,
        chunk_data: bytes
    ) -> Dict:
        """Receive and store a chunk."""
        with self._lock:
            upload = self._uploads.get(upload_id)
            if not upload:
                raise ValueError(f"Upload session not found: {upload_id}")
        
        # Validate chunk index
        if chunk_index < 0 or (upload["chunks_total"] > 0 and chunk_index >= upload["chunks_total"]):
            raise ValueError(f"Invalid chunk index: {chunk_index}")
        
        # Calculate offset
        offset = chunk_index * upload["chunk_size"]
        
        # Write chunk to temp file
        temp_path = Path(upload["temp_path"])
        async with aiofiles.open(temp_path, "r+b" if temp_path.exists() else "wb") as f:
            await f.seek(offset)
            await f.write(chunk_data)
        
        # Update upload info
        with self._lock:
            if chunk_index not in upload["chunks_received"]:
                upload["chunks_received"].append(chunk_index)
                upload["transferred_size"] += len(chunk_data)
                upload["updated_at"] = time.time()
            
            upload["state"] = "in_progress"
            
            # Check if complete
            if upload["chunks_total"] > 0 and len(upload["chunks_received"]) >= upload["chunks_total"]:
                upload["state"] = "complete"
        
        return {
            "upload_id": upload_id,
            "chunk_index": chunk_index,
            "chunks_received": len(upload["chunks_received"]),
            "chunks_total": upload["chunks_total"],
            "progress": len(upload["chunks_received"]) / upload["chunks_total"] * 100 if upload["chunks_total"] > 0 else 0,
            "state": upload["state"]
        }
    
    async def finalize_upload(self, upload_id: str) -> Dict:
        """Finalize an upload and move to final location."""
        with self._lock:
            upload = self._uploads.get(upload_id)
            if not upload:
                raise ValueError(f"Upload session not found: {upload_id}")
            
            if upload["state"] != "complete":
                raise ValueError("Upload not complete")
        
        temp_path = Path(upload["temp_path"])
        final_path = Path(upload["final_path"])
        
        # Verify checksum if provided
        if upload["checksum"]:
            actual_checksum = await self._calculate_checksum(temp_path)
            if actual_checksum != upload["checksum"]:
                temp_path.unlink()
                raise ValueError("Checksum mismatch")
        
        # Move to final location
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.rename(final_path)
        
        # Update state
        with self._lock:
            upload["state"] = "finalized"
            upload["final_path"] = str(final_path)
        
        log.info("Upload finalized: %s -> %s", upload_id, final_path)
        
        return {
            "upload_id": upload_id,
            "filename": upload["filename"],
            "size": upload["total_size"],
            "path": str(final_path),
            "checksum": upload["checksum"]
        }
    
    async def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of a file."""
        sha256 = hashlib.sha256()
        async with aiofiles.open(file_path, "rb") as f:
            while True:
                chunk = await f.read(8192)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def get_upload(self, upload_id: str) -> Optional[Dict]:
        """Get upload session info."""
        return self._uploads.get(upload_id)
    
    def cancel_upload(self, upload_id: str) -> bool:
        """Cancel an upload."""
        with self._lock:
            upload = self._uploads.pop(upload_id, None)
            if upload:
                # Delete temp file
                temp_path = Path(upload["temp_path"])
                if temp_path.exists():
                    temp_path.unlink()
                return True
            return False
    
    def cleanup_expired(self, max_age_hours: int = 24) -> int:
        """Clean up expired upload sessions."""
        cutoff = time.time() - (max_age_hours * 3600)
        cleaned = 0
        
        with self._lock:
            to_remove = [
                uid for uid, upload in self._uploads.items()
                if upload["updated_at"] < cutoff and upload["state"] != "finalized"
            ]
            
            for uid in to_remove:
                self.cancel_upload(uid)
                cleaned += 1
        
        if cleaned > 0:
            log.info("Cleaned up %d expired uploads", cleaned)
        
        return cleaned

# ============================================================================
# DOWNLOAD MANAGER
# ============================================================================

class DownloadManager:
    """Manages file downloads with resumable support."""
    
    def __init__(self):
        self._downloads: Dict[str, Transfer] = {}
        self._lock = threading.RLock()
    
    async def download_file(
        self,
        url: str,
        destination: Path,
        transfer_id: str = None,
        headers: Dict = None,
        progress_callback: Callable = None
    ) -> Transfer:
        """Download a file with progress tracking."""
        transfer_id = transfer_id or str(uuid.uuid4())
        
        transfer = Transfer(
            id=transfer_id,
            device_id="system",
            transfer_type=TransferType.DOWNLOAD.value,
            filename=destination.name,
            source_path=url,
            destination_path=str(destination),
            state=TransferState.IN_PROGRESS.value,
            started_at=time.time()
        )
        
        with self._lock:
            self._downloads[transfer_id] = transfer
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        raise ValueError(f"Download failed: HTTP {response.status}")
                    
                    transfer.total_size = int(response.headers.get("Content-Length", 0))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    
                    async with aiofiles.open(destination, "wb") as f:
                        async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                            await f.write(chunk)
                            transfer.transferred_size += len(chunk)
                            
                            if transfer.total_size > 0:
                                transfer.progress = (transfer.transferred_size / transfer.total_size) * 100
                            
                            if progress_callback:
                                await progress_callback(transfer)
            
            transfer.state = TransferState.COMPLETED.value
            transfer.completed_at = time.time()
            
        except Exception as e:
            transfer.state = TransferState.FAILED.value
            transfer.error = str(e)
            log.error("Download failed: %s - %s", transfer_id, e)
        
        return transfer
    
    def get_download(self, transfer_id: str) -> Optional[Transfer]:
        """Get download info."""
        return self._downloads.get(transfer_id)

# ============================================================================
# BANDWIDTH CONTROLLER
# ============================================================================

class BandwidthController:
    """Controls bandwidth usage for transfers."""
    
    def __init__(self, max_bps: int = 10 * 1024 * 1024):  # 10 MB/s default
        self.max_bps = max_bps
        self._current_usage = 0
        self._tokens = max_bps
        self._last_update = time.time()
        self._lock = threading.Lock()
    
    def acquire(self, bytes_needed: int) -> float:
        """Acquire bandwidth tokens. Returns wait time in seconds."""
        with self._lock:
            now = time.time()
            elapsed = now - self._last_update
            
            # Refill tokens
            self._tokens = min(self.max_bps, self._tokens + elapsed * self.max_bps)
            self._last_update = now
            
            if bytes_needed <= self._tokens:
                self._tokens -= bytes_needed
                return 0
            
            # Need to wait
            wait_time = (bytes_needed - self._tokens) / self.max_bps
            self._tokens = 0
            return wait_time
    
    def set_limit(self, max_bps: int):
        """Set bandwidth limit."""
        with self._lock:
            self.max_bps = max_bps
            self._tokens = min(self._tokens, max_bps)

# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

transfer_queue = TransferQueue()
upload_manager = UploadManager()
download_manager = DownloadManager()
bandwidth_controller = BandwidthController()

# ============================================================================
# API HANDLERS
# ============================================================================

async def handle_chunk_upload(request: web.Request) -> web.Response:
    """Handle chunk upload request."""
    try:
        device_id = request.match_info.get("device_id")
        upload_id = request.match_info.get("upload_id")
        chunk_index = int(request.query.get("chunk", "0"))
        
        # Read chunk data
        chunk_data = await request.read()
        
        # Receive chunk
        result = await upload_manager.receive_chunk(upload_id, chunk_index, chunk_data)
        
        return web.json_response({"ok": True, **result})
    
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)

async def handle_upload_finalize(request: web.Request) -> web.Response:
    """Handle upload finalization."""
    try:
        upload_id = request.match_info.get("upload_id")
        result = await upload_manager.finalize_upload(upload_id)
        return web.json_response({"ok": True, **result})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)

async def handle_upload_status(request: web.Request) -> web.Response:
    """Get upload status."""
    upload_id = request.match_info.get("upload_id")
    upload = upload_manager.get_upload(upload_id)
    
    if not upload:
        return web.json_response({"ok": False, "error": "Upload not found"}, status=404)
    
    return web.json_response({"ok": True, "upload": upload})

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_upload_session(
    device_id: str,
    filename: str,
    total_size: int,
    checksum: str = None
) -> Dict:
    """Create a new upload session."""
    return upload_manager.create_upload_session(device_id, filename, total_size, checksum)

async def upload_chunk(upload_id: str, chunk_index: int, chunk_data: bytes) -> Dict:
    """Upload a chunk."""
    return await upload_manager.receive_chunk(upload_id, chunk_index, chunk_data)

def get_transfer_status(transfer_id: str) -> Optional[Dict]:
    """Get transfer status."""
    transfer = transfer_queue.get_transfer(transfer_id)
    if transfer:
        return {
            "id": transfer.id,
            "state": transfer.state,
            "progress": transfer.progress,
            "transferred_size": transfer.transferred_size,
            "total_size": transfer.total_size,
            "speed_bps": transfer.speed_bps,
            "error": transfer.error
        }
    return None
