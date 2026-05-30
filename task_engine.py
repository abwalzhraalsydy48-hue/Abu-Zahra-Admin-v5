#!/usr/bin/env python3
"""
Abu-Zahra Async Task Engine
Background workers for heavy operations: file uploads, backups, screen recording.
"""

import asyncio
import time
import uuid
import json
import threading
import queue
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
import logging
import traceback

log = logging.getLogger("abu-zahra.tasks")

# ============================================================================
# TASK STATES
# ============================================================================

class TaskState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"

class TaskPriority(Enum):
    CRITICAL = 3
    HIGH = 2
    NORMAL = 1
    LOW = 0

# ============================================================================
# TASK MODEL
# ============================================================================

@dataclass
class Task:
    id: str
    name: str
    task_type: str
    device_id: Optional[str]
    params: Dict
    state: str = "pending"
    priority: int = 1
    progress: float = 0.0
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Dict] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    timeout: int = 300
    callback_url: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())

# ============================================================================
# TASK REGISTRY
# ============================================================================

TASK_HANDLERS: Dict[str, Callable] = {}

def register_task_handler(task_type: str):
    """Decorator to register a task handler."""
    def decorator(func):
        TASK_HANDLERS[task_type] = func
        log.info("Registered task handler: %s", task_type)
        return func
    return decorator

# ============================================================================
# TASK QUEUE
# ============================================================================

class TaskQueue:
    """Priority-based task queue."""
    
    def __init__(self, max_size: int = 10000):
        self._queues: Dict[int, queue.PriorityQueue] = {
            3: queue.PriorityQueue(maxsize=max_size),  # CRITICAL
            2: queue.PriorityQueue(maxsize=max_size),  # HIGH
            1: queue.PriorityQueue(maxsize=max_size),  # NORMAL
            0: queue.PriorityQueue(maxsize=max_size),  # LOW
        }
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.RLock()
        self._stats = {
            "total_enqueued": 0,
            "total_completed": 0,
            "total_failed": 0
        }
    
    def enqueue(self, task: Task) -> bool:
        """Add a task to the queue."""
        with self._lock:
            priority = task.priority
            if priority not in self._queues:
                priority = 1
            
            # Priority queue uses (priority, counter, task) for ordering
            # Lower number = higher priority
            self._queues[priority].put((time.time(), task))
            self._tasks[task.id] = task
            self._stats["total_enqueued"] += 1
            log.debug("Task enqueued: %s (priority=%d)", task.id, priority)
            return True
    
    def dequeue(self, timeout: float = 1.0) -> Optional[Task]:
        """Get the next task from the queue (priority order)."""
        # Check queues in priority order
        for priority in [3, 2, 1, 0]:
            try:
                _, task = self._queues[priority].get(timeout=0.1)
                return task
            except queue.Empty:
                continue
        
        return None
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        with self._lock:
            return self._tasks.get(task_id)
    
    def update_task(self, task: Task) -> None:
        """Update a task."""
        with self._lock:
            self._tasks[task.id] = task
    
    def remove_task(self, task_id: str) -> Optional[Task]:
        """Remove a task."""
        with self._lock:
            return self._tasks.pop(task_id, None)
    
    def get_pending_count(self) -> int:
        """Get count of pending tasks."""
        count = 0
        for q in self._queues.values():
            count += q.qsize()
        return count
    
    def get_stats(self) -> Dict:
        """Get queue statistics."""
        return {
            **self._stats,
            "pending_tasks": self.get_pending_count(),
            "total_tracked": len(self._tasks)
        }

# ============================================================================
# TASK EXECUTOR
# ============================================================================

