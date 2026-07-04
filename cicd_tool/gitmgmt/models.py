from django.db import models
from django.contrib.auth.models import User
from django.urls import reverse

class Organization(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_organizations')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Team(models.Model):
    name = models.CharField(max_length=100)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='teams')
    members = models.ManyToManyField(User, related_name='teams')

    def __str__(self):
        return f"{self.organization.name} / {self.name}"

class Repository(models.Model):
    VISIBILITY_CHOICES = (
        ('public', 'Public'),
        ('private', 'Private'),
    )
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, null=True, blank=True, related_name='repositories')
    owner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='owned_repositories')
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default='public')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    stars = models.ManyToManyField(User, related_name='starred_repositories', blank=True)
    application = models.OneToOneField('pipeline.Application', on_delete=models.CASCADE, null=True, blank=True, related_name='repository')

    def __str__(self):
        return self.name
    
    def get_absolute_url(self):
        return reverse('repository_detail', kwargs={'repository_name': self.name})

class Collaborator(models.Model):
    ROLE_CHOICES = (
        ('read', 'Read'),
        ('write', 'Write'),
        ('admin', 'Admin'),
    )
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='collaborators')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='collaborations')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='read')

    class Meta:
        unique_together = ('repository', 'user')

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    bio = models.TextField(max_length=500, blank=True)
    location = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)

    def __str__(self):
        return self.user.username

class PersonalAccessToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tokens')
    name = models.CharField(max_length=100)
    token = models.CharField(max_length=64, unique=True) # Hashed token
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} - {self.user.username}"

class Branch(models.Model):
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='branches')
    name = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)
    is_protected = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.repository.name}/{self.name}"

class Commit(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='commits')
    message = models.TextField()
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='commits')
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
    author = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='pull_requests_created')
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
