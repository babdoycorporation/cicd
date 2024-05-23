from django import forms
from .models import Project

class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name', 'repository_url']

# forms.py
from django import forms
from .models import Project
import json

class ProjectConfigurationForm(forms.ModelForm):
    build_triggers = forms.CharField(widget=forms.Textarea(attrs={'rows': 5}), required=False)
    environment_variables = forms.CharField(widget=forms.Textarea(attrs={'rows': 5}), required=False)

    class Meta:
        model = Project
        fields = [
            'environment_variables', 'build_triggers', 'notifications_enabled',
            'notification_emails', 'slack_webhook_url', 'build_scripts', 'test_scripts',
            'deployment_scripts'
        ]
    
    def clean_build_triggers(self):
        data = self.cleaned_data['build_triggers']
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            raise forms.ValidationError("Invalid JSON format for build triggers")

    def clean_environment_variables(self):
        data = self.cleaned_data['environment_variables']
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            raise forms.ValidationError("Invalid JSON format for environment variables")

from django import forms
from .models import Pipeline, Stage, Step, Agent


class PipelineForm(forms.ModelForm):
    class Meta:
        model = Pipeline
        fields = ['name', 'description']


class StageForm(forms.ModelForm):
    class Meta:
        model = Stage
        fields = ['name', 'pipeline']


class StepForm(forms.ModelForm):
    class Meta:
        model = Step
        fields = ['name', 'stage', 'command', 'condition']

class AgentForm(forms.ModelForm):
    class Meta:
        model = Agent
        fields = ['hostname', 'ip_address', 'hash_key', 'last_heartbeat', 'operating_system', 'live']

from django import forms
from .models import GlobalCredential

class GlobalCredentialForm(forms.ModelForm):
    class Meta:
        model = GlobalCredential
        fields = ['service_name', 'username', 'password', 'token']

from django import forms
from .models import LocalCredential

class LocalCredentialForm(forms.ModelForm):
    class Meta:
        model = LocalCredential
        fields = ['service_name', 'username', 'password', 'token']

from django import forms
from .models import Application

class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = ['name', 'global_credentials', 'local_credentials', 'agents']
