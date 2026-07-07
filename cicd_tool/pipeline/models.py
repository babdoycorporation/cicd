from django.db import models
from django.core.validators import validate_ipv4_address
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
import requests
import uuid

# SCOPE CHOICES
SCOPE_CHOICES = (
    ('global', 'Global'),
    ('project', 'Project Level'),
    ('application', 'Application Level'),
)

class Environment(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

class GlobalSettings(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()

    def __str__(self):
        return self.key

class Project(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    # Link to gitmgmt.Organization
    organization = models.ForeignKey('gitmgmt.Organization', on_delete=models.CASCADE, related_name='projects', null=True, blank=True)

    repository_url = models.URLField(blank=True, null=True)
    environment_variables = models.JSONField(default=dict, blank=True)
    build_triggers = models.JSONField(default=dict, blank=True)
    notifications_enabled = models.BooleanField(default=False)
    notification_emails = models.CharField(max_length=500, blank=True)
    slack_webhook_url = models.URLField(blank=True)
    build_scripts = models.TextField(blank=True)
    test_scripts = models.TextField(blank=True)
    deployment_scripts = models.TextField(blank=True)

    def __str__(self):
        return self.name

    def get_member_role(self, user):
        """Project role, falling back to org role for org admins/owners."""
        m = self.members.filter(user=user).first()
        if m:
            return m.role
        if self.organization:
            org_role = self.organization.get_member_role(user)
            if org_role in ('owner', 'admin'):
                return 'maintainer'
        return None


class ProjectMember(models.Model):
    """Role-based membership of a user in a project.

    Maintainer — manage settings, members, pipelines, trigger builds
    Developer  — trigger builds, manage pipelines
    Viewer     — read-only access to builds and logs
    """
    ROLE_CHOICES = (
        ('maintainer', 'Maintainer'),
        ('developer', 'Developer'),
        ('viewer', 'Viewer'),
    )
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='project_memberships')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='developer')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('project', 'user')

    def __str__(self):
        return f"{self.user.username} @ {self.project.name} ({self.role})"


class Application(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='applications')
    default_branch = models.CharField(max_length=100, default='main')

    # NOTE: the backing Git repository is linked from the other side —
    # gitmgmt.Repository.application (OneToOne, related_name='repository').
    # Access it via `app.linked_repository` (safe) or `app.repository` (may raise).

    def __str__(self):
        return f"{self.project.name} / {self.name}"

    @property
    def linked_repository(self):
        """The backing Repository, or None. Safe accessor for the reverse OneToOne."""
        from gitmgmt.models import Repository
        return Repository.objects.filter(application=self).first()

CREDENTIAL_TYPE_CHOICES = (
    ('generic',         'Generic / Other'),
    ('aws',             'AWS (Access Key)'),
    ('azure',           'Azure (Service Principal)'),
    ('gcp',             'GCP (Service Account)'),
    ('kubernetes',      'Kubernetes (Kubeconfig / Token)'),
    ('docker_registry', 'Docker Registry'),
    ('ssh',             'SSH Key / Password'),
    ('git',             'Git (Username + Token)'),
)

class Credential(models.Model):
    service_name = models.CharField(max_length=100)
    credential_type = models.CharField(max_length=30, choices=CREDENTIAL_TYPE_CHOICES, default='generic')
    username = models.CharField(max_length=100, blank=True)
    password = models.CharField(max_length=500, blank=True)
    token = models.CharField(max_length=500, blank=True)
    extra = models.JSONField(default=dict, blank=True)

    scope_level = models.CharField(max_length=20, choices=SCOPE_CHOICES, default='global')
    project = models.ForeignKey(Project, on_delete=models.CASCADE, null=True, blank=True, related_name='credentials')
    application = models.ForeignKey(Application, on_delete=models.CASCADE, null=True, blank=True, related_name='credentials')

    def __str__(self):
        return f"{self.service_name} [{self.credential_type}] ({self.scope_level})"

class Tag(models.Model):
    name = models.CharField(max_length=100)
    def __str__(self):
        return self.name

class Pipeline(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='pipelines', null=True, blank=True)
    tags = models.ManyToManyField(Tag, blank=True)
    environments = models.ManyToManyField(Environment, blank=True, related_name='pipelines')
    
    # For YAML support
    yaml_path = models.CharField(max_length=255, default='rockerci.yaml')
    monitored_branch = models.CharField(max_length=100, default='main')

    def __str__(self):
        return self.name

class Stage(models.Model):
    name = models.CharField(max_length=100)
    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE, related_name='stages')
    def __str__(self):
        return self.name

