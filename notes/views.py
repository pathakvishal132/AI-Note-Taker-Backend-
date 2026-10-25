"""Views for the Notes app."""
import logging
import os

from django.conf import settings
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.parsers import MultiPartParser
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from drf_spectacular.utils import extend_schema, OpenApiParameter

from .models import Note
from .serializers import (
    NoteSerializer, NoteListSerializer,
    TextNoteInputSerializer,
)
from .services.intent_extraction import IntentExtractionService, IntentExtractionError
from .services.task_execution import TaskExecutionService

logger = logging.getLogger(__name__)


class VoiceUploadThrottle(AnonRateThrottle):
    rate = settings.REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {}).get(
        'voice_upload', '30/hour'
    )


def _process_note_pipeline(transcript: str, source: str) -> dict:
    """Shared pipeline for processing a note (voice or text).

    1. Save the note
    2. Extract intent
    3. Execute action
    4. Return structured response

    The note is always saved, even if intent extraction fails.
    """
    # Step 1: Save the raw transcript as a note
    note = Note.objects.create(
        raw_transcript=transcript,
        source=source,
    )

    response_data = {
        'note': {
            'id': str(note.id),
            'transcript': note.raw_transcript,
            'source': note.source,
            'created_at': note.created_at.isoformat(),
        },
        'intent': None,
        'action': None,
    }

    # Step 2: Extract intent
    try:
        intent_service = IntentExtractionService()
        intent_result = intent_service.extract_intent(transcript)
        response_data['intent'] = intent_result.intent.value

        # Step 3: Execute the action
        task_service = TaskExecutionService()
        action_result = task_service.execute(intent_result, note)
        response_data['action'] = action_result

        # Refresh note to get task link
        note.refresh_from_db()
        if note.task_id:
            response_data['note']['task_id'] = str(note.task_id)

    except IntentExtractionError as e:
        logger.error(f"Intent extraction failed for note {note.id}: {e}")
        response_data['intent'] = 'EXTRACTION_FAILED'
        response_data['action'] = {
            'type': 'error',
            'message': (
                'Could not determine intent from your message. '
                'The note has been saved. You can try again.'
            ),
        }
    except Exception as e:
        logger.exception(f"Processing pipeline error for note {note.id}: {e}")
        response_data['intent'] = 'PROCESSING_ERROR'
        response_data['action'] = {
            'type': 'error',
            'message': 'An error occurred while processing your request. The note has been saved.',
        }

    return response_data


@extend_schema(
    summary="Transcribe audio and process intent",
    description="Upload an audio file for transcription, intent extraction, and task management.",
    request={
        'multipart/form-data': {
            'type': 'object',
            'properties': {
                'audio': {
                    'type': 'string',
                    'format': 'binary',
                    'description': 'Audio file (WebM, WAV, MP3, M4A)',
                },
            },
            'required': ['audio'],
        }
    },
)
@api_view(['POST'])
@throttle_classes([VoiceUploadThrottle])
def voice_transcribe(request):
    """POST /api/voice/transcribe - Upload audio, transcribe, extract intent, execute action."""
    audio_file = request.FILES.get('audio')

    if not audio_file:
        return Response(
            {'error': {'message': 'No audio file provided. Send file as "audio" field.'}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Validate file type
    content_type = audio_file.content_type or ''
    allowed_types = getattr(settings, 'ALLOWED_AUDIO_TYPES', [])
    if content_type and allowed_types and content_type not in allowed_types:
        return Response(
            {'error': {'message': f'Unsupported audio format: {content_type}. Supported: {", ".join(allowed_types)}'}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Validate file size
    max_size = getattr(settings, 'MAX_UPLOAD_SIZE_MB', 25) * 1024 * 1024
    if audio_file.size > max_size:
        return Response(
            {'error': {'message': f'File too large. Maximum size: {settings.MAX_UPLOAD_SIZE_MB}MB'}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Validate not empty
    if audio_file.size == 0:
        return Response(
            {'error': {'message': 'Audio file is empty.'}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Transcribe
    try:
        from .services.transcription import TranscriptionService, TranscriptionError
        transcript = TranscriptionService.transcribe(audio_file)
    except TranscriptionError as e:
        logger.error(f"Transcription failed: {e}")
        return Response(
            {'error': {'message': f'Transcription failed: {e}'}},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except Exception as e:
        logger.exception(f"Unexpected transcription error: {e}")
        return Response(
            {'error': {'message': 'An error occurred during transcription.'}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Process through the shared pipeline
    response_data = _process_note_pipeline(transcript, Note.Source.VOICE)
    return Response(response_data, status=status.HTTP_201_CREATED)


@extend_schema(
    summary="Create a text note and process intent",
    description="Submit text for note creation, intent extraction, and task management.",
    request=TextNoteInputSerializer,
)
@api_view(['POST'])
def create_text_note(request):
    """POST /api/notes - Create a note from text input."""
    serializer = TextNoteInputSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {'error': {'message': 'Invalid input', 'details': serializer.errors}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    text = serializer.validated_data['text']
    response_data = _process_note_pipeline(text, Note.Source.TEXT)
    return Response(response_data, status=status.HTTP_201_CREATED)


class NoteViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for listing and retrieving notes."""
    queryset = Note.objects.all()
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = {
        'source': ['exact'],
        'created_at': ['gte', 'lte'],
    }
    ordering_fields = ['created_at']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return NoteListSerializer
        return NoteSerializer
