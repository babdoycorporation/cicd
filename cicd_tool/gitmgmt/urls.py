from django.contrib.auth import views as auth_views
from django.urls import path, re_path
from django.shortcuts import redirect

from . import views
from .views import GitService
from pipeline import views as pipeline_views

urlpatterns = [
    # ── Auth ─────────────────────────────────────────────────────────────────
    path('', auth_views.LoginView.as_view(template_name='gitmgmt/login.html'), name='login'),
    path('login/', auth_views.LoginView.as_view(template_name='gitmgmt/login.html'), name='login_alias'),
    path('logout/', views.user_logout, name='logout'),
    path('accounts/logout/', views.user_logout, name='accounts_logout'),
    path('auth/logout/', views.user_logout, name='auth_logout'),
    path('ci/logout/', views.user_logout, name='ci_logout_alias'),
    path('dashboard/', lambda r: redirect('dashboard'), name='dashboard_alias'),
    path('notifications/preferences/', pipeline_views.notification_preferences, name='notification_preferences_alias'),
    path('auth/keycloak/login/', pipeline_views.keycloak_login, name='keycloak_login_alias'),
    path('auth/keycloak/callback/', pipeline_views.keycloak_callback, name='keycloak_callback_alias'),
    path('signup/', views.signup, name='signup'),
    path('profile/', views.profile, name='profile'),
    path('users/<str:username>/', views.user_profile_view, name='user_profile'),

    # ── Search ────────────────────────────────────────────────────────────────
    path('search/', views.global_search, name='global_search'),
    path('api/search/', views.global_search_api, name='global_search_api'),

    # ── Notifications ────────────────────────────────────────────────────────
    path('notifications/', views.notification_list, name='notification_list'),
    path('notifications/<int:notification_id>/read/', views.mark_notification_read, name='mark_notification_read'),
    path('notifications/count/', views.notification_count, name='notification_count'),

    # ── Activity ──────────────────────────────────────────────────────────────
    path('activity/', views.activity_feed, name='activity_feed'),

    # ── Organisations ─────────────────────────────────────────────────────────
    path('organizations/', views.organization_list, name='organization_list'),
    path('organizations/create/', views.create_organization, name='create_organization'),
    path('organizations/<str:org_name>/', views.organization_detail, name='organization_detail'),
    path('organizations/<str:org_name>/add-member/', views.add_org_member, name='add_org_member'),
    path('organizations/<str:org_name>/create-team/', views.create_team, name='create_team'),
    path('organizations/<str:org_name>/settings/', views.organization_settings, name='organization_settings'),

    # ── Repositories ──────────────────────────────────────────────────────────
    path('repositories/', views.repository_list, name='repository_list'),
    path('repositories/create/', views.create_repository, name='create_repository'),
    path('repositories/<str:repository_name>/', views.repository_detail, name='repository_detail'),
    path('repositories/<str:repository_name>/toggle-favorite/', views.toggle_favorite, name='toggle_favorite'),
    path('repositories/<str:repository_name>/toggle-watch/', views.toggle_watch, name='toggle_watch'),
    path('repositories/<str:repository_name>/fork/', views.fork_repository, name='fork_repository'),
    path('repositories/<str:repository_name>/activity/', views.repository_activity, name='repository_activity'),

    # File / commit operations
    path('repositories/<str:repository_name>/logs/', views.view_logs, name='view_logs'),
    path('repositories/<str:repository_name>/upload/', views.upload_file, name='upload_file'),
    path('repositories/<str:repository_name>/edit/<path:file_path>/', views.edit_and_save_file, name='edit_and_save_file'),

    # Branch operations
    path('repositories/<str:repository_name>/create-branch/', views.create_branch, name='create_branch'),
    path('repositories/<str:repository_name>/delete-branch/', views.delete_branch, name='delete_branch'),
    path('repositories/<str:repository_name>/merge/', views.merge_branch, name='merge_branch'),
    path('repositories/<str:repository_name>/branches/<path:branch_name>/protection/', views.branch_protection, name='branch_protection'),
    path('repositories/<str:repository_name>/compare/', views.compare_branches, name='compare_branches'),

    # Access Requests (Ownership & Permission Control)
    path('repositories/<str:repository_name>/request-access/', views.request_repo_access, name='request_repo_access'),
    path('repositories/<str:repository_name>/access-requests/', views.repository_access_requests, name='repository_access_requests'),
    path('repositories/<str:repository_name>/access-requests/<int:request_id>/<str:action>/', views.review_access_request, name='review_access_request'),

    # Settings / collaborators / delete
    path('repositories/<str:repository_name>/settings/', views.repository_settings, name='repository_settings'),
    path('repositories/<str:repository_name>/delete/', views.delete_repository, name='delete_repository'),
    path('repositories/<str:repository_name>/settings/collaborators/add/', views.add_collaborator, name='add_collaborator'),
    path('repositories/<str:repository_name>/settings/collaborators/<int:user_id>/remove/', views.remove_collaborator, name='remove_collaborator'),

    # ── Pull Requests ─────────────────────────────────────────────────────────
    path('repositories/<str:repository_name>/pull-requests/', views.pull_request_list, name='pull_request_list'),
    path('repositories/<str:repository_name>/pull-requests/create/', views.create_pull_request, name='create_pull_request'),
    path('pull-requests/<int:pull_request_id>/', views.pull_request_detail, name='pull_request_detail'),
    path('pull-requests/<int:pull_request_id>/merge/', views.merge_pull_request, name='merge_pull_request'),
    path('pull-requests/<int:pull_request_id>/close/', views.close_pull_request, name='close_pull_request'),
    path('pull-requests/<int:pull_request_id>/reopen/', views.reopen_pull_request, name='reopen_pull_request'),
    path('pull-requests/<int:pull_request_id>/inline-comment/', views.add_inline_comment, name='add_inline_comment'),

    # ── Issues ────────────────────────────────────────────────────────────────
    path('repositories/<str:repository_name>/issues/', views.repository_issues, name='repository_issues'),
    path('repositories/<str:repository_name>/issues/new/', views.create_issue, name='create_issue'),
    path('repositories/<str:repository_name>/issues/<int:issue_number>/', views.issue_detail, name='issue_detail'),
    path('repositories/<str:repository_name>/issues/<int:issue_number>/edit/', views.edit_issue, name='edit_issue'),

    # ── Labels ────────────────────────────────────────────────────────────────
    path('repositories/<str:repository_name>/labels/', views.label_list, name='label_list'),
    path('repositories/<str:repository_name>/labels/new/', views.label_create, name='label_create'),
    path('repositories/<str:repository_name>/labels/<int:label_id>/edit/', views.label_edit, name='label_edit'),
    path('repositories/<str:repository_name>/labels/<int:label_id>/delete/', views.label_delete, name='label_delete'),

    # ── Milestones ────────────────────────────────────────────────────────────
    path('repositories/<str:repository_name>/milestones/', views.milestone_list, name='milestone_list'),
    path('repositories/<str:repository_name>/milestones/new/', views.milestone_create, name='milestone_create'),
    path('repositories/<str:repository_name>/milestones/<int:milestone_id>/', views.milestone_detail, name='milestone_detail'),
    path('repositories/<str:repository_name>/milestones/<int:milestone_id>/close/', views.milestone_close, name='milestone_close'),

    # ── Releases ──────────────────────────────────────────────────────────────
    path('repositories/<str:repository_name>/releases/', views.release_list, name='release_list'),
    path('repositories/<str:repository_name>/releases/new/', views.create_release, name='create_release'),
    path('repositories/<str:repository_name>/releases/<str:tag_name>/', views.release_detail, name='release_detail'),

    # ── Actions & macOS .IPA Builder (GitHub Actions Suite) ───────────────────
    path('repositories/<str:repository_name>/actions/', views.repository_actions, name='repository_actions'),
    path('repositories/<str:repository_name>/actions/run/', views.run_macos_action, name='run_macos_action'),
    path('repositories/<str:repository_name>/actions/runs/<uuid:run_id>/', views.repository_action_run_detail, name='repository_action_run_detail'),
    path('repositories/<str:repository_name>/actions/runs/<uuid:run_id>/download-ipa/', views.download_action_ipa, name='download_action_ipa'),
    path('repositories/<str:repository_name>/actions/create-workflow-file/', views.create_workflow_file, name='create_workflow_file'),

    # ── CI tab (Legacy Alias) ─────────────────────────────────────────────────
    path('repositories/<str:repository_name>/ci/', views.repository_actions, name='repository_rocket_ci'),
    path('repositories/<str:repository_name>/ci/initialize/', views.initialize_rocket_ci, name='initialize_rocket_ci'),

    # ── Reactions ─────────────────────────────────────────────────────────────
    path('reactions/<str:target_type>/<int:target_id>/<str:emoji>/', views.toggle_reaction, name='toggle_reaction'),

    # ── Git Smart HTTP Protocol (supports /git/<owner>/<repo>.git, /git/<repo>.git, /repos/<repo>.git) ────
    re_path(r'^(?:git/(?:[\w\-\.]+/)?|repos/)(?P<repo_name>[\w\-\.]+)/info/refs$', GitService.as_view(), name='git_info_refs'),
    re_path(r'^(?:git/(?:[\w\-\.]+/)?|repos/)(?P<repo_name>[\w\-\.]+)/(?P<path>git-upload-pack)$', GitService.as_view(), name='git_upload_pack'),
    re_path(r'^(?:git/(?:[\w\-\.]+/)?|repos/)(?P<repo_name>[\w\-\.]+)/(?P<path>git-receive-pack)$', GitService.as_view(), name='git_receive_pack'),
    re_path(r'^(?:git/(?:[\w\-\.]+/)?|repos/)(?P<repo_name>[\w\-\.]+)/(?P<path>.+)$', GitService.as_view(), name='git_static_files'),
]