class Step(models.Model):
    name = models.CharField(max_length=100)
    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name='steps')
    command = models.TextField()
    condition = models.CharField(max_length=100, choices=[('always', _('Always')), ('on_success', _('On Success')), ('on_failure', _('On Failure'))])
    def __str__(self):
        return self.name

class PipelineStep(models.Model):
    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    command = models.TextField()
    condition = models.TextField(blank=True)
    def __str__(self):
        return f"{self.name} - {self.pipeline.name}"

class Agent(models.Model):
    hostname = models.CharField(max_length=255, unique=True)
    ip_address = models.CharField(max_length=255, validators=[validate_ipv4_address], unique=True)
    hash_key = models.CharField(max_length=255, unique=True, default='')
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    operating_system = models.CharField(max_length=100, null=True, blank=True)
    live = models.BooleanField(default=False)
    
    scope_level = models.CharField(max_length=20, choices=SCOPE_CHOICES, default='global')
    project = models.ForeignKey(Project, on_delete=models.CASCADE, null=True, blank=True, related_name='agents')
    application = models.ForeignKey(Application, on_delete=models.CASCADE, null=True, blank=True, related_name='agents')
    environments = models.ManyToManyField(Environment, blank=True, related_name='agents')

    def __str__(self):
        return self.hostname

    def get_command_url(self):
        return f"http://{self.ip_address}:9000/pipeline/agents/receive-command/"

    def send_command(self, command_data):
        try:
            endpoint = self.get_command_url()
            response = requests.post(endpoint, json=command_data)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise RuntimeError(f"Error sending command to agent: {e}")

    def update_heartbeat(self):
        self.last_heartbeat = timezone.now()
        self.save()
        return self.hostname

class PipelineRun(models.Model):
    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE, related_name='runs')
    status = models.CharField(max_length=20, choices=[('pending', 'Pending'), ('running', 'Running'), ('success', 'Success'), ('failed', 'Failed')])
    log = models.TextField()
    agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    run_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    def __str__(self):
        return f"Run of {self.pipeline.name} at {self.started_at}"
    
    def save(self, *args, **kwargs):
        if not self.pk:
            while PipelineRun.objects.filter(run_id=self.run_id).exists():
                self.run_id = uuid.uuid4()
        super().save(*args, **kwargs)

import uuid

class ProjectPipeline(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='project_pipelines')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    yaml_path = models.CharField(max_length=255, blank=True, help_text="Path to orchestration YAML if repository-driven")
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.project.name} / {self.name}"

class ProjectOrchestrationStep(models.Model):
    project_pipeline = models.ForeignKey(ProjectPipeline, on_delete=models.CASCADE, related_name='steps')
    order = models.IntegerField(default=0)
    target_pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE)
    parallel = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['order', 'id']
        
    def __str__(self):
        return f"Step {self.order} -> {self.target_pipeline.name}"

class ProjectPipelineRun(models.Model):
    run_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    project_pipeline = models.ForeignKey(ProjectPipeline, on_delete=models.CASCADE, related_name='runs')
    status = models.CharField(max_length=20, choices=[('pending', 'Pending'), ('running', 'Running'), ('success', 'Success'), ('failed', 'Failed')], default='pending')
    log = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.project_pipeline.name} #{self.run_id}"

class Command(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE)
    command = models.TextField()
    timestamp = models.DateTimeField(default=timezone.now)

class Heartbeat(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)

class YamlFileVersion(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, null=True, blank=True)
    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE)
    version_number = models.IntegerField()
    yaml_content = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)


# ─────────────────────────────────────────────────────────────────────────────
#  Build Artifacts
# ─────────────────────────────────────────────────────────────────────────────

