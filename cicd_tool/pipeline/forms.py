from django import forms
from .models import (Project, Pipeline, Stage, Step, Agent, Credential,
                     Application, GlobalSettings, DeploymentTarget)
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
        fields = ['service_name', 'credential_type', 'username', 'password', 'token']

class LocalCredentialForm(forms.ModelForm):
    class Meta:
        model = Credential
        fields = ['service_name', 'credential_type', 'username', 'password', 'token']


class DeploymentTargetForm(forms.ModelForm):
    class Meta:
        model = DeploymentTarget
        fields = [
            'name', 'description', 'target_type',
            'endpoint', 'region', 'namespace',
            'environment', 'project', 'credential',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['credential'].queryset = Credential.objects.all().order_by('service_name')

class ApplicationForm(forms.ModelForm):
    REPO_MODE_CHOICES = (
        ('create', 'Initialize a new repository (recommended)'),
        ('link', 'Link an existing repository'),
        ('none', 'No repository for now'),
    )
    repo_mode = forms.ChoiceField(
        choices=REPO_MODE_CHOICES, initial='create',
        widget=forms.RadioSelect, label='Source repository')
    existing_repository = forms.ModelChoiceField(
        queryset=None, required=False, label='Existing repository')

    class Meta:
        model = Application
        fields = ['name', 'description', 'default_branch']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from gitmgmt.models import Repository
        self.fields['existing_repository'].queryset = Repository.objects.all().order_by('name')

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get('repo_mode')
        if mode == 'link':
            repo = cleaned.get('existing_repository')
            if not repo:
                self.add_error('existing_repository', 'Select the repository to link.')
            elif repo.application_id:
                self.add_error('existing_repository',
                    f"'{repo.name}' already backs another application.")
        if mode == 'create' and cleaned.get('name'):
            from gitmgmt.models import Repository
            if Repository.objects.filter(name=cleaned['name']).exists():
                self.add_error('name',
                    f"A repository named '{cleaned['name']}' already exists. "
                    "Choose another application name or link the existing repository.")
        return cleaned


class ApplicationSettingsForm(forms.ModelForm):
    repository = forms.ModelChoiceField(queryset=None, required=False, label='Linked repository')

    class Meta:
        model = Application
        fields = ['description', 'default_branch']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from gitmgmt.models import Repository
        self.fields['repository'].queryset = Repository.objects.all().order_by('name')
        if self.instance.pk:
            self.initial['repository'] = Repository.objects.filter(application=self.instance).first()

    def clean_repository(self):
        repo = self.cleaned_data.get('repository')
        if repo and repo.application_id and repo.application_id != self.instance.pk:
            raise forms.ValidationError(f"'{repo.name}' already backs another application.")
        return repo

class GlobalSettingsForm(forms.ModelForm):
    class Meta:
        model = GlobalSettings
        fields = ['key', 'value']
