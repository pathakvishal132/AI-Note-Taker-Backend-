"""URL configuration for the Notes app."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import voice_transcribe, create_text_note, NoteViewSet

router = DefaultRouter()
router.register(r'notes', NoteViewSet, basename='note')

urlpatterns = [
    path('voice/transcribe', voice_transcribe, name='voice-transcribe'),
    path('notes', create_text_note, name='create-text-note'),
    path('', include(router.urls)),
]
