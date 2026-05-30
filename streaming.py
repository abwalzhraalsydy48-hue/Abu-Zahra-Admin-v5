#!/usr/bin/env python3
"""
Abu-Zahra Streaming Engine
WebRTC, HLS, and RTMP support for live streaming and screen recording.
"""

import asyncio
import time
import uuid
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import logging
import base64
import hashlib

log = logging.getLogger("abu-zahra.stream")

# ============================================================================
# CONFIGURATION
# ============================================================================

RECORDINGS_DIR = Path(__file__).parent / "data" / "recordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# STREAM TYPES
# ============================================================================

class StreamType(Enum):
    SCREEN = "screen"
    CAMERA = "camera"
    AUDIO = "audio"
    LOCATION = "location"

class StreamState(Enum):
    PENDING = "pending"
    STARTING = "starting"
    LIVE = "live"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"

class StreamProtocol(Enum):
    HLS = "hls"
    WEBRTC = "webrtc"
    RTMP = "rtmp"
    CHUNKED = "chunked"  # For simple chunked upload

# ============================================================================
# STREAM MODEL
# ============================================================================

@dataclass
class StreamSession:
    id: str
    device_id: str
    stream_type: str
    protocol: str
    state: str = "pending"
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    stopped_at: Optional[float] = None
    duration: int = 0
    output_path: Optional[str] = None
    playlist_url: Optional[str] = None
    chunk_count: int = 0
    total_size: int = 0
    metadata: Dict = field(default_factory=dict)
    subscribers: List[str] = field(default_factory=list)
    config: Dict = field(default_factory=dict)
    error: Optional[str] = None
    
    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())

# ============================================================================
# STREAMING MANAGER
# ============================================================================

