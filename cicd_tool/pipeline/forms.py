from django import forms
from .models import Project, Pipeline, Stage, Step, Agent, Credential, Application, GlobalSettings
import json

class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name', 'repository_url', 'organization']

class ProjectConfigurationForm(forms.ModelForm):
    environment_variables = forms.CharField(widget=forms.Textarea(attrs={'rows': 5}), required=False)

    class Meta:
        model = Project
        fields = [
            'environment_variables', 'notifications_enabled',
            'notification_emails', 'slack_webhook_url'
        ]
    
    def clean_build_triggers(self):
        data = self.cleaned_data.get('build_triggers')
        if not data: return {}
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            raise forms.ValidationError("Invalid JSON format for build triggers")

    def clean_environment_variables(self):
        data = self.cleaned_data.get('environment_variables')
        if not data: return {}
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            raise forms.ValidationError("Invalid JSON format for environment variables")


class PipelineForm(forms.ModelForm):
    class Meta:
        model = Pipeline
        fields = ['name', 'description', 'application', 'environments', 'yaml_path', 'monitored_branch']


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
        fields = ['hostname', 'ip_address', 'hash_key', 'last_heartbeat', 'operating_system', 'live', 'scope_level', 'project', 'application', 'environments']

class GlobalCredentialForm(forms.ModelForm):
    class Meta:
        model = Credential
        fields = ['service_name', 'username', 'password', 'token']

class LocalCredentialForm(forms.ModelForm):
    class Meta:
        model = Credential
        fields = ['service_name', 'username', 'password', 'token']

class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = ['name']

class GlobalSettingsForm(forms.ModelForm):
    class Meta:
        model = GlobalSettings
        fields = ['key', 'value']
