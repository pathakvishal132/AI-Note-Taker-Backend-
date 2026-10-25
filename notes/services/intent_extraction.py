"""Intent extraction service - orchestrates LLM calls and validates output."""
import json
import logging
from datetime import date, timedelta
from typing import Optional

from django.conf import settings
from django.utils import timezone

from .schemas import IntentExtractionResult, IntentType
from .llm_provider import get_llm_provider, LLMProviderError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an AI assistant that extracts structured intent from user messages related to note-taking and task management.

CURRENT DATE: {current_date}
CURRENT DAY OF WEEK: {day_of_week}

Analyze the user's message and extract one of these intents:

1. **CREATE_TASK** - User wants to create a new task/reminder/to-do
   Extract: title, description (if provided), due_date (YYYY-MM-DD format), priority (LOW/MEDIUM/HIGH)
   Rules:
   - Always extract a clear, concise title
   - Only set due_date if the user explicitly mentions a date or relative time ("by Friday", "tomorrow", "next week")
   - Convert relative dates to absolute dates based on the current date provided above
   - "by Friday" means the coming Friday from today
   - "tomorrow" means {tomorrow_date}
   - "next week" means the Monday of next week
   - Default priority is MEDIUM if not specified
   - Set priority HIGH only if user says "high priority", "urgent", "important", "ASAP", or similar

2. **UPDATE_TASK_STATUS** - User wants to change a task's status
   Extract: task_identifier (text to search for the task), new_status (PENDING/IN_PROGRESS/COMPLETED/CANCELLED)
   Rules:
   - "mark as done/complete/finished" = COMPLETED
   - "mark as cancelled/cancel" = CANCELLED  
   - "start working on/begin" = IN_PROGRESS
   - "reopen/reset" = PENDING
   - task_identifier should be descriptive text to find the task

3. **QUERY_TASKS** - User wants to see/list/find tasks
   Extract: filters (status, priority, due_date_start, due_date_end in YYYY-MM-DD)
   Rules:
   - "pending tasks" = filter by status PENDING
   - "this week" = due_date_start={week_start}, due_date_end={week_end}
   - "overdue" = due_date_end={yesterday}
   - "high priority" = filter by priority HIGH

4. **GENERAL_NOTE** - Message is a general note, idea, or doesn't fit above categories
   No specific entities needed.

If the message is ambiguous between UPDATE_TASK_STATUS and another intent, and you cannot determine which task to update, set needs_clarification=true and provide a clarification_question.

Respond ONLY with valid JSON in this exact format:
{{
  "intent": "CREATE_TASK|UPDATE_TASK_STATUS|QUERY_TASKS|GENERAL_NOTE",
  "entities": {{
    "title": "string or null",
    "description": "string or null",
    "due_date": "YYYY-MM-DD or null",
    "priority": "LOW|MEDIUM|HIGH or null",
    "task_identifier": "string or null",
    "new_status": "PENDING|IN_PROGRESS|COMPLETED|CANCELLED or null",
    "filters": {{
      "status": "PENDING|IN_PROGRESS|COMPLETED|CANCELLED or null",
      "priority": "LOW|MEDIUM|HIGH or null",
      "due_date_start": "YYYY-MM-DD or null",
      "due_date_end": "YYYY-MM-DD or null"
    }} or null
  }},
  "needs_clarification": false,
  "clarification_question": null
}}

Do NOT invent dates the user didn't mention. Do NOT guess or hallucinate information."""


class IntentExtractionError(Exception):
    """Raised when intent extraction fails."""
    pass


class IntentExtractionService:
    """Service for extracting intent from transcripts using LLM."""

    def __init__(self):
        self.max_retries = getattr(settings, 'LLM_MAX_RETRIES', 2)

    def _build_system_prompt(self) -> str:
        """Build the system prompt with current date context."""
        now = timezone.now()
        today = now.date()
        tomorrow = today + timedelta(days=1)

        # Calculate this week's Monday and Sunday
        days_since_monday = today.weekday()
        week_start = today - timedelta(days=days_since_monday)
        week_end = week_start + timedelta(days=6)
        yesterday = today - timedelta(days=1)

        return SYSTEM_PROMPT.format(
            current_date=today.isoformat(),
            day_of_week=today.strftime('%A'),
            tomorrow_date=tomorrow.isoformat(),
            week_start=week_start.isoformat(),
            week_end=week_end.isoformat(),
            yesterday=yesterday.isoformat(),
        )

    def extract_intent(self, transcript: str) -> IntentExtractionResult:
        """Extract intent from a transcript.

        Args:
            transcript: The text to analyze.

        Returns:
            Validated IntentExtractionResult.

        Raises:
            IntentExtractionError: If extraction fails after retries.
        """
        if not transcript or not transcript.strip():
            return IntentExtractionResult(
                intent=IntentType.GENERAL_NOTE,
                needs_clarification=False,
            )

        provider = get_llm_provider()
        system_prompt = self._build_system_prompt()
        last_error = None

        for attempt in range(1, self.max_retries + 2):  # +1 for initial, +1 for range
            try:
                raw_response = provider.chat_completion(system_prompt, transcript)
                result = self._parse_and_validate(raw_response)
                logger.info(
                    f"Intent extracted: {result.intent.value} "
                    f"(attempt {attempt})"
                )
                return result

            except (json.JSONDecodeError, ValueError) as e:
                last_error = e
                logger.warning(
                    f"Intent extraction parse error (attempt {attempt}): {e}"
                )
                if attempt <= self.max_retries:
                    continue
            except LLMProviderError as e:
                last_error = e
                logger.error(f"LLM provider error (attempt {attempt}): {e}")
                if attempt <= self.max_retries:
                    continue
            except Exception as e:
                last_error = e
                logger.error(
                    f"Unexpected error in intent extraction "
                    f"(attempt {attempt}): {e}"
                )
                break

        raise IntentExtractionError(
            f"Intent extraction failed after {self.max_retries + 1} attempts: {last_error}"
        )

    def _parse_and_validate(self, raw_response: str) -> IntentExtractionResult:
        """Parse and validate the LLM's JSON response."""
        # Try to extract JSON from the response
        response_text = raw_response.strip()

        # Handle markdown code blocks
        if response_text.startswith('```'):
            lines = response_text.split('\n')
            # Remove first and last lines (```json and ```)
            json_lines = []
            in_block = False
            for line in lines:
                if line.strip().startswith('```') and not in_block:
                    in_block = True
                    continue
                elif line.strip() == '```' and in_block:
                    break
                elif in_block:
                    json_lines.append(line)
            response_text = '\n'.join(json_lines)

        data = json.loads(response_text)

        # Validate with Pydantic
        result = IntentExtractionResult.model_validate(data)

        # Additional validation
        validation_errors = result.validate_for_intent()
        if validation_errors and not result.needs_clarification:
            raise ValueError(
                f"Validation errors for {result.intent}: {validation_errors}"
            )

        return result