class StreamingManager:
    """Manages live streaming sessions."""
    
    def __init__(self):
        self._sessions: Dict[str, StreamSession] = {}
        self._device_sessions: Dict[str, str] = {}  # device_id -> session_id
        self._lock = threading.RLock()
        self._chunk_handlers: Dict[str, Callable] = {}
    
    def create_session(
        self,
        device_id: str,
        stream_type: str,
        protocol: str = "chunked",
        config: Dict = None
    ) -> StreamSession:
        """Create a new streaming session."""
        with self._lock:
            # Check if device already has active session
            if device_id in self._device_sessions:
                existing_id = self._device_sessions[device_id]
                existing = self._sessions.get(existing_id)
                if existing and existing.state == StreamState.LIVE.value:
                    raise ValueError(f"Device {device_id} already has an active stream")
            
            session = StreamSession(
                id=str(uuid.uuid4()),
                device_id=device_id,
                stream_type=stream_type,
                protocol=protocol,
                config=config or {}
            )
            
            self._sessions[session.id] = session
            self._device_sessions[device_id] = session.id
            
            log.info("Created stream session: %s (device=%s, type=%s)",
                     session.id, device_id, stream_type)
            
            return session
    
    def start_session(self, session_id: str) -> bool:
        """Mark session as live."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            
            session.state = StreamState.LIVE.value
            session.started_at = time.time()
            
            # Create output directory
            output_dir = RECORDINGS_DIR / session.device_id / session_id
            output_dir.mkdir(parents=True, exist_ok=True)
            session.output_path = str(output_dir)
            
            log.info("Stream session started: %s", session_id)
            return True
    
    def stop_session(self, session_id: str) -> Optional[StreamSession]:
        """Stop a streaming session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            
            session.state = StreamState.STOPPED.value
            session.stopped_at = time.time()
            
            if session.started_at:
                session.duration = int(session.stopped_at - session.started_at)
            
            # Remove from device sessions
            if session.device_id in self._device_sessions:
                if self._device_sessions[session.device_id] == session_id:
                    del self._device_sessions[session.device_id]
            
            log.info("Stream session stopped: %s (duration=%ds)", session_id, session.duration)
            return session
    
    def get_session(self, session_id: str) -> Optional[StreamSession]:
        """Get a session by ID."""
        return self._sessions.get(session_id)
    
    def get_device_session(self, device_id: str) -> Optional[StreamSession]:
        """Get active session for a device."""
        with self._lock:
            session_id = self._device_sessions.get(device_id)
            if session_id:
                return self._sessions.get(session_id)
            return None
    
    def add_chunk(self, session_id: str, chunk_data: bytes, chunk_num: int = None) -> Dict:
        """Add a chunk to the stream."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise ValueError(f"Session not found: {session_id}")
            
            if session.state != StreamState.LIVE.value:
                raise ValueError(f"Session is not live: {session_id}")
            
            # Generate chunk filename
            if chunk_num is None:
                chunk_num = session.chunk_count
            
            # Determine file extension based on stream type
            ext = ".dat"
            if session.stream_type == StreamType.SCREEN.value:
                ext = ".mp4"
            elif session.stream_type == StreamType.AUDIO.value:
                ext = ".m4a"
            elif session.stream_type == StreamType.CAMERA.value:
                ext = ".jpg" if session.config.get("mode") == "photo" else ".mp4"
            
            chunk_filename = f"chunk_{chunk_num:06d}{ext}"
            chunk_path = Path(session.output_path) / chunk_filename
            
            # Save chunk
            chunk_path.write_bytes(chunk_data)
            
            # Update session
            session.chunk_count += 1
            session.total_size += len(chunk_data)
            
            log.debug("Added chunk %d to session %s (size=%d)", 
                     chunk_num, session_id, len(chunk_data))
            
            return {
                "chunk_num": chunk_num,
                "chunk_path": str(chunk_path),
                "size": len(chunk_data),
                "total_chunks": session.chunk_count,
                "total_size": session.total_size
            }
    
    def add_subscriber(self, session_id: str, subscriber_id: str) -> bool:
        """Add a subscriber to a stream."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            
            if subscriber_id not in session.subscribers:
                session.subscribers.append(subscriber_id)
            
            return True
    
    def remove_subscriber(self, session_id: str, subscriber_id: str) -> bool:
        """Remove a subscriber from a stream."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            
            if subscriber_id in session.subscribers:
                session.subscribers.remove(subscriber_id)
            
            return True
    
    def finalize_stream(self, session_id: str) -> Optional[Dict]:
        """Finalize a stream and create output file."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            
            if not session.output_path or session.chunk_count == 0:
                return None
            
            output_dir = Path(session.output_path)
            
            # Find all chunks and sort
            chunks = sorted(output_dir.glob("chunk_*"))
            
            if not chunks:
                return None
            
            # Determine output file
            timestamp = datetime.fromtimestamp(session.created_at).strftime("%Y%m%d_%H%M%S")
            ext = ".mp4"
            if session.stream_type == StreamType.AUDIO.value:
                ext = ".m4a"
            
            output_filename = f"{session.stream_type}_{timestamp}{ext}"
            output_path = output_dir / output_filename
            
            # Concatenate chunks (for video/audio)
            if session.stream_type in (StreamType.SCREEN.value, StreamType.CAMERA.value, StreamType.AUDIO.value):
                # Create concat file for ffmpeg
                concat_file = output_dir / "concat.txt"
                with open(concat_file, "w") as f:
                    for chunk in chunks:
                        f.write(f"file '{chunk.name}'\n")
                
                # Use ffmpeg to concatenate
                try:
                    result = subprocess.run([
                        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(concat_file),
                        "-c", "copy",
                        str(output_path)
                    ], capture_output=True, timeout=300)
                    
                    if result.returncode == 0:
                        # Cleanup chunks
                        for chunk in chunks:
                            chunk.unlink()
                        concat_file.unlink()
                        
                        session.metadata["final_output"] = str(output_path)
                        log.info("Finalized stream: %s -> %s", session_id, output_path)
                    else:
                        log.error("FFmpeg error: %s", result.stderr.decode())
                except Exception as e:
                    log.error("Finalization error: %s", e)
            
            return {
                "session_id": session_id,
                "output_file": str(output_path),
                "duration": session.duration,
                "size": output_path.stat().st_size if output_path.exists() else session.total_size,
                "chunks": session.chunk_count
            }
    
    def get_stats(self) -> Dict:
        """Get streaming statistics."""
        with self._lock:
            active = sum(1 for s in self._sessions.values() if s.state == StreamState.LIVE.value)
            total = len(self._sessions)
            
            return {
                "total_sessions": total,
                "active_sessions": active,
                "device_sessions": len(self._device_sessions)
            }
    
    def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """Clean up old stopped sessions."""
        cutoff = time.time() - (max_age_hours * 3600)
        cleaned = 0
        
        with self._lock:
            to_remove = []
            for session_id, session in self._sessions.items():
                if (session.state == StreamState.STOPPED.value and 
                    session.stopped_at and session.stopped_at < cutoff):
                    to_remove.append(session_id)
            
            for session_id in to_remove:
                del self._sessions[session_id]
                cleaned += 1
        
        if cleaned > 0:
            log.info("Cleaned up %d old stream sessions", cleaned)
        
        return cleaned

# ============================================================================
# HLS GENERATOR
# ============================================================================

