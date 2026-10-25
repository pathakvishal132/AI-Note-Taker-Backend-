"""Serializers for the Tasks app."""
from rest_framework import serializers
from .models import Task


class TaskSerializer(serializers.ModelSerializer):
    """Full serializer for Task model."""

    class Meta:
        model = Task
        fields = [
            'id', 'title', 'description', 'status', 'priority',
            'due_date', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class TaskUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating task fields."""

    class Meta:
        model = Task
        fields = ['title', 'description', 'status', 'priority', 'due_date']
        extra_kwargs = {
            'title': {'required': False},
            'description': {'required': False},
            'status': {'required': False},
            'priority': {'required': False},
            'due_date': {'required': False},
        }

    def validate_status(self, value):
        if value and value not in dict(Task.Status.choices):
            raise serializers.ValidationError(
                f"Invalid status. Must be one of: {list(dict(Task.Status.choices).keys())}"
            )
        return value

    def validate_priority(self, value):
        if value and value not in dict(Task.Priority.choices):
            raise serializers.ValidationError(
                f"Invalid priority. Must be one of: {list(dict(Task.Priority.choices).keys())}"
            )
        return value


class TaskListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for task listings."""

    class Meta:
        model = Task
        fields = [
            'id', 'title', 'status', 'priority',
            'due_date', 'created_at', 'updated_at',
        ]
        read_only_fields = fields
