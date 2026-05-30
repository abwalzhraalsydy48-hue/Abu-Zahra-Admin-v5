#!/usr/bin/env python3
"""
Abu-Zahra Workflow Automation Engine
Triggers, schedules, and chained actions for automated device management.
"""

import asyncio
import time
import uuid
import json
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from enum import Enum
import logging
import re

log = logging.getLogger("abu-zahra.workflow")

# ============================================================================
# TRIGGER TYPES
# ============================================================================

class TriggerType(Enum):
    SCHEDULE = "schedule"          # Time-based trigger
    EVENT = "event"                # Event-based trigger
    CONDITION = "condition"        # Condition-based trigger
    GEO_FENCE = "geo_fence"        # Location-based trigger
    THRESHOLD = "threshold"        # Metric threshold trigger

class ScheduleType(Enum):
    ONCE = "once"                  # One-time execution
    INTERVAL = "interval"          # Recurring interval
    DAILY = "daily"                # Daily at specific time
    WEEKLY = "weekly"              # Weekly on specific days
    CRON = "cron"                  # Cron expression

# ============================================================================
# ACTION TYPES
# ============================================================================

class ActionType(Enum):
    COMMAND = "command"            # Execute a command
    NOTIFICATION = "notification"  # Send notification
    WEBHOOK = "webhook"           # Call webhook
    SCRIPT = "script"             # Execute script
    CHAIN = "chain"               # Chain of actions
    DELAY = "delay"               # Delay before next action
    CONDITION = "condition"       # Conditional execution

# ============================================================================
# MODELS
# ============================================================================

@dataclass
class Trigger:
    """Workflow trigger configuration."""
    type: str
    config: Dict = field(default_factory=dict)
    enabled: bool = True
    
    # Config examples:
    # schedule: {"type": "interval", "value": 300}  # every 5 min
    # schedule: {"type": "daily", "time": "09:00"}
    # schedule: {"type": "cron", "expression": "0 9 * * 1-5"}
    # event: {"event_type": "device_online", "device_id": "xxx"}
    # condition: {"field": "battery_level", "operator": "<", "value": 20}
    # geo_fence: {"lat": 33.3, "lon": 44.4, "radius": 100, "enter": True}
    # threshold: {"metric": "cpu_usage", "operator": ">", "value": 80}

@dataclass
class Action:
    """Workflow action configuration."""
    type: str
    config: Dict = field(default_factory=dict)
    order: int = 0
    enabled: bool = True
    on_success: Optional[str] = None  # Next action ID on success
    on_failure: Optional[str] = None  # Next action ID on failure
    
    # Config examples:
    # command: {"device_id": "xxx", "command": "get_location", "params": {}}
    # notification: {"type": "telegram", "chat_id": 123, "message": "..."}
    # webhook: {"url": "...", "method": "POST", "payload": {}}
    # script: {"language": "python", "code": "..."}
    # delay: {"seconds": 10}

@dataclass
class Workflow:
    """Workflow definition."""
    id: str
    name: str
    description: str = ""
    triggers: List[Trigger] = field(default_factory=list)
    actions: List[Action] = field(default_factory=list)
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_triggered_at: Optional[float] = None
    trigger_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    tags: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())

@dataclass
class WorkflowExecution:
    """Record of a workflow execution."""
    id: str
    workflow_id: str
    trigger_type: str
    triggered_at: float
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    status: str = "pending"  # pending, running, completed, failed
    actions_executed: List[Dict] = field(default_factory=list)
    error: Optional[str] = None
    context: Dict = field(default_factory=dict)

# ============================================================================
# TRIGGER HANDLERS
# ============================================================================

class TriggerHandler:
    """Base class for trigger handlers."""
    
    @staticmethod
    async def evaluate(trigger: Trigger, context: Dict) -> bool:
        """Evaluate if trigger should fire."""
        raise NotImplementedError

