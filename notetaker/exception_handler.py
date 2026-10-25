"""Custom exception handler for consistent API error responses."""
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """Handle exceptions with consistent JSON error responses."""
    response = exception_handler(exc, context)

    if response is not None:
        error_data = {
            'error': {
                'type': type(exc).__name__,
                'message': str(exc.detail) if hasattr(exc, 'detail') else str(exc),
                'status_code': response.status_code,
            }
        }
        response.data = error_data
        return response

    # Handle unexpected exceptions
    logger.exception(f"Unhandled exception in {context.get('view', 'unknown')}")
    return Response(
        {
            'error': {
                'type': 'InternalServerError',
                'message': 'An unexpected error occurred. Please try again.',
                'status_code': 500,
            }
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
