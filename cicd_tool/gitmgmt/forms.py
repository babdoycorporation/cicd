from django import forms
from .models import Repository

from django import forms
from .models import Repository

class RepositoryForm(forms.ModelForm):
    class Meta:
        model = Repository
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50'}),
            'description': forms.Textarea(attrs={'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50', 'rows': 3}),
        }

from django import forms
from .models import PullRequest

class PullRequestForm(forms.ModelForm):
    class Meta:
        model = PullRequest
        fields = ['title', 'description', 'source_branch', 'target_branch']

from django import forms

class UploadFileForm(forms.Form):
    file = forms.FileField()
