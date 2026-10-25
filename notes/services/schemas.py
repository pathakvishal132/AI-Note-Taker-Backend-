"""Pydantic schemas for intent extraction validation."""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator


class IntentType(str, Enum):
    CREATE_TASK = "CREATE_TASK"
    UPDATE_TASK_STATUS = "UPDATE_TASK_STATUS"
    QUERY_TASKS = "QUERY_TASKS"
    GENERAL_NOTE = "GENERAL_NOTE"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TaskPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TaskFilters(BaseModel):
    """Filters for QUERY_TASKS intent."""
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    due_date_start: Optional[date] = None
    due_date_end: Optional[date] = None


class IntentEntities(BaseModel):
    """Entities extracted from the transcript."""
    # CREATE_TASK fields
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[date] = None
    priority: Optional[TaskPriority] = None

    # UPDATE_TASK_STATUS fields
    task_identifier: Optional[str] = Field(
        None,
        description="A description or keyword to identify the task to update"
    )
    new_status: Optional[TaskStatus] = None

    # QUERY_TASKS fields
    filters: Optional[TaskFilters] = None

    @field_validator('title')
    @classmethod
    def title_not_empty(cls, v):
        if v is not None and not v.strip():
            return None
        return v

    @field_validator('due_date')
    @classmethod
    def validate_due_date(cls, v):
        if v is not None and isinstance(v, str):
            try:
                return date.fromisoformat(v)
            except ValueError:
                return None
        return v


class IntentExtractionResult(BaseModel):
    """Validated result from LLM intent extraction."""
    intent: IntentType
    entities: IntentEntities = Field(default_factory=IntentEntities)
    needs_clarification: bool = False
    clarification_question: Optional[str] = None

    def validate_for_intent(self) -> List[str]:
        """Validate that required fields are present for the detected intent."""
        errors = []

        if self.intent == IntentType.CREATE_TASK:
            if not self.entities.title:
                errors.append("CREATE_TASK requires a title")

        elif self.intent == IntentType.UPDATE_TASK_STATUS:
            if not self.entities.task_identifier:
                errors.append("UPDATE_TASK_STATUS requires a task_identifier")
            if not self.entities.new_status:
                errors.append("UPDATE_TASK_STATUS requires new_status")

        return errors
