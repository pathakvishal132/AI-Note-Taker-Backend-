"""Admin configuration for Notes."""
from django.contrib import admin
from .models import Note


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ['id', 'source', 'short_transcript', 'task', 'created_at']
    list_filter = ['source', 'created_at']
    search_fields = ['raw_transcript']
    readonly_fields = ['id', 'created_at']

    def short_transcript(self, obj):
        return obj.raw_transcript[:100]
    short_transcript.short_description = 'Transcript'