class TaskExecutor:
    """Executes tasks using a thread pool."""
    
    def __init__(self, max_workers: int = 4, task_queue: TaskQueue = None):
        self.max_workers = max_workers
        self.task_queue = task_queue or TaskQueue()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._active = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
    
    async def start(self):
        """Start the task executor."""
        self._active = True
        self._loop = asyncio.get_event_loop()
        log.info("Task executor started with %d workers", self.max_workers)
        
        # Start worker tasks
        for i in range(self.max_workers):
            asyncio.create_task(self._worker(i))
    
    async def stop(self):
        """Stop the task executor."""
        self._active = False
        self._executor.shutdown(wait=True)
        log.info("Task executor stopped")
    
    async def _worker(self, worker_id: int):
        """Worker coroutine that processes tasks."""
        log.info("Task worker %d started", worker_id)
        
        while self._active:
            try:
                task = self.task_queue.dequeue(timeout=1.0)
                if task is None:
                    await asyncio.sleep(0.5)
                    continue
                
                # Execute task
                await self._execute_task(task)
                
            except Exception as e:
                log.error("Worker %d error: %s", worker_id, e)
                await asyncio.sleep(1)
    
    async def _execute_task(self, task: Task):
        """Execute a single task."""
        try:
            task.state = TaskState.RUNNING.value
            task.started_at = time.time()
            self.task_queue.update_task(task)
            
            log.info("Executing task: %s (type=%s)", task.id, task.task_type)
            
            # Get handler
            handler = TASK_HANDLERS.get(task.task_type)
            if handler is None:
                raise ValueError(f"No handler for task type: {task.task_type}")
            
            # Execute with timeout
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await asyncio.wait_for(
                        handler(task),
                        timeout=task.timeout
                    )
                else:
                    result = await self._loop.run_in_executor(
                        self._executor,
                        lambda: handler(task)
                    )
            except asyncio.TimeoutError:
                task.state = TaskState.TIMEOUT.value
                task.error = "Task timed out"
                self.task_queue._stats["total_failed"] += 1
                self.task_queue.update_task(task)
                log.warning("Task timed out: %s", task.id)
                return
            
            # Success
            task.state = TaskState.COMPLETED.value
            task.result = result
            task.completed_at = time.time()
            task.progress = 100.0
            self.task_queue._stats["total_completed"] += 1
            self.task_queue.update_task(task)
            
            log.info("Task completed: %s (duration=%.2fs)", 
                     task.id, task.completed_at - task.started_at)
            
            # Callback
            if task.callback_url:
                asyncio.create_task(self._send_callback(task))
            
        except Exception as e:
            task.state = TaskState.FAILED.value
            task.error = str(e)
            task.completed_at = time.time()
            
            # Retry logic
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                task.state = TaskState.PENDING.value
                log.warning("Task failed, retrying (%d/%d): %s - %s",
                           task.retry_count, task.max_retries, task.id, e)
                self.task_queue.enqueue(task)
            else:
                self.task_queue._stats["total_failed"] += 1
                log.error("Task failed permanently: %s - %s", task.id, e)
            
            self.task_queue.update_task(task)
    
    async def _send_callback(self, task: Task):
        """Send callback notification."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(task.callback_url, json={
                    "task_id": task.id,
                    "state": task.state,
                    "result": task.result,
                    "error": task.error
                })
        except Exception as e:
            log.warning("Callback failed: %s", e)
    
    def submit(self, task: Task) -> str:
        """Submit a task for execution."""
        self.task_queue.enqueue(task)
        return task.id
    
    def get_status(self, task_id: str) -> Optional[Dict]:
        """Get task status."""
        task = self.task_queue.get_task(task_id)
        if task:
            return {
                "id": task.id,
                "name": task.name,
                "type": task.task_type,
                "state": task.state,
                "progress": task.progress,
                "created_at": task.created_at,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
                "result": task.result,
                "error": task.error,
                "retry_count": task.retry_count
            }
        return None

# ============================================================================
# BUILT-IN TASK HANDLERS
# ============================================================================

@register_task_handler("file_upload")
async def handle_file_upload(task: Task):
    """Handle file upload task."""
    params = task.params
    device_id = task.device_id
    file_path = params.get("file_path")
    
    log.info("Processing file upload: %s from device %s", file_path, device_id)
    
    # Simulate file processing
    await asyncio.sleep(2)
    
    # Update progress
    task.progress = 50.0
    task.metadata["stage"] = "processing"
    
    # Final result
    return {
        "file_path": file_path,
        "uploaded": True,
        "size": params.get("file_size", 0),
        "storage_path": f"/uploads/{device_id}/{file_path}"
    }

@register_task_handler("backup_create")
async def handle_backup_create(task: Task):
    """Handle backup creation task."""
    device_id = task.device_id
    backup_type = task.params.get("backup_type", "full")
    
    log.info("Creating %s backup for device %s", backup_type, device_id)
    
    # Simulate backup process
    stages = ["collecting_data", "compressing", "uploading"]
    for i, stage in enumerate(stages):
        await asyncio.sleep(1)
        task.progress = (i + 1) / len(stages) * 100
        task.metadata["stage"] = stage
    
    return {
        "backup_type": backup_type,
        "backup_id": str(uuid.uuid4()),
        "created_at": time.time(),
        "size_bytes": 1024 * 1024 * 50  # 50MB placeholder
    }

@register_task_handler("screen_record_process")
async def handle_screen_record(task: Task):
    """Handle screen recording processing."""
    device_id = task.device_id
    duration = task.params.get("duration", 0)
    
    log.info("Processing screen recording from device %s", device_id)
    
    # Simulate video processing
    await asyncio.sleep(2)
    
    return {
        "video_path": f"/recordings/{device_id}/{time.time()}.mp4",
        "duration": duration,
        "processed": True
    }

@register_task_handler("data_sync")
async def handle_data_sync(task: Task):
    """Handle data synchronization task."""
    device_id = task.device_id
    data_types = task.params.get("data_types", ["sms", "calls", "contacts"])
    
    log.info("Syncing data for device %s: %s", device_id, data_types)
    
    results = {}
    for data_type in data_types:
        await asyncio.sleep(0.5)
        results[data_type] = {"synced": True, "count": 0}
        task.progress += 100 / len(data_types)
    
    return {
        "synced_types": list(results.keys()),
        "results": results
    }

@register_task_handler("notification_batch")
async def handle_notification_batch(task: Task):
    """Handle batch notification sending."""
    notifications = task.params.get("notifications", [])
    
    log.info("Processing %d notifications", len(notifications))
    
    sent = 0
    failed = 0
    
    for notif in notifications:
        await asyncio.sleep(0.1)
        sent += 1
        task.progress = sent / len(notifications) * 100
    
    return {
        "total": len(notifications),
        "sent": sent,
        "failed": failed
    }

# ============================================================================
# GLOBAL TASK ENGINE
# ============================================================================

task_queue = TaskQueue()
task_executor = TaskExecutor(max_workers=4, task_queue=task_queue)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_task(
    name: str,
    task_type: str,
    params: Dict,
    device_id: str = None,
    priority: int = 1,
    timeout: int = 300,
    callback_url: str = None
) -> Task:
    """Create and submit a new task."""
    task = Task(
        id=str(uuid.uuid4()),
        name=name,
        task_type=task_type,
        device_id=device_id,
        params=params,
        priority=priority,
        timeout=timeout,
        callback_url=callback_url
    )
    task_executor.submit(task)
    return task

async def init_task_engine():
    """Initialize the task engine."""
    await task_executor.start()

async def stop_task_engine():
    """Stop the task engine."""
    await task_executor.stop()
