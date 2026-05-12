"""
APScheduler-based background task scheduler with state recovery.
Supports long-running tasks, persistence, and crash recovery.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor
from apscheduler.events import (
    EVENT_JOB_EXECUTED,
    EVENT_JOB_ERROR,
    EVENT_JOB_MISSED,
    EVENT_JOB_SUBMITTED,
)
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.job import Job
import structlog
from datetime import datetime, timedelta
from typing import Dict, Any, Callable, Optional
import asyncio
import json

from app.core.config import get_settings
from app.database.session import SessionLocal
from app.database.models import BackgroundTask, TaskLog

logger = structlog.get_logger()
settings = get_settings()

# Global scheduler instance
scheduler: Optional[AsyncIOScheduler] = None


def _job_listener(event):
    """Listen for job execution events."""
    if event.exception:
        logger.error(
            "job_executed_error",
            job_id=event.job_id,
            error=str(event.exception),
            traceback=getattr(event, 'traceback', None)
        )
    else:
        logger.info(
            "job_executed_success",
            job_id=event.job_id,
            scheduled_time=getattr(event, 'scheduled_run_time', None)
        )


def _job_missed_listener(event):
    """Handle missed job executions."""
    logger.warning(
        "job_missed",
        job_id=event.job_id,
        scheduled_time=getattr(event, 'scheduled_run_time', None)
    )


class SchedulerManager:
    """
    Production-ready scheduler manager with state recovery.
    
    Features:
    - Persistent job storage in PostgreSQL
    - Automatic recovery on startup
    - Job execution logging
    - Long-running task support
    - Graceful shutdown
    """

    def __init__(self):
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._job_states: Dict[str, Dict] = {}
        self._running_jobs: Dict[str, bool] = {}

    def _create_scheduler(self) -> AsyncIOScheduler:
        """Create and configure the scheduler instance."""
        
        # Configure job stores
        job_stores = {
            'default': SQLAlchemyJobStore(url=settings.database_url),
        }
        
        # Configure executors
        executors = {
            'default': ThreadPoolExecutor(20),
            'processpool': ProcessPoolExecutor(5)
        }
        
        # Configure job defaults
        job_defaults = {
            'coalesce': False,  # Don't combine missed executions
            'max_instances': 3,  # Allow multiple instances of same job
            'misfire_grace_time': 60 * 15  # 15 minutes grace period
        }
        
        scheduler = AsyncIOScheduler(
            jobstores=job_stores,
            executors=executors,
            job_defaults=job_defaults,
            timezone='UTC'
        )
        
        # Add event listeners
        scheduler.add_listener(
            _job_listener,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
        )
        scheduler.add_listener(
            _job_missed_listener,
            EVENT_JOB_MISSED
        )
        
        return scheduler

    def start(self):
        """Start the scheduler with recovery of interrupted jobs."""
        if self._scheduler and self._scheduler.running:
            logger.warning("scheduler_already_running")
            return
        
        self._scheduler = self._create_scheduler()
        self._scheduler.start()
        
        logger.info("scheduler_started")
        
        # Schedule recovery of interrupted tasks
        self._schedule_recovery()
        
        # Schedule periodic cleanup
        self._schedule_cleanup()

    def stop(self):
        """Gracefully stop the scheduler."""
        if self._scheduler and self._scheduler.running:
            # Wait for running jobs to complete (with timeout)
            self._scheduler.shutdown(wait=True, timeout=60)
            logger.info("scheduler_stopped")

    def _schedule_recovery(self):
        """Schedule recovery check for interrupted jobs."""
        self._scheduler.add_job(
            self._recover_interrupted_jobs,
            trigger=DateTrigger(
                run_date=datetime.utcnow() + timedelta(seconds=10)
            ),
            id='recovery_job',
            replace_existing=True
        )

    def _schedule_cleanup(self):
        """Schedule periodic cleanup of old task logs."""
        self._scheduler.add_job(
            self._cleanup_old_tasks,
            trigger=CronTrigger(hour=2, minute=0),  # Run at 2 AM UTC
            id='cleanup_job',
            replace_existing=True
        )

    async def _recover_interrupted_jobs(self):
        """
        Recover jobs that were interrupted (e.g., server crash).
        
        Finds jobs in 'running' state and either:
        1. Reschedules them if they're still valid
        2. Marks them as failed if they exceeded timeout
        """
        logger.info("starting_job_recovery")
        
        db = SessionLocal()
        try:
            # Find running tasks that haven't been updated in 30 minutes
            cutoff = datetime.utcnow() - timedelta(minutes=30)
            
            running_tasks = db.query(BackgroundTask).filter(
                BackgroundTask.status == "running",
            ).all()
            
            recovered = 0
            failed = 0
            
            for task in running_tasks:
                # Check if task was created recently enough to recover
                task_age = datetime.utcnow() - task.updated_at
                
                if task_age > timedelta(hours=1):
                    # Task is too old, mark as failed
                    task.status = "failed"
                    task.result = {"error": "Task timed out during recovery"}
                    failed += 1
                    
                    TaskLog(
                        task_id=task.id,
                        content=f"Task marked as failed during recovery: timeout",
                        level="error"
                    )
                    logger.warning(
                        "task_marked_failed_recovery",
                        task_id=task.id,
                        age_hours=task_age.total_seconds() / 3600
                    )
                else:
                    # Task can be recovered - reschedule
                    task.status = "pending"
                    recovered += 1
                    
                    # Re-trigger the task
                    self._reschedule_task(task)
                    
                    logger.info(
                        "task_recovered",
                        task_id=task.id,
                        payload=task.payload
                    )
            
            db.commit()
            
            logger.info(
                "recovery_complete",
                recovered=recovered,
                failed=failed
            )
            
        except Exception as e:
            logger.error("recovery_failed", error=str(e))
        finally:
            db.close()

    def _reschedule_task(self, task: BackgroundTask):
        """Reschedule a recovered task."""
        if not self._scheduler:
            return
        
        task_type = task.task_type
        task_id = task.id
        payload = task.payload or {}
        
        # Map task types to handler functions
        handlers = {
            'index': _run_indexing_handler,
            'agent': _run_agent_handler,
            'decompose': _run_decompose_handler,
            'custom': _run_custom_handler,
        }
        
        handler = handlers.get(task_type, _run_generic_handler)
        
        self.add_job(
            handler,
            'date',
            args=[task_id, payload],
            job_id=f"recovered_{task_id}",
            replace_existing=True
        )

    async def _cleanup_old_tasks(self):
        """Clean up old completed/failed tasks."""
        db = SessionLocal()
        try:
            # Find tasks older than 7 days
            cutoff = datetime.utcnow() - timedelta(days=7)
            
            old_tasks = db.query(BackgroundTask).filter(
                BackgroundTask.status.in_(['completed', 'failed']),
                BackgroundTask.updated_at < cutoff
            ).all()
            
            # Delete old task logs first
            task_ids = [t.id for t in old_tasks]
            if task_ids:
                db.query(TaskLog).filter(
                    TaskLog.task_id.in_(task_ids)
                ).delete()
                
                db.query(BackgroundTask).filter(
                    BackgroundTask.id.in_(task_ids)
                ).delete()
                
                db.commit()
            
            logger.info("cleanup_complete", deleted=len(old_tasks))
            
        except Exception as e:
            logger.error("cleanup_failed", error=str(e))
        finally:
            db.close()

    def add_job(
        self,
        func: Callable,
        trigger: str = 'date',
        job_id: Optional[str] = None,
        replace_existing: bool = True,
        **kwargs
    ) -> Optional[Job]:
        """
        Add a job to the scheduler.
        
        Args:
            func: The function to execute
            trigger: Trigger type ('date', 'interval', 'cron')
            job_id: Unique job identifier
            replace_existing: Replace existing job with same ID
            **kwargs: Additional arguments passed to the job
            
        Returns:
            Created Job instance or None
        """
        if not self._scheduler:
            logger.error("scheduler_not_running")
            return None
        
        if not job_id:
            job_id = f"job_{datetime.utcnow().timestamp()}"
        
        trigger_obj = self._get_trigger(trigger, kwargs)
        
        try:
            job = self._scheduler.add_job(
                func,
                trigger=trigger_obj,
                id=job_id,
                replace_existing=replace_existing,
                **kwargs
            )
            
            logger.info("job_added", job_id=job_id, trigger=trigger)
            return job
            
        except Exception as e:
            logger.error("job_add_failed", job_id=job_id, error=str(e))
            return None

    def _get_trigger(self, trigger_type: str, kwargs: Dict) -> Any:
        """Create the appropriate trigger object."""
        if trigger_type == 'date':
            run_date = kwargs.get('run_date', datetime.utcnow())
            return DateTrigger(run_date=run_date)
        elif trigger_type == 'interval':
            return IntervalTrigger(
                seconds=kwargs.get('seconds'),
                minutes=kwargs.get('minutes'),
                hours=kwargs.get('hours'),
                days=kwargs.get('days')
            )
        elif trigger_type == 'cron':
            return CronTrigger(
                hour=kwargs.get('hour'),
                minute=kwargs.get('minute'),
                day_of_week=kwargs.get('day_of_week')
            )
        else:
            return DateTrigger(run_date=datetime.utcnow())

    def remove_job(self, job_id: str):
        """Remove a job from the scheduler."""
        if self._scheduler:
            try:
                self._scheduler.remove_job(job_id)
                logger.info("job_removed", job_id=job_id)
            except Exception as e:
                logger.warning("job_remove_failed", job_id=job_id, error=str(e))

    def pause_job(self, job_id: str):
        """Pause a job."""
        if self._scheduler:
            try:
                self._scheduler.pause_job(job_id)
                logger.info("job_paused", job_id=job_id)
            except Exception as e:
                logger.warning("job_pause_failed", job_id=job_id, error=str(e))

    def resume_job(self, job_id: str):
        """Resume a paused job."""
        if self._scheduler:
            try:
                self._scheduler.resume_job(job_id)
                logger.info("job_resumed", job_id=job_id)
            except Exception as e:
                logger.warning("job_resume_failed", job_id=job_id, error=str(e))

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        if self._scheduler:
            return self._scheduler.get_job(job_id)
        return None

    def get_jobs(self) -> list:
        """Get all scheduled jobs."""
        if self._scheduler:
            return self._scheduler.get_jobs()
        return []

    def run_job_now(self, job_id: str):
        """Run a job immediately."""
        job = self.get_job(job_id)
        if job:
            job.modify(next_run_time=datetime.utcnow())
            logger.info("job_scheduled_now", job_id=job_id)
        else:
            logger.warning("job_not_found", job_id=job_id)


# Global scheduler manager
_sched_manager: Optional[SchedulerManager] = None


def get_scheduler_manager() -> SchedulerManager:
    """Get the global scheduler manager instance."""
    global _sched_manager
    if _sched_manager is None:
        _sched_manager = SchedulerManager()
    return _sched_manager


# Convenience functions
scheduler = get_scheduler_manager()


def start_scheduler():
    """Start the global scheduler."""
    get_scheduler_manager().start()


def stop_scheduler():
    """Stop the global scheduler."""
    get_scheduler_manager().stop()


def schedule_task(
    func: Callable,
    task_id: int,
    task_type: str,
    payload: Dict[str, Any]
):
    """
    Schedule a background task.
    
    Args:
        func: Handler function
        task_id: Database task ID
        task_type: Type of task
        payload: Task parameters
    """
    job_id = f"{task_type}_{task_id}_{datetime.utcnow().timestamp()}"
    
    scheduler.add_job(
        func,
        'date',
        args=[task_id, payload],
        job_id=job_id
    )


# Task handlers for different task types
async def _run_indexing_handler(task_id: int, payload: Dict):
    """Handle repository indexing tasks."""
    from app.intelligence.indexer import CodebaseIndexer
    
    db = SessionLocal()
    try:
        task = db.query(BackgroundTask).get(task_id)
        if not task:
            return
        
        task.status = "running"
        db.commit()
        
        token = payload.get('github_token', settings.github_token)
        indexer = CodebaseIndexer(db, token)
        
        stats = await indexer.index_repo(
            workspace_id=payload.get('workspace_id'),
            owner=payload.get('owner'),
            repo=payload.get('repo'),
            branch=payload.get('branch', 'main'),
            incremental=payload.get('incremental', True)
        )
        
        task.status = "completed"
        task.result = stats
        
        TaskLog(task_id=task_id, content=f"Indexing completed: {stats}", level="info")
        db.commit()
        
    except Exception as e:
        task = db.query(BackgroundTask).get(task_id)
        if task:
            task.status = "failed"
            task.result = {"error": str(e)}
            TaskLog(task_id=task_id, content=f"Indexing failed: {e}", level="error")
            db.commit()
    finally:
        db.close()


async def _run_agent_handler(task_id: int, payload: Dict):
    """Handle agent execution tasks."""
    from app.tasks import run_agent_task
    
    run_agent_task(task_id)


async def _run_decompose_handler(task_id: int, payload: Dict):
    """Handle task decomposition tasks."""
    from app.orchestrator.decomposer import TaskDecomposer
    
    db = SessionLocal()
    try:
        task = db.query(BackgroundTask).get(task_id)
        if not task:
            return
        
        task.status = "running"
        db.commit()
        
        decomposer = TaskDecomposer()
        goal = payload.get('goal', '')
        context = payload.get('context', {})
        
        graph = await decomposer.decompose(goal, context)
        
        task.status = "completed"
        task.result = {
            "graph_id": graph.id,
            "subtasks": len(graph.subtasks)
        }
        
        TaskLog(task_id=task_id, content=f"Decomposition completed: {len(graph.subtasks)} subtasks", level="info")
        db.commit()
        
    except Exception as e:
        task = db.query(BackgroundTask).get(task_id)
        if task:
            task.status = "failed"
            task.result = {"error": str(e)}
            TaskLog(task_id=task_id, content=f"Decomposition failed: {e}", level="error")
            db.commit()
    finally:
        db.close()


async def _run_custom_handler(task_id: int, payload: Dict):
    """Handle custom task types."""
    handler_name = payload.get('handler')
    if handler_name:
        # Dynamic handler lookup
        pass


async def _run_generic_handler(task_id: int, payload: Dict):
    """Generic task handler."""
    logger.info("generic_task_handler", task_id=task_id)


# Periodic health check
async def _health_check():
    """Periodic health check for running tasks."""
    db = SessionLocal()
    try:
        # Find stuck tasks (running for > 1 hour)
        cutoff = datetime.utcnow() - timedelta(hours=1)
        
        stuck_tasks = db.query(BackgroundTask).filter(
            BackgroundTask.status == "running",
            BackgroundTask.updated_at < cutoff
        ).all()
        
        for task in stuck_tasks:
            logger.warning("stuck_task_detected", task_id=task.id)
            # Could auto-fail or retry here
            
    except Exception as e:
        logger.error("health_check_failed", error=str(e))
    finally:
        db.close()