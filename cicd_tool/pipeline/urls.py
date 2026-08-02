from django.contrib.auth.decorators import login_required
from django.urls import path

from . import views

urlpatterns = [
    # ── Dashboard ─────────────────────────────────────────────────────────────
    path('', login_required(views.DashboardView.as_view()), name='dashboard'),
    path('settings/', login_required(views.global_settings), name='global_settings'),
    path('documentation/', login_required(views.documentation), name='documentation'),
    path('metrics/', login_required(views.pipeline_metrics_api), name='pipeline_metrics_api'),

    # ── Projects ──────────────────────────────────────────────────────────────
    path('projectslist/', login_required(views.project_list), name='project_list'),
    path('projects/new/', login_required(views.project_create), name='project_create'),
    path('projects/<str:project_name>/', login_required(views.project_detail), name='project_detail'),
    path('projects/<str:project_name>/edit/', login_required(views.project_edit), name='project_edit'),
    path('projects/<str:project_name>/delete/', login_required(views.project_delete), name='project_delete'),
    path('projects/<str:project_name>/configure/', login_required(views.configure_project), name='configure_project'),
    path('projects/<str:project_name>/settings/', login_required(views.project_settings), name='project_settings'),
    path('projects/<str:project_name>/orchestrate/', login_required(views.trigger_project_pipeline), name='trigger_project_pipeline'),
    path('projects/<str:project_name>/orchestrator-history/', login_required(views.project_pipeline_history), name='project_pipeline_history'),
    path('projects/<str:project_name>/files/<path:path>/', login_required(views.project_file_download), name='project_file_download'),
    # ── Pipelines ─────────────────────────────────────────────────────────────
    path('projects/<str:project_name>/pipelines/', login_required(views.pipeline_list), name='pipeline_list'),
    path('projects/<str:project_name>/pipelines/create/', login_required(views.pipeline_create), name='pipeline_create'),
    path('projects/<str:project_name>/pipelines/<str:pipeline_name>/update/', login_required(views.pipeline_update), name='pipeline_update'),
    path('projects/<str:project_name>/pipelines/<str:pipeline_name>/delete/', login_required(views.pipeline_delete), name='pipeline_delete'),

    path('pipeline/<str:pipeline_name>/', login_required(views.pipeline_detail), name='pipeline_detail'),
    path('pipeline/<str:pipeline_name>/run/', login_required(views.run_pipeline), name='run_pipeline'),
    path('pipeline/<str:pipeline_name>/runs/', login_required(views.pipeline_run_list), name='pipeline_run_list'),
    path('pipeline/run/<uuid:run_id>/', login_required(views.pipeline_run_detail), name='pipeline_run_detail'),
    path('pipeline/run/<uuid:run_id>/api/', login_required(views.pipeline_run_api), name='pipeline_run_api'),
    path('pipeline/run/<uuid:run_id>/cancel/', login_required(views.cancel_pipeline_run), name='cancel_pipeline_run'),

    # ── Pipeline Steps ────────────────────────────────────────────────────────
    path('pipelines/<str:pipeline_name>/steps/', login_required(views.pipeline_step_list), name='pipeline_step_list'),
    path('pipelines/<str:pipeline_name>/steps/create/', login_required(views.pipeline_step_create), name='pipeline_step_create'),
    path('pipelines/<str:pipeline_name>/steps/<int:step_id>/update/', login_required(views.pipeline_step_update), name='pipeline_step_update'),
    path('pipelines/<str:pipeline_name>/steps/<int:step_id>/delete/', login_required(views.pipeline_step_delete), name='pipeline_step_delete'),

    # ── YAML pipeline creator ─────────────────────────────────────────────────
    path('yaml-pipeline/', login_required(views.create_yaml_pipeline), name='create_yaml_pipeline'),
    path('pipelines/', login_required(views.global_pipeline_list), name='global_pipeline_list'),

    # ── Orchestrator (new) ───────────────────────────────────────────────────
    path('projects/<str:project_name>/orchestrator/create/', login_required(views.project_pipeline_create), name='project_pipeline_create'),
    path('projects/<str:project_name>/orchestrator/<int:pipeline_id>/delete/', login_required(views.project_pipeline_delete), name='project_pipeline_delete'),
    path('orchestrator/run/<uuid:run_id>/', login_required(views.project_pipeline_run_detail), name='project_pipeline_run_detail'),
    path('orchestrator/run/api/<uuid:run_id>/', login_required(views.project_pipeline_run_api), name='project_pipeline_run_api'),
    # ── Agents ────────────────────────────────────────────────────────────────
    path('agents/', login_required(views.agent_list), name='agent_list'),
    path('agents/add/', login_required(views.add_agent), name='add_agent'),
    path('agents/send-command/', login_required(views.send_command), name='send_command'),
    path('agents/instructions/', login_required(views.agent_instructions), name='agent_instructions'),

    # Agent API endpoints — MUST be before <str:agent_hostname>/ to avoid wildcard capture
    path('agents/download/<str:filename>', views.download_agent_script, name='download_agent_script'),
    path('static/agents/<str:filename>', views.download_agent_script, name='download_agent_script_static'),
    path('agents/register/', views.register_agent, name='register_agent'),
    path('agents/receive-heartbeat/', views.receive_heartbeat, name='receive_heartbeat'),
    path('agents/receive-command/', views.receive_command, name='receive_command'),
    path('agents/poll/', views.poll_agent_task, name='poll_agent_task'),
    path('agents/report-task/', views.report_agent_task, name='report_agent_task'),
    path('agents/stream/', views.agent_stream, name='agent_stream'),
    path('agents/report-stream-result/', views.report_stream_result, name='report_stream_result'),

    # Wildcard — must come LAST in agent group
    path('agents/<str:agent_hostname>/', login_required(views.agent_detail), name='agent_detail'),

    # ── Credentials ───────────────────────────────────────────────────────────
    path('global-credentials/', login_required(views.global_credential_list), name='global_credential_list'),   # ← FIXED (no trailing space)
    path('global-credentials/create/', login_required(views.global_credential_create), name='global_credential_create'),
    path('global-credentials/<int:pk>/', login_required(views.global_credential_detail), name='global_credential_detail'),
    path('global-credentials/<int:pk>/update/', login_required(views.global_credential_update), name='global_credential_update'),
    path('global-credentials/<int:pk>/delete/', login_required(views.global_credential_delete), name='global_credential_delete'),

    path('projects/<str:project_name>/credentials/', login_required(views.local_credential_list), name='local_credential_list'),
    path('projects/<str:project_name>/credentials/create/', login_required(views.local_credential_create), name='local_credential_create'),
    path('credentials/<int:pk>/', login_required(views.local_credential_detail), name='local_credential_detail'),
    path('credentials/<int:pk>/update/', login_required(views.local_credential_update), name='local_credential_update'),
    path('credentials/<int:pk>/delete/', login_required(views.local_credential_delete), name='local_credential_delete'),

    # ── Applications ──────────────────────────────────────────────────────────
    path('applications/', login_required(views.application_list), name='application_list'),
    path('applications/create/', login_required(views.create_application), name='create_application'),
    path('applications/create/<str:project_name>/', login_required(views.create_application), name='create_application'),
    path('applications/<str:application_name>/settings/', login_required(views.application_settings), name='application_settings'),
    path('applications/<str:application_name>/', login_required(views.application_detail), name='application_detail'),
    path('projects/<str:project_name>/applications/create/', login_required(views.create_application), name='create_application_project'),

    # ── Webhooks (no auth) ────────────────────────────────────────────────────
    path('webhook/github/', views.github_webhook, name='github_webhook'),

    # ── Notification integrations & preferences ───────────────────────────────
    path('settings/integrations/email/save/', login_required(views.save_email_integration), name='save_email_integration'),
    path('settings/integrations/email/test/', login_required(views.test_email_integration), name='test_email_integration'),
    path('notifications/preferences/', login_required(views.notification_preferences), name='notification_preferences'),

    # ── Infrastructure & Security Settings ────────────────────────────────────
    path('settings/scaling/save/', login_required(views.save_task_scaling_settings), name='save_task_scaling_settings'),
    path('settings/redis/test/', login_required(views.test_redis_connection_api), name='test_redis_connection_api'),
    path('settings/secrets/save/', login_required(views.save_secret_storage_settings), name='save_secret_storage_settings'),
    path('settings/storage/save/', login_required(views.save_repo_storage_settings), name='save_repo_storage_settings'),

    # ── Keycloak Enterprise SSO (Workloop Pattern) ────────────────────────────
    path('settings/keycloak/save/', login_required(views.save_keycloak_settings), name='save_keycloak_settings'),
    path('settings/keycloak/test/', login_required(views.test_keycloak_connection_api), name='test_keycloak_connection_api'),
    path('auth/keycloak/login/', views.keycloak_login, name='keycloak_login'),
    path('auth/keycloak/callback/', views.keycloak_callback, name='keycloak_callback'),

    # ── Build Artifacts ───────────────────────────────────────────────────────
    path('pipeline/run/<uuid:run_id>/artifacts/<int:artifact_id>/download/', login_required(views.artifact_download), name='artifact_download'),

    # ── Deployment Targets ────────────────────────────────────────────────────
    path('deployment-targets/', login_required(views.deployment_target_list), name='deployment_target_list'),
    path('deployment-targets/create/', login_required(views.deployment_target_create), name='deployment_target_create'),
    path('deployment-targets/<int:pk>/', login_required(views.deployment_target_detail), name='deployment_target_detail'),
    path('deployment-targets/<int:pk>/edit/', login_required(views.deployment_target_update), name='deployment_target_update'),
    path('deployment-targets/<int:pk>/delete/', login_required(views.deployment_target_delete), name='deployment_target_delete'),
]
