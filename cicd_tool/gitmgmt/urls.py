from django.urls import path, re_path
from . import views
from .views import GitService
from django.contrib.auth import views as auth_views


urlpatterns = [
    # Repository management
    path('', auth_views.LoginView.as_view(template_name='gitmgmt/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

    path('repositories/', views.repository_list, name='repository_list'),
    path('repositories/create/', views.create_repository, name='create_repository'),
    path('repositories/<int:repository_id>/', views.repository_detail, name='repository_detail'),
    path('repositories/<int:repository_id>/toggle_favorite/', views.toggle_favorite, name='toggle_favorite'),
    path('repositories/<int:repository_id>/logs/', views.view_logs, name='view_logs'),

    # File management
    path('repositories/<int:repository_id>/upload/', views.upload_file, name='upload_file'),
    path('repositories/<int:repository_id>/edit/<path:file_path>/', views.edit_and_save_file, name='edit_and_save_file'),

    # Branch management
    path('repositories/<int:repository_id>/create-branch/', views.create_branch, name='create_branch'),
    path('repositories/<int:repository_id>/merge/', views.merge_branch, name='merge_branch'),  # ✅ **New route for merging branches**

    # Pull request management
    path('repositories/<int:repository_id>/pull-request/create/', views.create_pull_request, name='create_pull_request'),
    path('pull-requests/<int:pull_request_id>/', views.pull_request_detail, name='pull_request_detail'),
    path('pull-requests/<int:pull_request_id>/merge/', views.merge_pull_request, name='merge_pull_request'),
    path('pull-requests/<int:pull_request_id>/close/', views.close_pull_request, name='close_pull_request'),

    # Git-specific URLs
    re_path(r'^repos/(?P<repo_name>[\w\-\.]+)/info/refs$', GitService.as_view(), name='git_info_refs'),
    re_path(r'^repos/(?P<repo_name>[\w\-\.]+)/(?P<path>git-upload-pack)$', GitService.as_view(), name='git_upload_pack'),
    re_path(r'^repos/(?P<repo_name>[\w\-\.]+)/(?P<path>git-receive-pack)$', GitService.as_view(), name='git_receive_pack'),
    re_path(r'^repos/(?P<repo_name>[\w\-\.]+)/(?P<path>.+)$', GitService.as_view(), name='git_static_files'),
]