class ScheduleTriggerHandler(TriggerHandler):
    """Handler for schedule-based triggers."""
    
    @staticmethod
    async def evaluate(trigger: Trigger, context: Dict) -> bool:
        config = trigger.config
        schedule_type = config.get("type", "interval")
        
        if schedule_type == ScheduleType.INTERVAL.value:
            interval = config.get("value", 300)
            last_triggered = context.get("last_triggered_at", 0)
            return time.time() - last_triggered >= interval
        
        elif schedule_type == ScheduleType.DAILY.value:
            trigger_time = config.get("time", "00:00")
            now = datetime.now()
            target = datetime.strptime(trigger_time, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
            
            # Check if it's time to trigger today
            if now.hour == target.hour and now.minute == target.minute:
                last_triggered = context.get("last_triggered_at", 0)
                # Only trigger if not already triggered today
                if time.time() - last_triggered > 3600:  # At least 1 hour ago
                    return True
        
        elif schedule_type == ScheduleType.WEEKLY.value:
            days = config.get("days", [])  # 0=Monday, 6=Sunday
            trigger_time = config.get("time", "00:00")
            
            now = datetime.now()
            if now.weekday() in days:
                target = datetime.strptime(trigger_time, "%H:%M").replace(
                    year=now.year, month=now.month, day=now.day
                )
                if now.hour == target.hour and now.minute == target.minute:
                    last_triggered = context.get("last_triggered_at", 0)
                    if time.time() - last_triggered > 3600:
                        return True
        
        return False

class EventTriggerHandler(TriggerHandler):
    """Handler for event-based triggers."""
    
    @staticmethod
    async def evaluate(trigger: Trigger, context: Dict) -> bool:
        config = trigger.config
        event = context.get("event", {})
        
        # Match event type
        expected_type = config.get("event_type")
        if expected_type and event.get("type") != expected_type:
            return False
        
        # Match device ID if specified
        device_id = config.get("device_id")
        if device_id and event.get("device_id") != device_id:
            return False
        
        # Match event data conditions
        conditions = config.get("conditions", {})
        for key, expected_value in conditions.items():
            actual_value = event.get("data", {}).get(key)
            if actual_value != expected_value:
                return False
        
        return True

class ConditionTriggerHandler(TriggerHandler):
    """Handler for condition-based triggers."""
    
    OPERATORS = {
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "contains": lambda a, b: b in a if isinstance(a, (str, list)) else False,
        "matches": lambda a, b: bool(re.match(b, str(a))) if a else False,
    }
    
    @staticmethod
    async def evaluate(trigger: Trigger, context: Dict) -> bool:
        config = trigger.config
        device_data = context.get("device_data", {})
        
        field = config.get("field")
        operator = config.get("operator", "==")
        expected = config.get("value")
        
        if not field or operator not in ConditionTriggerHandler.OPERATORS:
            return False
        
        # Get actual value from device data
        actual = device_data
        for part in field.split("."):
            if isinstance(actual, dict):
                actual = actual.get(part)
            else:
                return False
        
        if actual is None:
            return False
        
        # Evaluate condition
        try:
            return ConditionTriggerHandler.OPERATORS[operator](actual, expected)
        except Exception:
            return False

class GeoFenceTriggerHandler(TriggerHandler):
    """Handler for location-based triggers."""
    
    @staticmethod
    async def evaluate(trigger: Trigger, context: Dict) -> bool:
        config = trigger.config
        location = context.get("location", {})
        
        if not location:
            return False
        
        device_lat = location.get("latitude")
        device_lon = location.get("longitude")
        
        if device_lat is None or device_lon is None:
            return False
        
        # Geo fence center and radius
        center_lat = config.get("lat")
        center_lon = config.get("lon")
        radius = config.get("radius", 100)  # meters
        trigger_on_enter = config.get("enter", True)
        
        if center_lat is None or center_lon is None:
            return False
        
        # Calculate distance (Haversine formula)
        from math import radians, cos, sin, sqrt, atan2
        
        R = 6371000  # Earth radius in meters
        lat1, lat2 = radians(center_lat), radians(device_lat)
        lon1, lon2 = radians(center_lon), radians(device_lon)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        distance = R * c
        
        inside = distance <= radius
        
        # Check if we should trigger
        was_inside = context.get("was_inside_geo_fence", False)
        
        if trigger_on_enter and inside and not was_inside:
            return True
        elif not trigger_on_enter and not inside and was_inside:
            return True
        
        return False

class ThresholdTriggerHandler(TriggerHandler):
    """Handler for metric threshold triggers."""
    
    @staticmethod
    async def evaluate(trigger: Trigger, context: Dict) -> bool:
        config = trigger.config
        metrics = context.get("metrics", {})
        
        metric_name = config.get("metric")
        operator = config.get("operator", ">")
        threshold = config.get("value")
        
        if not metric_name:
            return False
        
        current_value = metrics.get(metric_name)
        if current_value is None:
            return False
        
        # Use condition handler's operators
        ops = ConditionTriggerHandler.OPERATORS
        
        if operator not in ops:
            return False
        
        try:
            return ops[operator](current_value, threshold)
        except Exception:
            return False

# ============================================================================
# ACTION EXECUTORS
# ============================================================================

class ActionExecutor:
    """Base class for action executors."""
    
    @staticmethod
    async def execute(action: Action, context: Dict) -> Dict:
        """Execute an action and return result."""
        raise NotImplementedError

class CommandActionExecutor(ActionExecutor):
    """Executor for command actions."""
    
    @staticmethod
    async def execute(action: Action, context: Dict) -> Dict:
        from database import command_repo, Command
        
        config = action.config
        device_id = config.get("device_id") or context.get("device_id")
        command = config.get("command")
        params = config.get("params", {})
        
        if not device_id or not command:
            return {"success": False, "error": "Missing device_id or command"}
        
        # Create command
        cmd = Command(
            id=str(uuid.uuid4()),
            device_id=device_id,
            command=command,
            params=params,
            source="workflow"
        )
        
        command_repo.create(cmd)
        
        return {
            "success": True,
            "command_id": cmd.id,
            "device_id": device_id,
            "command": command
        }

class NotificationActionExecutor(ActionExecutor):
    """Executor for notification actions."""
    
    @staticmethod
    async def execute(action: Action, context: Dict) -> Dict:
        config = action.config
        notif_type = config.get("type", "telegram")
        message = config.get("message", "")
        chat_id = config.get("chat_id")
        
        # Template variable substitution
        for key, value in context.items():
            placeholder = f"${{{key}}}"
            if placeholder in message:
                message = message.replace(placeholder, str(value))
        
        if notif_type == "telegram":
            # Import from main server
            import aiohttp
            BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
            
            if not BOT_TOKEN or not chat_id:
                return {"success": False, "error": "Missing BOT_TOKEN or chat_id"}
            
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML"
                }) as resp:
                    result = await resp.json()
                    return {"success": result.get("ok", False), "result": result}
        
        return {"success": False, "error": f"Unknown notification type: {notif_type}"}

