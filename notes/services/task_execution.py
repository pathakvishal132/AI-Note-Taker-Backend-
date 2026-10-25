"""Task execution service - performs task CRUD operations based on extracted intents."""
import logging
from typing import Optional, Dict, Any, List

from django.db import transaction
from django.db.models import Q

from tasks.models import Task
from notes.models import Note
from .schemas import (
    IntentExtractionResult, IntentType, TaskStatus,
    TaskPriority, TaskFilters,
)

logger = logging.getLogger(__name__)


class TaskExecutionError(Exception):
    """Raised when task execution fails."""
    pass


class TaskExecutionService:
    """Service that executes task operations based on extracted intents."""

    def execute(
        self, intent_result: IntentExtractionResult, note: Note
    ) -> Dict[str, Any]:
        """Execute the action corresponding to the extracted intent.

        Args:
            intent_result: Validated intent extraction result.
            note: The note associated with this action.

        Returns:
            Dict with action type and relevant data.
        """
        if intent_result.needs_clarification:
            return {
                'type': 'needs_clarification',
                'message': intent_result.clarification_question or
                           'Could you please clarify your request?',
            }

        intent = intent_result.intent

        if intent == IntentType.CREATE_TASK:
            return self._create_task(intent_result, note)
        elif intent == IntentType.UPDATE_TASK_STATUS:
            return self._update_task_status(intent_result)
        elif intent == IntentType.QUERY_TASKS:
            return self._query_tasks(intent_result)
        elif intent == IntentType.GENERAL_NOTE:
            return {
                'type': 'note_saved',
                'message': 'Note saved successfully.',
            }
        else:
            return {
                'type': 'unknown_intent',
                'message': f'Unrecognized intent: {intent}',
            }

    @transaction.atomic
    def _create_task(
        self, intent_result: IntentExtractionResult, note: Note
    ) -> Dict[str, Any]:
        """Create a task from the extracted entities."""
        entities = intent_result.entities

        task = Task.objects.create(
            title=entities.title,
            description=entities.description or '',
            status=Task.Status.PENDING,
            priority=self._map_priority(entities.priority),
            due_date=entities.due_date,
        )

        # Link the note to the task
        note.task = task
        note.save(update_fields=['task'])

        logger.info(f"Created task {task.id}: {task.title}")

        return {
            'type': 'task_created',
            'task': self._task_to_dict(task),
        }

    def _update_task_status(
        self, intent_result: IntentExtractionResult
    ) -> Dict[str, Any]:
        """Update a task's status by searching for it."""
        entities = intent_result.entities
        identifier = entities.task_identifier

        if not identifier:
            return {
                'type': 'error',
                'message': 'No task identifier provided.',
            }

        # Search for matching tasks
        matching_tasks = Task.objects.filter(
            Q(title__icontains=identifier) |
            Q(description__icontains=identifier)
        ).exclude(
            status=Task.Status.CANCELLED
        )

        count = matching_tasks.count()

        if count == 0:
            return {
                'type': 'task_not_found',
                'message': f'No task found matching: "{identifier}"',
            }
        elif count > 1:
            # Ambiguous - return matches for clarification
            tasks_list = [
                self._task_to_dict(t) for t in matching_tasks[:5]
            ]
            return {
                'type': 'needs_clarification',
                'message': (
                    f'Found {count} tasks matching "{identifier}". '
                    'Please be more specific or use the task ID.'
                ),
                'matching_tasks': tasks_list,
            }

        # Exactly one match
        task = matching_tasks.first()
        new_status = self._map_status(entities.new_status)

        with transaction.atomic():
            task.status = new_status
            task.save(update_fields=['status', 'updated_at'])

        logger.info(f"Updated task {task.id} status to {new_status}")

        return {
            'type': 'task_updated',
            'task': self._task_to_dict(task),
        }

    def _query_tasks(
        self, intent_result: IntentExtractionResult
    ) -> Dict[str, Any]:
        """Query tasks based on filters."""
        filters = intent_result.entities.filters
        queryset = Task.objects.all()

        if filters:
            if filters.status:
                queryset = queryset.filter(status=filters.status.value)
            if filters.priority:
                queryset = queryset.filter(priority=filters.priority.value)
            if filters.due_date_start:
                queryset = queryset.filter(due_date__gte=filters.due_date_start)
            if filters.due_date_end:
                queryset = queryset.filter(due_date__lte=filters.due_date_end)

        tasks = queryset[:20]  # Limit results
        tasks_list = [self._task_to_dict(t) for t in tasks]

        return {
            'type': 'tasks_queried',
            'tasks': tasks_list,
            'total_count': queryset.count(),
        }

    @staticmethod
    def _map_priority(priority: Optional[TaskPriority]) -> str:
        """Map Pydantic priority to Django model choice."""
        if priority is None:
            return Task.Priority.MEDIUM
        return priority.value

    @staticmethod
    def _map_status(status: Optional[TaskStatus]) -> str:
        """Map Pydantic status to Django model choice."""
        if status is None:
            return Task.Status.PENDING
        return status.value

    @staticmethod
    def _task_to_dict(task: Task) -> Dict[str, Any]:
        """Serialize a task to a dict."""
        return {
            'id': str(task.id),
            'title': task.title,
            'description': task.description,
            'status': task.status,
            'priority': task.priority,
            'due_date': task.due_date.isoformat() if task.due_date else None,
            'created_at': task.created_at.isoformat(),
            'updated_at': task.updated_at.isoformat(),
        }
