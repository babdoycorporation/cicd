from django import forms
from django.contrib.auth.models import User

from .models import (
    Branch, Issue, IssueComment, Label, Milestone,
    PRReview, PRReviewComment, PullRequest, PullRequestComment,
    Release, Repository, UserProfile,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Repository
# ─────────────────────────────────────────────────────────────────────────────

class RepositoryForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'visibility' in self.fields and not self.instance.pk:
            self.fields['visibility'].initial = 'private'

    class Meta:
        model = Repository
        fields = ['name', 'description', 'visibility', 'default_branch']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'my-project'}),
            'description': forms.Textarea(attrs={'class': 'form-textarea', 'rows': 3}),
            'visibility': forms.Select(attrs={'class': 'form-select'}),
            'default_branch': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'main'}),
        }


class UploadFileForm(forms.Form):
    file = forms.FileField(widget=forms.ClearableFileInput(attrs={'class': 'form-input'}))
    commit_message = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Add file via upload'}),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Pull Requests
# ─────────────────────────────────────────────────────────────────────────────

class PullRequestForm(forms.ModelForm):
    class Meta:
        model = PullRequest
        fields = ['title', 'description', 'source_branch', 'target_branch', 'is_draft', 'labels', 'assignees', 'milestone']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input'}),
            'description': forms.Textarea(attrs={'rows': 6, 'class': 'form-textarea'}),
            'source_branch': forms.Select(attrs={'class': 'form-select'}),
            'target_branch': forms.Select(attrs={'class': 'form-select'}),
            'is_draft': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'labels': forms.CheckboxSelectMultiple(),
            'assignees': forms.CheckboxSelectMultiple(),
            'milestone': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, repository=None, **kwargs):
        super().__init__(*args, **kwargs)
        if repository:
            self.fields['source_branch'].queryset = Branch.objects.filter(repository=repository)
            self.fields['target_branch'].queryset = Branch.objects.filter(repository=repository)
            self.fields['labels'].queryset = Label.objects.filter(repository=repository)
            self.fields['milestone'].queryset = Milestone.objects.filter(repository=repository, state='open')
            self.fields['assignees'].queryset = User.objects.filter(
                collaborations__repository=repository
            ).distinct()

    def clean(self):
        cleaned = super().clean()
        src = cleaned.get('source_branch')
        tgt = cleaned.get('target_branch')
        if src and tgt and src == tgt:
            raise forms.ValidationError("Source and target branches must be different.")
        return cleaned


class PullRequestCommentForm(forms.ModelForm):
    class Meta:
        model = PullRequestComment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={
                'rows': 4, 'class': 'form-textarea',
                'placeholder': 'Leave a comment…',
            }),
        }
        labels = {'content': ''}


class PRReviewForm(forms.ModelForm):
    class Meta:
        model = PRReview
        fields = ['state', 'body']
        widgets = {
            'state': forms.RadioSelect(),
            'body': forms.Textarea(attrs={'rows': 5, 'class': 'form-textarea', 'placeholder': 'Leave a review comment…'}),
        }


class PRReviewCommentForm(forms.ModelForm):
    class Meta:
        model = PRReviewComment
        fields = ['file_path', 'line_number', 'content']
        widgets = {
            'file_path': forms.HiddenInput(),
            'line_number': forms.HiddenInput(),
            'content': forms.Textarea(attrs={'rows': 3, 'class': 'form-textarea'}),
        }


# ─────────────────────────────────────────────────────────────────────────────
#  Issues
# ─────────────────────────────────────────────────────────────────────────────

class IssueForm(forms.ModelForm):
    class Meta:
        model = Issue
        fields = ['title', 'body', 'labels', 'assignees', 'milestone']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Issue title'}),
            'body': forms.Textarea(attrs={'rows': 8, 'class': 'form-textarea', 'placeholder': 'Describe the issue…'}),
            'labels': forms.CheckboxSelectMultiple(),
            'assignees': forms.CheckboxSelectMultiple(),
            'milestone': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, repository=None, **kwargs):
        super().__init__(*args, **kwargs)
        if repository:
            self.fields['labels'].queryset = Label.objects.filter(repository=repository)
            self.fields['milestone'].queryset = Milestone.objects.filter(repository=repository, state='open')
            self.fields['assignees'].queryset = User.objects.filter(
                collaborations__repository=repository
            ).distinct()


class IssueCommentForm(forms.ModelForm):
    class Meta:
        model = IssueComment
        fields = ['body']
        widgets = {
            'body': forms.Textarea(attrs={
                'rows': 4, 'class': 'form-textarea',
                'placeholder': 'Write a comment…',
            }),
        }
        labels = {'body': ''}


# ─────────────────────────────────────────────────────────────────────────────
#  Labels & Milestones
# ─────────────────────────────────────────────────────────────────────────────

class LabelForm(forms.ModelForm):
    class Meta:
        model = Label
        fields = ['name', 'color', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input'}),
            'color': forms.TextInput(attrs={'type': 'color', 'class': 'form-input w-16 h-10 p-1'}),
            'description': forms.TextInput(attrs={'class': 'form-input'}),
        }


class MilestoneForm(forms.ModelForm):
    class Meta:
        model = Milestone
        fields = ['title', 'description', 'due_date']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-textarea'}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-input'}),
        }


# ─────────────────────────────────────────────────────────────────────────────
#  Releases
# ─────────────────────────────────────────────────────────────────────────────

class ReleaseForm(forms.ModelForm):
    class Meta:
        model = Release
        fields = ['tag_name', 'title', 'description', 'target_commitish', 'is_prerelease', 'is_draft']
        widgets = {
            'tag_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'v1.0.0'}),
            'title': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Release title'}),
            'description': forms.Textarea(attrs={'rows': 8, 'class': 'form-textarea'}),
            'target_commitish': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'main'}),
            'is_prerelease': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'is_draft': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }


# ─────────────────────────────────────────────────────────────────────────────
#  User profile
# ─────────────────────────────────────────────────────────────────────────────

class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['avatar', 'bio', 'location', 'website', 'company', 'twitter_handle']
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 3, 'class': 'form-textarea'}),
            'location': forms.TextInput(attrs={'class': 'form-input'}),
            'website': forms.URLInput(attrs={'class': 'form-input'}),
            'company': forms.TextInput(attrs={'class': 'form-input'}),
            'twitter_handle': forms.TextInput(attrs={'class': 'form-input', 'placeholder': '@handle'}),
        }