class WebhookActionExecutor(ActionExecutor):
    """Executor for webhook actions."""
    
    @staticmethod
    async def execute(action: Action, context: Dict) -> Dict:
        import aiohttp
        
        config = action.config
        url = config.get("url")
        method = config.get("method", "POST").upper()
        payload = config.get("payload", {})
        headers = config.get("headers", {})
        
        if not url:
            return {"success": False, "error": "Missing webhook URL"}
        
        # Template substitution in payload
        payload_str = json.dumps(payload)
        for key, value in context.items():
            payload_str = payload_str.replace(f"${{{key}}}", str(value))
        payload = json.loads(payload_str)
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.request(
                    method, url, json=payload, headers=headers, timeout=30
                ) as resp:
                    result = await resp.text()
                    return {
                        "success": resp.status < 400,
                        "status": resp.status,
                        "response": result[:500]
                    }
            except Exception as e:
                return {"success": False, "error": str(e)}

class DelayActionExecutor(ActionExecutor):
    """Executor for delay actions."""
    
    @staticmethod
    async def execute(action: Action, context: Dict) -> Dict:
        config = action.config
        seconds = config.get("seconds", 0)
        
        if seconds > 0:
            await asyncio.sleep(seconds)
        
        return {"success": True, "delayed_seconds": seconds}

# ============================================================================
# WORKFLOW ENGINE
# ============================================================================

