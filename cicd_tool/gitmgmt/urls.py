from django.urls import path, re_path
from . import views
from .views import GitService
from django.contrib.auth import views as auth_views


urlpatterns = [
    # Repository management
    path('', auth_views.LoginView.as_view(template_name='gitmgmt/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('signup/', views.signup, name='signup'),
    path('profile/', views.profile, name='profile'),
    path('organizations/', views.organization_list, name='organization_list'),
    path('organizations/create/', views.create_organization, name='create_organization'),
    path('organizations/<int:org_id>/', views.organization_detail, name='organization_detail'),
    path('organizations/<int:org_id>/add-member/', views.add_org_member, name='add_org_member'),
    path('organizations/<int:org_id>/create-team/', views.create_team, name='create_team'),

    path('repositories/', views.repository_list, name='repository_list'),
    path('repositories/create/', views.create_repository, name='create_repository'),
    path('repositories/<str:repository_name>/', views.repository_detail, name='repository_detail'),
    path('repositories/<str:repository_name>/toggle_favorite/', views.toggle_favorite, name='toggle_favorite'),
    path('repositories/<str:repository_name>/logs/', views.view_logs, name='view_logs'),

    # File management
    path('repositories/<str:repository_name>/upload/', views.upload_file, name='upload_file'),
    path('repositories/<str:repository_name>/edit/<path:file_path>/', views.edit_and_save_file, name='edit_and_save_file'),

    # Branch management
    path('repositories/<str:repository_name>/create-branch/', views.create_branch, name='create_branch'),
    path('repositories/<str:repository_name>/merge/', views.merge_branch, name='merge_branch'),  # ✅ **New route for merging branches**

    # Tab views
    path('repositories/<str:repository_name>/pull-requests/', views.pull_request_list, name='pull_request_list'),
    path('repositories/<str:repository_name>/issues/', views.repository_issues, name='repository_issues'),
    path('repositories/<str:repository_name>/settings/', views.repository_settings, name='repository_settings'),
    path('repositories/<str:repository_name>/ci/', views.repository_rocket_ci, name='repository_rocket_ci'),

    # Pull request management
    path('repositories/<str:repository_name>/pull-request/create/', views.create_pull_request, name='create_pull_request'),
    path('pull-requests/<int:pull_request_id>/', views.pull_request_detail, name='pull_request_detail'),
    path('pull-requests/<int:pull_request_id>/merge/', views.merge_pull_request, name='merge_pull_request'),
    path('pull-requests/<int:pull_request_id>/close/', views.close_pull_request, name='close_pull_request'),

    # Git-specific URLs
    re_path(r'^repos/(?P<repo_name>[\w\-\.]+)/info/refs$', GitService.as_view(), name='git_info_refs'),
    re_path(r'^repos/(?P<repo_name>[\w\-\.]+)/(?P<path>git-upload-pack)$', GitService.as_view(), name='git_upload_pack'),
    re_path(r'^repos/(?P<repo_name>[\w\-\.]+)/(?P<path>git-receive-pack)$', GitService.as_view(), name='git_receive_pack'),
    re_path(r'^repos/(?P<repo_name>[\w\-\.]+)/(?P<path>.+)$', GitService.as_view(), name='git_static_files'),
]
