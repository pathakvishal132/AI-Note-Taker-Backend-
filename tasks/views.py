"""Views for the Tasks app."""
from rest_framework import viewsets, status
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter
from drf_spectacular.utils import extend_schema

from .models import Task
from .serializers import TaskSerializer, TaskUpdateSerializer, TaskListSerializer


class TaskViewSet(viewsets.ModelViewSet):
    """ViewSet for Task CRUD operations."""
    queryset = Task.objects.all()
    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_fields = {
        'status': ['exact'],
        'priority': ['exact'],
        'due_date': ['gte', 'lte', 'exact'],
        'created_at': ['gte', 'lte'],
    }
    ordering_fields = ['created_at', 'updated_at', 'due_date', 'priority']
    ordering = ['-created_at']
    search_fields = ['title', 'description']

    def get_serializer_class(self):
        if self.action == 'list':
            return TaskListSerializer
        if self.action in ('partial_update', 'update'):
            return TaskUpdateSerializer
        return TaskSerializer

    @extend_schema(summary="List all tasks with filters")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Retrieve a single task")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(summary="Create a new task manually")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(summary="Update task fields")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(summary="Delete a task")
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {'message': 'Task deleted successfully.'},
            status=status.HTTP_200_OK,
        )
