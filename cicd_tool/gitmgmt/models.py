from django.db import models
from django.contrib.auth.models import User
from django.urls import reverse

class Repository(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_favorite = models.BooleanField(default=False)

    def __str__(self):
        return self.name
    
    def get_absolute_url(self):
        return reverse('repository_detail', kwargs={'repository_id': self.id})

class Branch(models.Model):
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='branches')
    name = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.repository.name}/{self.name}"

class Commit(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='commits')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    hash = models.CharField(max_length=40, unique=True)

    def __str__(self):
        return f"{self.hash[:7]} - {self.message}"

class PullRequest(models.Model):
    STATUS_CHOICES = (
        ('open', 'Open'),
        ('closed', 'Closed'),
        ('merged', 'Merged'),
    )

    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='pull_requests')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    source_branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='source_pull_requests')
    target_branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='target_pull_requests')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open')
    merged_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='merged_pull_requests')
    merged_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"PR: {self.title} - {self.repository.name}"

class PullRequestComment(models.Model):
    pull_request = models.ForeignKey(PullRequest, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Comment on {self.pull_request} by {self.user}"