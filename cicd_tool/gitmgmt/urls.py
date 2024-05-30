from django.urls import path
from . import views
from .views import GitService

urlpatterns = [
    path('repositories/', views.repository_list, name='repository_list'),
    path('repositories/create/', views.create_repository, name='create_repository'),
    path('repositories/<int:repository_id>/', views.repository_detail, name='repository_detail'),
    path('repositories/<int:repository_id>/pull_request/create/', views.create_pull_request, name='create_pull_request'),
    path('pull_requests/<int:pull_request_id>/', views.pull_request_detail, name='pull_request_detail'),
    path('repositories/<int:repository_id>/upload/', views.upload_file, name='upload_file'),
    path('repositories/<int:repository_id>/create-branch/', views.create_branch, name='create_branch'),
    path('<int:repository_id>/toggle_favorite/', views.toggle_favorite, name='toggle_favorite'),
    path('repositories/<int:repository_id>/logs/', views.view_logs, name='view_logs'),
    path('edit_and_save_file/<int:repository_id>/<path:file_path>/', views.edit_and_save_file, name='edit_and_save_file'),
    path('repos/<str:repo_name>.git/', GitService.as_view(), name='git_service'),
]
