"""FastAPI backend service for BrowserPilot Vision with single-task lock and safe worker thread.

Note on Task State Management:
    Task records and live histories are managed in an in-memory bounded dictionary
    (limited to 100 recent tasks). Restarting the FastAPI server will clear all in-memory
    task statuses and histories. However, persistent step-by-step execution logs are
    safely written to disk in `data/<task_id>.jsonl`.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.agent import BrowserAgent
from app.config import settings
from app.llm import LocalLLMClient
from app.logger import app_logger, mask_sensitive_data
from app.safety import default_safety_policy
from app.schemas import (
    TaskRequest,
    TaskResponse,
    TaskStatus,
    TaskStepRecord,
)


app = FastAPI(
    title="BrowserPilot Vision API",
    description="Local-first AI browser automation agent API powered by Ollama and Playwright.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory bounded task store (max 100 historical tasks)
MAX_STORED_TASKS = 100
tasks_lock = threading.Lock()
tasks_store: OrderedDict[str, TaskResponse] = OrderedDict()

# Single active task concurrency control
active_task_lock = threading.Lock()
current_active_task_id: Optional[str] = None
current_agent_instance: Optional[BrowserAgent] = None

# Local LLM client for health & model discovery
llm_client = LocalLLMClient()


def _sanitize_step_record(rec: TaskStepRecord) -> TaskStepRecord:
    """Mask credentials or sensitive data from task step entries before exposing to API."""
    sanitized_val = mask_sensitive_data(rec.value) if rec.value else None
    sanitized_thought = mask_sensitive_data(rec.thought)
    sanitized_msg = mask_sensitive_data(rec.message)
    sanitized_ev = mask_sensitive_data(rec.evidence) if rec.evidence else None
    sanitized_err = mask_sensitive_data(rec.error_category) if rec.error_category else None

    return TaskStepRecord(
        step=rec.step,
        timestamp=rec.timestamp,
        thought=sanitized_thought,
        action=rec.action,
        target=rec.target,
        value=sanitized_val,
        url=rec.url,
        success=rec.success,
        verification_passed=rec.verification_passed,
        message=sanitized_msg,
        evidence=sanitized_ev,
        duration=rec.duration,
        error_category=sanitized_err,
    )


def _sanitize_task_response(resp: TaskResponse) -> TaskResponse:
    """Create a sanitized clone of TaskResponse with masked sensitive tokens."""
    sanitized_history = [_sanitize_step_record(r) for r in resp.history]
    sanitized_res = mask_sensitive_data(resp.result) if resp.result else None
    sanitized_ev = mask_sensitive_data(resp.evidence) if resp.evidence else None
    sanitized_err = mask_sensitive_data(resp.error) if resp.error else None

    return TaskResponse(
        task_id=resp.task_id,
        status=resp.status,
        task=resp.task,
        start_url=resp.start_url,
        model=resp.model,
        result=sanitized_res,
        evidence=sanitized_ev,
        steps_taken=resp.steps_taken,
        max_steps=resp.max_steps,
        created_at=resp.created_at,
        updated_at=resp.updated_at,
        error=sanitized_err,
        history=sanitized_history,
    )


def _store_task(response: TaskResponse) -> None:
    with tasks_lock:
        tasks_store[response.task_id] = response
        while len(tasks_store) > MAX_STORED_TASKS:
            tasks_store.popitem(last=False)


@app.get("/health", tags=["System"])
def get_health() -> Dict[str, Any]:
    """Health check endpoint displaying system readiness and safe non-sensitive configuration."""
    ollama_ok = llm_client.is_available()
    with active_task_lock:
        is_busy = current_active_task_id is not None
        active_id = current_active_task_id

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ollama_connected": ollama_ok,
        "default_model": settings.default_model,
        "context_size": settings.context_size,
        "max_agent_steps": settings.max_agent_steps,
        "request_timeout": settings.request_timeout,
        "allowed_hosts": settings.allowed_hosts,
        "task_in_progress": is_busy,
        "active_task_id": active_id,
    }


@app.get("/models", tags=["System"])
def get_models() -> Dict[str, Any]:
    """Report the configured Ollama model and whether Ollama is reachable without auto-downloading."""
    reachable = llm_client.is_available()
    installed = llm_client.list_models() if reachable else []
    return {
        "default_model": settings.default_model,
        "supported_models": settings.supported_models,
        "installed_models": installed,
        "ollama_reachable": reachable,
    }


def _run_agent_thread(task_req: TaskRequest, initial_resp: TaskResponse) -> None:
    """Synchronous worker thread executing the browser agent loop."""
    global current_active_task_id, current_agent_instance
    agent = BrowserAgent(
        llm_client=llm_client,
        safety_policy=default_safety_policy,
        max_steps=task_req.max_steps,
    )
    with active_task_lock:
        current_agent_instance = agent

    try:
        def on_step(record: TaskStepRecord) -> None:
            with tasks_lock:
                if initial_resp.task_id in tasks_store:
                    existing = tasks_store[initial_resp.task_id]
                    existing.history.append(record)
                    existing.steps_taken = record.step
                    existing.updated_at = datetime.now(timezone.utc).isoformat()

        agent.step_callback = on_step
        final_resp = agent.run_task(task_req)
        # Preserve task_id
        final_resp.task_id = initial_resp.task_id
        _store_task(final_resp)
    except Exception as e:
        app_logger.error(f"Fatal unhandled error in agent execution thread: {e}")
        initial_resp.status = TaskStatus.FAILED
        initial_resp.error = str(e)
        initial_resp.updated_at = datetime.now(timezone.utc).isoformat()
        _store_task(initial_resp)
    finally:
        with active_task_lock:
            current_active_task_id = None
            current_agent_instance = None


@app.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED, tags=["Tasks"])
def create_task(req: TaskRequest) -> TaskResponse:
    """Submit a natural-language browser automation task.

    Enforces single active task, start URL validation against safety policy,
    and Ollama service availability.
    """
    global current_active_task_id

    # 1. Validate start URL safety
    is_safe, reason = default_safety_policy.validate_url(req.start_url)
    if not is_safe:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or prohibited starting URL '{req.start_url}': {reason}",
        )

    # 2. Check Ollama reachability
    if not llm_client.is_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama service is currently unreachable at http://localhost:11434. Please ensure Ollama is running.",
        )

    # 3. Enforce single active task lock
    with active_task_lock:
        if current_active_task_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Another browser task '{current_active_task_id}' is currently running. Only one active task allowed at a time.",
            )
        task_id = f"task_{uuid.uuid4().hex[:10]}"
        current_active_task_id = task_id

    now = datetime.now(timezone.utc).isoformat()
    init_response = TaskResponse(
        task_id=task_id,
        status=TaskStatus.RUNNING,
        task=req.task,
        start_url=req.start_url,
        model=req.model or settings.default_model,
        max_steps=req.max_steps or settings.max_agent_steps,
        created_at=now,
        updated_at=now,
        history=[],
    )
    _store_task(init_response)

    # Spawn background thread to run synchronous Playwright loop without blocking FastAPI event loop
    worker_thread = threading.Thread(
        target=_run_agent_thread,
        args=(req, init_response),
        daemon=True,
    )
    worker_thread.start()

    return _sanitize_task_response(init_response)


@app.get("/tasks/{task_id}", response_model=TaskResponse, tags=["Tasks"])
def get_task(task_id: str) -> TaskResponse:
    """Retrieve the live or historical execution status and log for a task."""
    with tasks_lock:
        if task_id not in tasks_store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task '{task_id}' not found.",
            )
        return _sanitize_task_response(tasks_store[task_id])


@app.post("/tasks/{task_id}/cancel", response_model=TaskResponse, tags=["Tasks"])
def cancel_task(task_id: str) -> TaskResponse:
    """Request immediate cancellation of a running task."""
    global current_agent_instance, current_active_task_id

    with active_task_lock:
        if current_active_task_id != task_id or current_agent_instance is None:
            with tasks_lock:
                if task_id in tasks_store:
                    return _sanitize_task_response(tasks_store[task_id])
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Task '{task_id}' not found to cancel.",
                )

        current_agent_instance.cancel()

    # Wait briefly for cancellation to take effect in agent loop
    for _ in range(15):
        with tasks_lock:
            if task_id in tasks_store and tasks_store[task_id].status == TaskStatus.CANCELLED:
                return _sanitize_task_response(tasks_store[task_id])
        time.sleep(0.2)

    with tasks_lock:
        return _sanitize_task_response(tasks_store[task_id])
