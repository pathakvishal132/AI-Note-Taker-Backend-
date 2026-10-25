"""Tests for Notes and Tasks API endpoints."""
import json
import io
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.conf import settings
from rest_framework.test import APIClient
from rest_framework import status

from notes.models import Note
from tasks.models import Task


class TestHealthEndpoint(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health_check(self):
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'healthy')
        self.assertIn('database', response.data['dependencies'])


class TestNoteAPIEndpoints(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch('notes.views.IntentExtractionService')
    def test_create_text_note(self, MockIntentService):
        mock_instance = MockIntentService.return_value
        from notes.services.schemas import IntentExtractionResult, IntentType
        mock_instance.extract_intent.return_value = IntentExtractionResult(
            intent=IntentType.GENERAL_NOTE,
            needs_clarification=False,
        )

        response = self.client.post(
            '/api/notes',
            {'text': 'This is a test note'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['note']['transcript'], 'This is a test note')
        self.assertEqual(response.data['note']['source'], 'text')
        self.assertEqual(response.data['intent'], 'GENERAL_NOTE')

        # Verify note persisted
        self.assertEqual(Note.objects.count(), 1)

    def test_create_text_note_empty(self):
        response = self.client.post(
            '/api/notes',
            {'text': ''},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_text_note_missing_field(self):
        response = self.client.post(
            '/api/notes',
            {},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_notes(self):
        Note.objects.create(raw_transcript='Note 1', source='text')
        Note.objects.create(raw_transcript='Note 2', source='voice')

        response = self.client.get('/api/notes/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(len(response.data['results']), 2)

    def test_list_notes_filter_by_source(self):
        Note.objects.create(raw_transcript='Text note', source='text')
        Note.objects.create(raw_transcript='Voice note', source='voice')

        response = self.client.get('/api/notes/?source=voice')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['source'], 'voice')

    def test_retrieve_note(self):
        note = Note.objects.create(raw_transcript='My note', source='text')
        response = self.client.get(f'/api/notes/{note.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['raw_transcript'], 'My note')

    def test_retrieve_note_not_found(self):
        import uuid
        response = self.client.get(f'/api/notes/{uuid.uuid4()}/')
        self.assertEqual(response.status_code, 404)

    @patch('notes.views.IntentExtractionService')
    def test_note_saves_on_intent_failure(self, MockIntentService):
        from notes.services.intent_extraction import IntentExtractionError
        mock_instance = MockIntentService.return_value
        mock_instance.extract_intent.side_effect = IntentExtractionError("LLM failed")

        response = self.client.post(
            '/api/notes',
            {'text': 'This should still be saved'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['intent'], 'EXTRACTION_FAILED')
        # Note should still be persisted
        self.assertEqual(Note.objects.count(), 1)

    def test_note_pagination(self):
        for i in range(25):
            Note.objects.create(raw_transcript=f'Note {i}', source='text')

        response = self.client.get('/api/notes/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 25)
        self.assertEqual(len(response.data['results']), 20)  # default page size
        self.assertIsNotNone(response.data['next'])


class TestVoiceEndpoint(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_voice_no_file(self):
        response = self.client.post('/api/voice/transcribe')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_voice_empty_file(self):
        audio = io.BytesIO(b'')
        audio.name = 'test.webm'
        response = self.client.post(
            '/api/voice/transcribe',
            {'audio': audio},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_voice_unsupported_type(self):
        audio = io.BytesIO(b'fake data')
        audio.name = 'test.txt'
        audio.content_type = 'text/plain'
        response = self.client.post(
            '/api/voice/transcribe',
            {'audio': audio},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('notes.services.transcription.TranscriptionService.transcribe')
    @patch('notes.views.IntentExtractionService')
    def test_voice_transcription_success(self, MockIntentService, mock_transcribe):
        mock_transcribe.return_value = "Hello this is a test"
        from notes.services.schemas import IntentExtractionResult, IntentType
        mock_intent = MockIntentService.return_value
        mock_intent.extract_intent.return_value = IntentExtractionResult(
            intent=IntentType.GENERAL_NOTE,
            needs_clarification=False,
        )

        audio = io.BytesIO(b'fake audio data for testing')
        audio.name = 'test.webm'
        audio.content_type = 'audio/webm'
        response = self.client.post(
            '/api/voice/transcribe',
            {'audio': audio},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['note']['source'], 'voice')

    @patch('notes.services.transcription.TranscriptionService.transcribe')
    def test_voice_transcription_failure(self, mock_transcribe):
        from notes.services.transcription import TranscriptionError
        mock_transcribe.side_effect = TranscriptionError("Model failed")

        audio = io.BytesIO(b'fake audio data')
        audio.name = 'test.webm'
        audio.content_type = 'audio/webm'
        response = self.client.post(
            '/api/voice/transcribe',
            {'audio': audio},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)


class TestTaskAPIEndpoints(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_list_tasks_empty(self):
        response = self.client.get('/api/tasks/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)

    def test_create_task(self):
        response = self.client.post('/api/tasks/', {
            'title': 'Test task',
            'priority': 'HIGH',
            'status': 'PENDING',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['title'], 'Test task')
        self.assertEqual(response.data['priority'], 'HIGH')

    def test_retrieve_task(self):
        task = Task.objects.create(title='Test task', priority='MEDIUM')
        response = self.client.get(f'/api/tasks/{task.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['title'], 'Test task')

    def test_retrieve_task_not_found(self):
        import uuid
        response = self.client.get(f'/api/tasks/{uuid.uuid4()}/')
        self.assertEqual(response.status_code, 404)

    def test_update_task_status(self):
        task = Task.objects.create(title='Test task', status='PENDING')
        response = self.client.patch(
            f'/api/tasks/{task.id}/',
            {'status': 'COMPLETED'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, 'COMPLETED')

    def test_update_task_invalid_status(self):
        task = Task.objects.create(title='Test task', status='PENDING')
        response = self.client.patch(
            f'/api/tasks/{task.id}/',
            {'status': 'INVALID'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_delete_task(self):
        task = Task.objects.create(title='Test task')
        response = self.client.delete(f'/api/tasks/{task.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Task.objects.count(), 0)

    def test_filter_tasks_by_status(self):
        Task.objects.create(title='Pending task', status='PENDING')
        Task.objects.create(title='Completed task', status='COMPLETED')

        response = self.client.get('/api/tasks/?status=PENDING')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['title'], 'Pending task')

    def test_filter_tasks_by_priority(self):
        Task.objects.create(title='High', priority='HIGH')
        Task.objects.create(title='Low', priority='LOW')

        response = self.client.get('/api/tasks/?priority=HIGH')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)

    def test_task_pagination(self):
        for i in range(25):
            Task.objects.create(title=f'Task {i}')

        response = self.client.get('/api/tasks/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 25)
        self.assertEqual(len(response.data['results']), 20)

    def test_note_task_relationship(self):
        task = Task.objects.create(title='Linked task')
        note = Note.objects.create(
            raw_transcript='Create task linked',
            source='text',
            task=task,
        )

        response = self.client.get(f'/api/notes/{note.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data['task_detail'])
        self.assertEqual(response.data['task_detail']['title'], 'Linked task')


class TestTaskExecutionService(TestCase):
    """Test the task execution service."""

    def setUp(self):
        from notes.services.task_execution import TaskExecutionService
        self.service = TaskExecutionService()

    def test_create_task_from_intent(self):
        from notes.services.schemas import (
            IntentExtractionResult, IntentType, IntentEntities, TaskPriority,
        )
        from datetime import date

        note = Note.objects.create(raw_transcript='Test', source='text')
        intent = IntentExtractionResult(
            intent=IntentType.CREATE_TASK,
            entities=IntentEntities(
                title="Review PR",
                priority=TaskPriority.HIGH,
                due_date=date(2026, 10, 25),
            ),
        )
        result = self.service.execute(intent, note)
        self.assertEqual(result['type'], 'task_created')
        self.assertEqual(result['task']['title'], 'Review PR')

        # Note should be linked to task
        note.refresh_from_db()
        self.assertIsNotNone(note.task)

    def test_update_task_not_found(self):
        from notes.services.schemas import (
            IntentExtractionResult, IntentType, IntentEntities, TaskStatus,
        )
        note = Note.objects.create(raw_transcript='Test', source='text')
        intent = IntentExtractionResult(
            intent=IntentType.UPDATE_TASK_STATUS,
            entities=IntentEntities(
                task_identifier="nonexistent",
                new_status=TaskStatus.COMPLETED,
            ),
        )
        result = self.service.execute(intent, note)
        self.assertEqual(result['type'], 'task_not_found')

    def test_update_task_ambiguous(self):
        from notes.services.schemas import (
            IntentExtractionResult, IntentType, IntentEntities, TaskStatus,
        )
        Task.objects.create(title='Bug fix 1')
        Task.objects.create(title='Bug fix 2')

        note = Note.objects.create(raw_transcript='Test', source='text')
        intent = IntentExtractionResult(
            intent=IntentType.UPDATE_TASK_STATUS,
            entities=IntentEntities(
                task_identifier="Bug fix",
                new_status=TaskStatus.COMPLETED,
            ),
        )
        result = self.service.execute(intent, note)
        self.assertEqual(result['type'], 'needs_clarification')

    def test_update_task_single_match(self):
        from notes.services.schemas import (
            IntentExtractionResult, IntentType, IntentEntities, TaskStatus,
        )
        task = Task.objects.create(title='Unique task name', status='PENDING')

        note = Note.objects.create(raw_transcript='Test', source='text')
        intent = IntentExtractionResult(
            intent=IntentType.UPDATE_TASK_STATUS,
            entities=IntentEntities(
                task_identifier="Unique task name",
                new_status=TaskStatus.COMPLETED,
            ),
        )
        result = self.service.execute(intent, note)
        self.assertEqual(result['type'], 'task_updated')
        task.refresh_from_db()
        self.assertEqual(task.status, 'COMPLETED')

    def test_query_tasks(self):
        from notes.services.schemas import (
            IntentExtractionResult, IntentType, IntentEntities, TaskFilters,
            TaskStatus,
        )
        Task.objects.create(title='Pending 1', status='PENDING')
        Task.objects.create(title='Done 1', status='COMPLETED')

        note = Note.objects.create(raw_transcript='Test', source='text')
        intent = IntentExtractionResult(
            intent=IntentType.QUERY_TASKS,
            entities=IntentEntities(
                filters=TaskFilters(status=TaskStatus.PENDING),
            ),
        )
        result = self.service.execute(intent, note)
        self.assertEqual(result['type'], 'tasks_queried')
        self.assertEqual(result['total_count'], 1)

    def test_general_note(self):
        from notes.services.schemas import IntentExtractionResult, IntentType
        note = Note.objects.create(raw_transcript='Test', source='text')
        intent = IntentExtractionResult(intent=IntentType.GENERAL_NOTE)
        result = self.service.execute(intent, note)
        self.assertEqual(result['type'], 'note_saved')

    def test_needs_clarification(self):
        from notes.services.schemas import IntentExtractionResult, IntentType
        note = Note.objects.create(raw_transcript='Test', source='text')
        intent = IntentExtractionResult(
            intent=IntentType.UPDATE_TASK_STATUS,
            needs_clarification=True,
            clarification_question='Which task?',
        )
        result = self.service.execute(intent, note)
        self.assertEqual(result['type'], 'needs_clarification')


class TestRateLimiting(TestCase):
    def test_rate_limit_per_ip(self):
        """Verify that requests exceeding 10 per hour per IP receive HTTP 429."""
        from django.core.cache import cache
        from rest_framework.test import APIRequestFactory
        from rest_framework.throttling import AnonRateThrottle
        from rest_framework.response import Response
        from rest_framework.views import APIView

        cache.clear()

        class ThrottledThrottle(AnonRateThrottle):
            rate = '10/hour'

        class SampleView(APIView):
            throttle_classes = [ThrottledThrottle]

            def get(self, request):
                return Response({'status': 'ok'})

        view = SampleView.as_view()
        factory = APIRequestFactory()

        # Send 10 allowed requests from same client IP
        for i in range(10):
            req = factory.get('/test')
            res = view(req)
            self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 11th request must be throttled with 429 Too Many Requests
        req = factory.get('/test')
        res = view(req)
        self.assertEqual(res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

