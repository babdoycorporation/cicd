from django import forms
from .models import Repository

class RepositoryForm(forms.ModelForm):
    class Meta:
        model = Repository
        fields = ['name', 'description']

from django import forms
from .models import PullRequest

class PullRequestForm(forms.ModelForm):
    class Meta:
        model = PullRequest
        fields = ['title', 'description', 'source_branch', 'target_branch']

from django import forms

class UploadFileForm(forms.Form):
    file = forms.FileField()
