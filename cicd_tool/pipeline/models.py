from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=100)
    repository_url = models.URLField()
    environment_variables = models.JSONField(default=dict, blank=True)
    build_triggers = models.JSONField(default=dict, blank=True)
    notifications_enabled = models.BooleanField(default=False)
    notification_emails = models.CharField(max_length=500, blank=True)
    slack_webhook_url = models.URLField(blank=True)
    build_scripts = models.TextField(blank=True)
    test_scripts = models.TextField(blank=True)
    deployment_scripts = models.TextField(blank=True)
    # Add other fields as needed

    # Add other fields as needed

    def __str__(self):
        return self.name
 # Add default branch field

class Tag(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class Build(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=[('pending', 'Pending'), ('running', 'Running'), ('success', 'Success'), ('failed', 'Failed')])
    log = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

from django.db import models
from django.utils.translation import gettext_lazy as _


class Pipeline(models.Model):
    tags = models.ManyToManyField(Tag, blank=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


# models.py

class PipelineStep(models.Model):
    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    command = models.TextField()
    condition = models.TextField(blank=True)  # Define condition for step execution

    def __str__(self):
        return f"{self.name} - {self.pipeline.name}"
from django.db import models

from django.core.validators import validate_ipv4_address

# models.py

from django.db import models
from django.core.validators import validate_ipv4_address
from django.utils import timezone
import requests

class Agent(models.Model):
    hostname = models.CharField(max_length=255, unique=True)
    ip_address = models.CharField(max_length=255, validators=[validate_ipv4_address], unique=True)
    hash_key = models.CharField(max_length=255, unique=True, default='')
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    operating_system = models.CharField(max_length=100, null=True, blank=True)
    live = models.BooleanField(default=False)

    def __str__(self):
        return self.hostname

    def get_command_url(self):
        """
        Get the URL for sending commands to the agent.
        """
        return f"http://{self.ip_address}:9000/pipeline/agents/receive-command/"

    def send_command(self, command_data):
        """
        Send command to the agent and return the response.
        """
        try:
            endpoint = self.get_command_url()
            response = requests.post(endpoint, json=command_data)
            response.raise_for_status()  # Raise an exception for HTTP errors
            return response.json()
        except requests.RequestException as e:
            # Handle communication errors
            raise RuntimeError(f"Error sending command to agent: {e}")

    def update_heartbeat(self):
        """
        Update the last heartbeat timestamp for the agent.
        """
        self.last_heartbeat = timezone.now()
        self.save()

        return self.hostname




from django.db import models
from django.utils import timezone
import uuid

from django.db import models
from django.utils import timezone
import uuid

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

# models.py



from django.utils import timezone

class Command(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE)
    command = models.TextField()
    timestamp = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Command for {self.agent.hostname}: {self.command}"



class Heartbeat(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Heartbeat from {self.agent.hostname} at {self.timestamp}"


from django.db import models

class GlobalCredential(models.Model):
    service_name = models.CharField(max_length=100)
    username = models.CharField(max_length=100)
    password = models.CharField(max_length=100)  # Encrypted or hashed
    token = models.CharField(max_length=100)     # Encrypted or hashed
    # Add other fields as needed

    def __str__(self):
        return self.service_name



class LocalCredential(models.Model):
    project = models.ForeignKey('Project', on_delete=models.CASCADE)
    service_name = models.CharField(max_length=100)
    username = models.CharField(max_length=100)
    password = models.CharField(max_length=100)  # Encrypted or hashed
    token = models.CharField(max_length=100)     # Encrypted or hashed
    # Add other fields as needed
    def __str__(self):
        return self.service_name



class Application(models.Model):
    name = models.CharField(max_length=100)
    project = models.ForeignKey('Project', on_delete=models.CASCADE, related_name='applications')
    pipelines = models.ManyToManyField('Pipeline', related_name='applications')
    global_credentials = models.ManyToManyField('GlobalCredential', related_name='applications')
    local_credentials = models.ManyToManyField('LocalCredential', related_name='applications')
    agents = models.ManyToManyField('Agent', related_name='applications')

    def __str__(self):
        return self.name



from django.db import models
from django.utils import timezone

class YamlFileVersion(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE)
    version_number = models.IntegerField()
    yaml_content = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Version {self.version_number} for {self.pipeline.name}"


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