class HLSGenerator:
    """Generates HLS playlists for live streaming."""
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.segment_duration = 2  # seconds
        self.playlist_path = output_dir / "stream.m3u8"
    
    def create_playlist(self, segments: List[str]) -> str:
        """Create HLS playlist."""
        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{self.segment_duration}",
            "#EXT-X-PLAYLIST-TYPE:EVENT"
        ]
        
        for i, segment in enumerate(segments):
            lines.append(f"#EXTINF:{self.segment_duration}.0,")
            lines.append(segment)
        
        playlist_content = "\n".join(lines)
        self.playlist_path.write_text(playlist_content)
        
        return str(self.playlist_path)
    
    def add_segment(self, segment_file: str, is_last: bool = False) -> str:
        """Add a segment to the playlist."""
        # Read existing playlist
        if self.playlist_path.exists():
            content = self.playlist_path.read_text()
            lines = content.strip().split("\n")
            
            # Remove end tag if present
            if lines and lines[-1].startswith("#EXT-X-ENDLIST"):
                lines = lines[:-1]
        else:
            lines = [
                "#EXTM3U",
                "#EXT-X-VERSION:3",
                f"#EXT-X-TARGETDURATION:{self.segment_duration}",
                "#EXT-X-PLAYLIST-TYPE:EVENT"
            ]
        
        # Add new segment
        lines.append(f"#EXTINF:{self.segment_duration}.0,")
        lines.append(segment_file)
        
        if is_last:
            lines.append("#EXT-X-ENDLIST")
        
        # Write updated playlist
        self.playlist_path.write_text("\n".join(lines))
        
        return str(self.playlist_path)
    
    def finalize(self):
        """Mark playlist as complete."""
        if self.playlist_path.exists():
            content = self.playlist_path.read_text()
            if "#EXT-X-ENDLIST" not in content:
                with open(self.playlist_path, "a") as f:
                    f.write("\n#EXT-X-ENDLIST\n")

# ============================================================================
# WEBRTC SIGNALING
# ============================================================================

class WebRTCSignaling:
    """WebRTC signaling server for peer connections."""
    
    def __init__(self):
        self._peers: Dict[str, Dict] = {}
        self._rooms: Dict[str, List[str]] = {}
        self._lock = threading.RLock()
    
    def create_room(self, room_id: str = None) -> str:
        """Create a new room."""
        room_id = room_id or str(uuid.uuid4())
        with self._lock:
            self._rooms[room_id] = []
        return room_id
    
    def join_room(self, room_id: str, peer_id: str, ws_send: Callable) -> bool:
        """Add a peer to a room."""
        with self._lock:
            if room_id not in self._rooms:
                return False
            
            self._rooms[room_id].append(peer_id)
            self._peers[peer_id] = {
                "room_id": room_id,
                "ws_send": ws_send
            }
            
            # Notify other peers
            for other_peer_id in self._rooms[room_id]:
                if other_peer_id != peer_id:
                    self._send_to_peer(other_peer_id, {
                        "type": "peer_joined",
                        "peer_id": peer_id
                    })
            
            return True
    
    def leave_room(self, peer_id: str):
        """Remove a peer from their room."""
        with self._lock:
            peer = self._peers.pop(peer_id, None)
            if peer:
                room_id = peer["room_id"]
                if room_id in self._rooms:
                    if peer_id in self._rooms[room_id]:
                        self._rooms[room_id].remove(peer_id)
                    
                    # Notify other peers
                    for other_peer_id in self._rooms[room_id]:
                        self._send_to_peer(other_peer_id, {
                            "type": "peer_left",
                            "peer_id": peer_id
                        })
    
    def relay_message(self, from_peer_id: str, to_peer_id: str, message: Dict):
        """Relay a message between peers."""
        self._send_to_peer(to_peer_id, {
            "type": "relay",
            "from_peer_id": from_peer_id,
            "data": message
        })
    
    def _send_to_peer(self, peer_id: str, message: Dict):
        """Send a message to a peer."""
        peer = self._peers.get(peer_id)
        if peer and peer.get("ws_send"):
            try:
                ws_send = peer["ws_send"]
                if asyncio.iscoroutinefunction(ws_send):
                    asyncio.create_task(ws_send(json.dumps(message)))
                else:
                    ws_send(json.dumps(message))
            except Exception as e:
                log.warning("Failed to send to peer %s: %s", peer_id, e)

# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

streaming_manager = StreamingManager()
webrtc_signaling = WebRTCSignaling()

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_stream_session(
    device_id: str,
    stream_type: str,
    protocol: str = "chunked",
    config: Dict = None
) -> StreamSession:
    """Create a new streaming session."""
    return streaming_manager.create_session(device_id, stream_type, protocol, config)

def get_stream_url(session: StreamSession) -> Optional[str]:
    """Get the URL for a stream session."""
    if session.protocol == StreamProtocol.HLS.value:
        return session.playlist_url
    elif session.protocol == StreamProtocol.WEBRTC.value:
        return f"webrtc://stream/{session.id}"
    elif session.protocol == StreamProtocol.CHUNKED.value:
        return f"/api/stream/{session.id}/chunks"
    return None