class BuildArtifact(models.Model):
    pipeline_run  = models.ForeignKey(PipelineRun, on_delete=models.CASCADE, related_name='artifacts')
    name          = models.CharField(max_length=255)
    file_path     = models.CharField(max_length=500)   # relative path under ARTIFACTS_DIR
    file_size     = models.BigIntegerField(default=0)  # bytes
    content_type  = models.CharField(max_length=100, default='application/octet-stream')
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} (run {self.pipeline_run.run_id})"

    @property
    def size_display(self):
        b = self.file_size
        for unit in ('B', 'KB', 'MB', 'GB'):
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} TB"


# ─────────────────────────────────────────────────────────────────────────────
#  Notification Integrations
# ─────────────────────────────────────────────────────────────────────────────

NOTIFICATION_INTEGRATION_TYPES = (
    ('email', 'Email (SMTP)'),
    ('slack', 'Slack'),
    ('teams', 'Microsoft Teams'),
)

class NotificationIntegration(models.Model):
    integration_type = models.CharField(max_length=20, choices=NOTIFICATION_INTEGRATION_TYPES, unique=True)
    name             = models.CharField(max_length=100)
    config           = models.JSONField(default=dict, blank=True)
    # config keys for email: smtp_host, smtp_port, smtp_user, smtp_password, smtp_from, use_tls
    # config keys for slack: webhook_url, channel
    # config keys for teams: webhook_url
    is_active        = models.BooleanField(default=False)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_integration_type_display()} ({'active' if self.is_active else 'inactive'})"


# ─────────────────────────────────────────────────────────────────────────────
#  User Notification Preferences
# ─────────────────────────────────────────────────────────────────────────────

class UserNotificationPreference(models.Model):
    user             = models.OneToOneField('auth.User', on_delete=models.CASCADE, related_name='notification_prefs')
    # Pipeline events
    pipeline_success = models.BooleanField(default=True)
    pipeline_failure = models.BooleanField(default=True)
    # Pull request events
    pr_assigned      = models.BooleanField(default=True)
    pr_merged        = models.BooleanField(default=False)
    # Issue events
    issue_assigned   = models.BooleanField(default=True)
    issue_commented  = models.BooleanField(default=False)

    def __str__(self):
        return f"Notification prefs for {self.user.username}"

    @classmethod
    def for_user(cls, user):
        obj, _ = cls.objects.get_or_create(user=user)
        return obj


DEPLOYMENT_TARGET_TYPE_CHOICES = (
    ('kubernetes',      'Kubernetes (kubectl / Helm)'),
    ('aws_ecs',         'AWS ECS'),
    ('aws_eks',         'AWS EKS'),
    ('aws_lambda',      'AWS Lambda'),
    ('azure_aks',       'Azure AKS'),
    ('azure_appservice','Azure App Service'),
    ('gcp_gke',         'GCP GKE'),
    ('gcp_cloudrun',    'GCP Cloud Run'),
    ('docker_registry', 'Docker Registry (push image)'),
    ('ssh',             'SSH / Server (shell over SSH)'),
)

class DeploymentTarget(models.Model):
    name        = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    target_type = models.CharField(max_length=30, choices=DEPLOYMENT_TARGET_TYPE_CHOICES)

    # Where to deploy
    endpoint    = models.CharField(max_length=500, blank=True, help_text="Cluster URL, registry host, SSH host, etc.")
    region      = models.CharField(max_length=100, blank=True, help_text="AWS/Azure/GCP region")
    namespace   = models.CharField(max_length=100, blank=True, help_text="K8s namespace / ECS cluster / resource group")

    # Scope
    environment  = models.ForeignKey(Environment,  on_delete=models.SET_NULL, null=True, blank=True, related_name='deployment_targets')
    project      = models.ForeignKey(Project,      on_delete=models.CASCADE,  null=True, blank=True, related_name='deployment_targets')
    credential   = models.ForeignKey(Credential,   on_delete=models.SET_NULL, null=True, blank=True, related_name='deployment_targets')

    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_target_type_display()})"