class WorkflowEngine:
    """Main workflow execution engine."""
    
    TRIGGER_HANDLERS = {
        TriggerType.SCHEDULE.value: ScheduleTriggerHandler,
        TriggerType.EVENT.value: EventTriggerHandler,
        TriggerType.CONDITION.value: ConditionTriggerHandler,
        TriggerType.GEO_FENCE.value: GeoFenceTriggerHandler,
        TriggerType.THRESHOLD.value: ThresholdTriggerHandler,
    }
    
    ACTION_EXECUTORS = {
        ActionType.COMMAND.value: CommandActionExecutor,
        ActionType.NOTIFICATION.value: NotificationActionExecutor,
        ActionType.WEBHOOK.value: WebhookActionExecutor,
        ActionType.DELAY.value: DelayActionExecutor,
    }
    
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}
        self._executions: Dict[str, WorkflowExecution] = {}
        self._lock = threading.RLock()
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    def register_workflow(self, workflow: Workflow) -> str:
        """Register a workflow."""
        with self._lock:
            self._workflows[workflow.id] = workflow
        log.info("Registered workflow: %s (%s)", workflow.name, workflow.id)
        return workflow.id
    
    def unregister_workflow(self, workflow_id: str) -> bool:
        """Unregister a workflow."""
        with self._lock:
            return self._workflows.pop(workflow_id, None) is not None
    
    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get a workflow by ID."""
        return self._workflows.get(workflow_id)
    
    def get_all_workflows(self) -> List[Workflow]:
        """Get all workflows."""
        return list(self._workflows.values())
    
    async def start(self):
        """Start the workflow engine."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        log.info("Workflow engine started")
    
    async def stop(self):
        """Stop the workflow engine."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("Workflow engine stopped")
    
    async def _run_loop(self):
        """Main loop for checking triggers."""
        while self._running:
            try:
                await self._check_triggers()
            except Exception as e:
                log.error("Trigger check error: %s", e)
            
            await asyncio.sleep(1)
    
    async def _check_triggers(self):
        """Check all workflow triggers."""
        for workflow_id, workflow in list(self._workflows.items()):
            if not workflow.enabled:
                continue
            
            for trigger in workflow.triggers:
                if not trigger.enabled:
                    continue
                
                try:
                    context = {
                        "last_triggered_at": workflow.last_triggered_at,
                        "workflow_id": workflow_id,
                    }
                    
                    handler = self.TRIGGER_HANDLERS.get(trigger.type)
                    if handler and await handler.evaluate(trigger, context):
                        await self.execute_workflow(workflow_id, trigger.type, context)
                
                except Exception as e:
                    log.error("Trigger evaluation error: %s - %s", workflow_id, e)
    
    async def execute_workflow(self, workflow_id: str, trigger_type: str, context: Dict = None) -> WorkflowExecution:
        """Execute a workflow."""
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow not found: {workflow_id}")
        
        # Create execution record
        execution = WorkflowExecution(
            id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            trigger_type=trigger_type,
            triggered_at=time.time(),
            context=context or {}
        )
        
        with self._lock:
            self._executions[execution.id] = execution
        
        # Update workflow stats
        workflow.trigger_count += 1
        workflow.last_triggered_at = time.time()
        
        log.info("Executing workflow: %s (trigger: %s)", workflow.name, trigger_type)
        
        # Execute actions in order
        execution.status = "running"
        execution.started_at = time.time()
        
        try:
            sorted_actions = sorted(workflow.actions, key=lambda a: a.order)
            
            for action in sorted_actions:
                if not action.enabled:
                    continue
                
                action_result = await self._execute_action(action, execution.context)
                execution.actions_executed.append({
                    "action_type": action.type,
                    "action_config": action.config,
                    "result": action_result,
                    "timestamp": time.time()
                })
                
                # Update context with action result
                execution.context[f"action_{action.order}"] = action_result
                
                # Check for failure
                if not action_result.get("success"):
                    execution.status = "failed"
                    execution.error = action_result.get("error", "Action failed")
                    workflow.failure_count += 1
                    break
            
            else:
                execution.status = "completed"
                workflow.success_count += 1
        
        except Exception as e:
            execution.status = "failed"
            execution.error = str(e)
            workflow.failure_count += 1
            log.error("Workflow execution error: %s - %s", workflow_id, e)
        
        finally:
            execution.completed_at = time.time()
        
        return execution
    
    async def _execute_action(self, action: Action, context: Dict) -> Dict:
        """Execute a single action."""
        executor = self.ACTION_EXECUTORS.get(action.type)
        
        if not executor:
            return {"success": False, "error": f"Unknown action type: {action.type}"}
        
        try:
            return await executor.execute(action, context)
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def process_event(self, event_type: str, event_data: Dict, device_id: str = None):
        """Process an event that may trigger workflows."""
        asyncio.create_task(self._process_event_async(event_type, event_data, device_id))
    
    async def _process_event_async(self, event_type: str, event_data: Dict, device_id: str = None):
        """Async event processing."""
        for workflow_id, workflow in list(self._workflows.items()):
            if not workflow.enabled:
                continue
            
            for trigger in workflow.triggers:
                if trigger.type == TriggerType.EVENT.value and trigger.enabled:
                    context = {
                        "event": {
                            "type": event_type,
                            "device_id": device_id,
                            "data": event_data
                        },
                        "device_id": device_id,
                    }
                    
                    handler = self.TRIGGER_HANDLERS.get(trigger.type)
                    if handler and await handler.evaluate(trigger, context):
                        await self.execute_workflow(workflow_id, trigger.type, context)
    
    def get_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Get an execution by ID."""
        return self._executions.get(execution_id)
    
    def get_workflow_executions(self, workflow_id: str, limit: int = 50) -> List[WorkflowExecution]:
        """Get executions for a workflow."""
        executions = [
            e for e in self._executions.values()
            if e.workflow_id == workflow_id
        ]
        return sorted(executions, key=lambda e: e.triggered_at, reverse=True)[:limit]

