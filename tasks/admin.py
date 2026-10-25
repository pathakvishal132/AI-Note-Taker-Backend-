"""Admin configuration for Tasks."""
from django.contrib import admin
from .models import Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'status', 'priority', 'due_date', 'created_at']
    list_filter = ['status', 'priority', 'due_date']
    search_fields = ['title', 'description']
    readonly_fields = ['id', 'created_at', 'updated_at']
