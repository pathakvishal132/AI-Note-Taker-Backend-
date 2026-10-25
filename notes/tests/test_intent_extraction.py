"""Tests for intent extraction schemas and service."""
import json
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone

from notes.services.schemas import (
    IntentExtractionResult, IntentType, IntentEntities,
    TaskStatus, TaskPriority, TaskFilters,
)
from notes.services.intent_extraction import IntentExtractionService, IntentExtractionError
from notes.services.llm_provider import LLMProviderError


class TestIntentSchemas(TestCase):
    """Test Pydantic schema validation."""

    def test_valid_create_task(self):
        data = {
            "intent": "CREATE_TASK",
            "entities": {
                "title": "Review the PR",
                "description": "Check the authentication module",
                "due_date": "2026-10-25",
                "priority": "HIGH",
            },
            "needs_clarification": False,
        }
        result = IntentExtractionResult.model_validate(data)
        self.assertEqual(result.intent, IntentType.CREATE_TASK)
        self.assertEqual(result.entities.title, "Review the PR")
        self.assertEqual(result.entities.priority, TaskPriority.HIGH)
        self.assertEqual(result.entities.due_date, date(2026, 10, 25))
        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.validate_for_intent(), [])

    def test_valid_update_task_status(self):
        data = {
            "intent": "UPDATE_TASK_STATUS",
            "entities": {
                "task_identifier": "login bug",
                "new_status": "COMPLETED",
            },
            "needs_clarification": False,
        }
        result = IntentExtractionResult.model_validate(data)
        self.assertEqual(result.intent, IntentType.UPDATE_TASK_STATUS)
        self.assertEqual(result.entities.task_identifier, "login bug")
        self.assertEqual(result.entities.new_status, TaskStatus.COMPLETED)

    def test_valid_query_tasks(self):
        data = {
            "intent": "QUERY_TASKS",
            "entities": {
                "filters": {
                    "status": "PENDING",
                    "priority": "HIGH",
                    "due_date_start": "2026-10-20",
                    "due_date_end": "2026-10-26",
                }
            },
            "needs_clarification": False,
        }
        result = IntentExtractionResult.model_validate(data)
        self.assertEqual(result.intent, IntentType.QUERY_TASKS)
        self.assertIsNotNone(result.entities.filters)
        self.assertEqual(result.entities.filters.status, TaskStatus.PENDING)

    def test_valid_general_note(self):
        data = {
            "intent": "GENERAL_NOTE",
            "entities": {},
            "needs_clarification": False,
        }
        result = IntentExtractionResult.model_validate(data)
        self.assertEqual(result.intent, IntentType.GENERAL_NOTE)

    def test_invalid_intent(self):
        data = {
            "intent": "INVALID_INTENT",
            "entities": {},
        }
        with self.assertRaises(Exception):
            IntentExtractionResult.model_validate(data)

    def test_invalid_priority(self):
        data = {
            "intent": "CREATE_TASK",
            "entities": {
                "title": "Test",
                "priority": "SUPER_HIGH",
            },
        }
        with self.assertRaises(Exception):
            IntentExtractionResult.model_validate(data)

    def test_invalid_status(self):
        data = {
            "intent": "UPDATE_TASK_STATUS",
            "entities": {
                "task_identifier": "test",
                "new_status": "DONE",
            },
        }
        with self.assertRaises(Exception):
            IntentExtractionResult.model_validate(data)

    def test_create_task_missing_title(self):
        data = {
            "intent": "CREATE_TASK",
            "entities": {
                "due_date": "2026-10-25",
            },
            "needs_clarification": False,
        }
        result = IntentExtractionResult.model_validate(data)
        errors = result.validate_for_intent()
        self.assertTrue(any("title" in e.lower() for e in errors))

    def test_update_task_missing_fields(self):
        data = {
            "intent": "UPDATE_TASK_STATUS",
            "entities": {},
            "needs_clarification": False,
        }
        result = IntentExtractionResult.model_validate(data)
        errors = result.validate_for_intent()
        self.assertTrue(len(errors) >= 2)

    def test_ambiguous_request_with_clarification(self):
        data = {
            "intent": "UPDATE_TASK_STATUS",
            "entities": {
                "task_identifier": "bug",
            },
            "needs_clarification": True,
            "clarification_question": "Which bug do you mean?",
        }
        result = IntentExtractionResult.model_validate(data)
        self.assertTrue(result.needs_clarification)
        self.assertEqual(result.clarification_question, "Which bug do you mean?")

    def test_missing_due_date_not_invented(self):
        data = {
            "intent": "CREATE_TASK",
            "entities": {
                "title": "Do something",
            },
            "needs_clarification": False,
        }
        result = IntentExtractionResult.model_validate(data)
        self.assertIsNone(result.entities.due_date)


