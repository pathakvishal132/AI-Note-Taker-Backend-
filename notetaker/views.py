"""Health check view."""
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from django.db import connection
import logging

logger = logging.getLogger(__name__)


@api_view(['GET'])
@throttle_classes([])
def health_check(request):
    """Health check endpoint with dependency status."""
    health = {
        'status': 'healthy',
        'dependencies': {}
    }

    # Check database
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        health['dependencies']['database'] = 'healthy'
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        health['dependencies']['database'] = 'unhealthy'
        health['status'] = 'degraded'

    # Check STT model availability (non-blocking)
    try:
        from notes.services.transcription import TranscriptionService
        stt_ready = TranscriptionService.is_model_loaded()
        health['dependencies']['stt'] = 'ready' if stt_ready else 'not_loaded'
    except Exception:
        health['dependencies']['stt'] = 'not_available'

    # LLM is optional - don't degrade health for it
    from django.conf import settings
    health['dependencies']['llm'] = 'configured' if settings.LLM_API_KEY else 'not_configured'

    return Response(health)