# ============================================================================
# WORKFLOW TEMPLATES
# ============================================================================

WORKFLOW_TEMPLATES = {
    "low_battery_alert": Workflow(
        id="template_low_battery",
        name="تنبيه البطارية المنخفضة",
        description="إرسال تنبيه عند انخفاض البطارية أقل من 20%",
        triggers=[
            Trigger(
                type=TriggerType.CONDITION.value,
                config={"field": "battery_level", "operator": "<", "value": 20}
            )
        ],
        actions=[
            Action(
                type=ActionType.NOTIFICATION.value,
                config={
                    "type": "telegram",
                    "message": "⚠️ تحذير: بطارية الجهاز ${device_id} منخفضة (${battery_level}%)"
                },
                order=0
            )
        ],
        tags=["battery", "alert"]
    ),
    
    "device_online_check": Workflow(
        id="template_device_online",
        name="فحص اتصال الجهاز",
        description="فحص حالة الجهاز كل 5 دقائق",
        triggers=[
            Trigger(
                type=TriggerType.SCHEDULE.value,
                config={"type": "interval", "value": 300}
            )
        ],
        actions=[
            Action(
                type=ActionType.COMMAND.value,
                config={"command": "ping"},
                order=0
            )
        ],
        tags=["monitoring", "health"]
    ),
    
    "daily_backup": Workflow(
        id="template_daily_backup",
        name="نسخ احتياطي يومي",
        description="إنشاء نسخة احتياطية يومية في منتصف الليل",
        triggers=[
            Trigger(
                type=TriggerType.SCHEDULE.value,
                config={"type": "daily", "time": "00:00"}
            )
        ],
        actions=[
            Action(
                type=ActionType.COMMAND.value,
                config={"command": "send_full_backup"},
                order=0
            )
        ],
        tags=["backup", "scheduled"]
    ),
}

# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

workflow_engine = WorkflowEngine()

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_workflow_from_template(template_name: str, device_id: str = None, **kwargs) -> Workflow:
    """Create a workflow from a template."""
    template = WORKFLOW_TEMPLATES.get(template_name)
    if not template:
        raise ValueError(f"Template not found: {template_name}")
    
    # Create new workflow from template
    workflow = Workflow(
        id=str(uuid.uuid4()),
        name=kwargs.get("name", template.name),
        description=kwargs.get("description", template.description),
        triggers=[Trigger(**{**t.__dict__}) for t in template.triggers],
        actions=[Action(**{**a.__dict__}) for a in template.actions],
        tags=template.tags.copy(),
        metadata={"template": template_name, "device_id": device_id}
    )
    
    # Set device_id in actions if provided
    if device_id:
        for action in workflow.actions:
            if action.type == ActionType.COMMAND.value:
                action.config["device_id"] = device_id
    
    return workflow
