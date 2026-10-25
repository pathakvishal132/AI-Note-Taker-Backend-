"""Serializers for the Notes app."""
from rest_framework import serializers
from .models import Note
from tasks.serializers import TaskSerializer


class NoteSerializer(serializers.ModelSerializer):
    """Serializer for Note model."""
    task_detail = TaskSerializer(source='task', read_only=True)

    class Meta:
        model = Note
        fields = ['id', 'raw_transcript', 'source', 'created_at', 'task', 'task_detail']
        read_only_fields = ['id', 'created_at', 'task', 'task_detail']


class NoteListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for note listings."""
    task_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Note
        fields = ['id', 'raw_transcript', 'source', 'created_at', 'task_id']
        read_only_fields = fields


class TextNoteInputSerializer(serializers.Serializer):
    """Serializer for text note input."""
    text = serializers.CharField(
        min_length=1,
        max_length=10000,
        help_text="The text content to process",
    )


class VoiceTranscribeResponseSerializer(serializers.Serializer):
    """Serializer for the voice transcribe response."""
    note = serializers.DictField()
    intent = serializers.CharField()
    action = serializers.DictField()
