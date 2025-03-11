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

class UploadFileForm(forms.Form):
    file = forms.FileField()


from django import forms
from .models import PullRequest, Branch

class PullRequestForm(forms.ModelForm):
    class Meta:
        model = PullRequest
        fields = ['title', 'description', 'source_branch', 'target_branch']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        repository = kwargs.pop('repository', None)
        super().__init__(*args, **kwargs)
        if repository:
            self.fields['source_branch'].queryset = Branch.objects.filter(repository=repository)
            self.fields['target_branch'].queryset = Branch.objects.filter(repository=repository)
        
        for field in self.fields:
            self.fields[field].widget.attrs.update({'class': 'form-control'})
        
    def clean(self):
        cleaned_data = super().clean()
        source_branch = cleaned_data.get('source_branch')
        target_branch = cleaned_data.get('target_branch')
        
        if source_branch == target_branch:
            raise forms.ValidationError("Source and target branches must be different.")
        
        return cleaned_data

from django import forms
from .models import PullRequestComment

class PullRequestCommentForm(forms.ModelForm):
    class Meta:
        model = PullRequestComment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Add your comment here...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['content'].label = ''  # Remove the label
        self.fields['content'].widget.attrs.update({'class': 'form-control'})  # Add Bootstrap class