class TestIntentExtractionService(TestCase):
    """Test the intent extraction service with mocked LLM."""

    def _mock_llm_response(self, data):
        """Helper to create a mock LLM provider that returns the given data."""
        mock_provider = MagicMock()
        mock_provider.chat_completion.return_value = json.dumps(data)
        return mock_provider

    @patch('notes.services.intent_extraction.get_llm_provider')
    def test_extract_create_task(self, mock_get_provider):
        mock_get_provider.return_value = self._mock_llm_response({
            "intent": "CREATE_TASK",
            "entities": {
                "title": "Review PR",
                "priority": "HIGH",
                "due_date": "2026-10-25",
            },
            "needs_clarification": False,
        })

        service = IntentExtractionService()
        result = service.extract_intent("Remind me to review the PR by Friday, high priority")

        self.assertEqual(result.intent, IntentType.CREATE_TASK)
        self.assertEqual(result.entities.title, "Review PR")

    @patch('notes.services.intent_extraction.get_llm_provider')
    def test_extract_general_note(self, mock_get_provider):
        mock_get_provider.return_value = self._mock_llm_response({
            "intent": "GENERAL_NOTE",
            "entities": {},
            "needs_clarification": False,
        })

        service = IntentExtractionService()
        result = service.extract_intent("Interesting idea: use Qdrant")

        self.assertEqual(result.intent, IntentType.GENERAL_NOTE)

    @patch('notes.services.intent_extraction.get_llm_provider')
    def test_malformed_json_retries(self, mock_get_provider):
        mock_provider = MagicMock()
        mock_provider.chat_completion.side_effect = [
            "not valid json at all",
            json.dumps({
                "intent": "GENERAL_NOTE",
                "entities": {},
                "needs_clarification": False,
            }),
        ]
        mock_get_provider.return_value = mock_provider

        service = IntentExtractionService()
        result = service.extract_intent("Test message")

        self.assertEqual(result.intent, IntentType.GENERAL_NOTE)
        self.assertEqual(mock_provider.chat_completion.call_count, 2)

    @patch('notes.services.intent_extraction.get_llm_provider')
    def test_malformed_json_all_retries_fail(self, mock_get_provider):
        mock_provider = MagicMock()
        mock_provider.chat_completion.return_value = "not valid json"
        mock_get_provider.return_value = mock_provider

        service = IntentExtractionService()
        with self.assertRaises(IntentExtractionError):
            service.extract_intent("Test message")

    @patch('notes.services.intent_extraction.get_llm_provider')
    def test_llm_timeout(self, mock_get_provider):
        mock_provider = MagicMock()
        mock_provider.chat_completion.side_effect = LLMProviderError("Timeout")
        mock_get_provider.return_value = mock_provider

        service = IntentExtractionService()
        with self.assertRaises(IntentExtractionError):
            service.extract_intent("Test message")

    def test_empty_transcript(self):
        service = IntentExtractionService()
        result = service.extract_intent("")
        self.assertEqual(result.intent, IntentType.GENERAL_NOTE)

    @patch('notes.services.intent_extraction.get_llm_provider')
    def test_unsupported_intent_in_response(self, mock_get_provider):
        mock_provider = MagicMock()
        mock_provider.chat_completion.return_value = json.dumps({
            "intent": "DELETE_EVERYTHING",
            "entities": {},
        })
        mock_get_provider.return_value = mock_provider

        service = IntentExtractionService()
        with self.assertRaises(IntentExtractionError):
            service.extract_intent("Delete everything")
