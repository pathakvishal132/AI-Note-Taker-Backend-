"""Note model."""
import uuid
from django.db import models


class Note(models.Model):
    """Represents a note created from voice or text input."""

    class Source(models.TextChoices):
        VOICE = 'voice', 'Voice'
        TEXT = 'text', 'Text'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    raw_transcript = models.TextField(help_text="The raw transcribed or entered text")
    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.TEXT,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # Optional link to a task created from this note
    task = models.ForeignKey(
        'tasks.Task',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='source_notes',
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at', 'source'], name='note_created_source_idx'),
        ]

    def __str__(self):
        preview = self.raw_transcript[:80]
        return f"Note({self.id}): {preview}"
