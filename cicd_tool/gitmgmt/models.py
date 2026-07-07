import hashlib
import secrets

from django.contrib.auth.models import User
from django.db import models
from django.urls import reverse
from django.utils import timezone


# ─────────────────────────────────────────────────────────────────────────────
#  Organisation / Team
# ─────────────────────────────────────────────────────────────────────────────

class Organization(models.Model):
    VISIBILITY_CHOICES = (('public', 'Public'), ('private', 'Private'))
    PROJECT_CREATION_CHOICES = (
        ('owner', 'Owners only'),
        ('admin', 'Owners and admins'),
        ('member', 'All members'),
    )

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_organizations')
    avatar = models.ImageField(upload_to='org_avatars/', null=True, blank=True)
    website = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # ── Organization-wide policies ──
    default_repo_visibility = models.CharField(
        max_length=10, choices=VISIBILITY_CHOICES, default='private',
        help_text='Default visibility for new repositories created under this organization.')
    project_creation_policy = models.CharField(
        max_length=10, choices=PROJECT_CREATION_CHOICES, default='admin',
        help_text='Who is allowed to create projects in this organization.')
    onboarding_notes = models.TextField(
        blank=True,
        help_text='Shown to new members — links, conventions, first steps.')

    def __str__(self):
        return self.name

    def get_member_role(self, user):
        """Return the role of a user in this organization, or None."""
        if user == self.owner:
            return 'owner'
        m = self.memberships.filter(user=user).first()
        return m.role if m else None

    def user_can_create_projects(self, user):
        role = self.get_member_role(user)
        if role is None:
            return False
        if self.project_creation_policy == 'member':
            return True
        if self.project_creation_policy == 'admin':
            return role in ('owner', 'admin')
        return role == 'owner'


class OrganizationMember(models.Model):
    """Role-based membership of a user in an organization."""
    ROLE_CHOICES = (
        ('owner', 'Owner'),
        ('admin', 'Admin'),
        ('member', 'Member'),
    )
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='org_memberships')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='member')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('organization', 'user')

    def __str__(self):
        return f"{self.user.username} @ {self.organization.name} ({self.role})"


class Team(models.Model):
    name = models.CharField(max_length=100)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='teams')
    members = models.ManyToManyField(User, related_name='teams', blank=True)
    description = models.TextField(blank=True)

    class Meta:
        unique_together = ('organization', 'name')

    def __str__(self):
        return f"{self.organization.name} / {self.name}"


# ─────────────────────────────────────────────────────────────────────────────
#  Repository
# ─────────────────────────────────────────────────────────────────────────────

class Repository(models.Model):
    VISIBILITY_CHOICES = (('public', 'Public'), ('private', 'Private'))

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    organization = models.ForeignKey(
        Organization, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='repositories'
    )
    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True,
        related_name='owned_repositories'
    )
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default='public')
    default_branch = models.CharField(max_length=100, default='main')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    stars = models.ManyToManyField(User, related_name='starred_repositories', blank=True)
    watchers = models.ManyToManyField(User, related_name='watched_repositories', blank=True)
    application = models.OneToOneField(
        'pipeline.Application', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='repository'
    )
    # Fork tracking
    forked_from = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='forks'
    )
    is_fork = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('repository_detail', kwargs={'repository_name': self.name})

    @property
    def star_count(self):
        return self.stars.count()

    @property
    def fork_count(self):
        return self.forks.count()

    @property
    def open_issues_count(self):
        return self.issues.filter(state='open').count()

    @property
    def open_pr_count(self):
        return self.pull_requests.filter(status='open').count()


class Collaborator(models.Model):
    ROLE_CHOICES = (('read', 'Read'), ('write', 'Write'), ('admin', 'Admin'))
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='collaborators')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='collaborations')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='read')

    class Meta:
        unique_together = ('repository', 'user')

    def __str__(self):
        return f"{self.user.username} → {self.repository.name} [{self.role}]"


# ─────────────────────────────────────────────────────────────────────────────
#  User profile & access tokens
# ─────────────────────────────────────────────────────────────────────────────

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    bio = models.TextField(max_length=500, blank=True)
    location = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    company = models.CharField(max_length=100, blank=True)
    twitter_handle = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return self.user.username


class PersonalAccessToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tokens')
    name = models.CharField(max_length=100)
    token_hash = models.CharField(max_length=64, unique=True)   # SHA-256 hex of the raw token
    prefix = models.CharField(max_length=8, default='')         # first 8 chars shown in UI
    scopes = models.CharField(max_length=200, blank=True, default='repo')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} — {self.user.username}"

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode()).hexdigest()

    @classmethod
    def create_token(cls, user, name, scopes='repo', expires_at=None):
        """Generate a new token, store its hash, return (instance, raw_token)."""
        raw = secrets.token_hex(32)
        obj = cls.objects.create(
            user=user,
            name=name,
            token_hash=cls.hash_token(raw),
            prefix=raw[:8],
            scopes=scopes,
            expires_at=expires_at,
        )
        return obj, raw

    def verify(self, raw_token: str) -> bool:
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return self.token_hash == self.hash_token(raw_token)


# ─────────────────────────────────────────────────────────────────────────────
#  Branch / Commit
# ─────────────────────────────────────────────────────────────────────────────

class Branch(models.Model):
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='branches')
    name = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)
    is_protected = models.BooleanField(default=False)

    class Meta:
        unique_together = ('repository', 'name')

    def __str__(self):
        return f"{self.repository.name}/{self.name}"


class BranchProtectionRule(models.Model):
    branch = models.OneToOneField(Branch, on_delete=models.CASCADE, related_name='protection_rule')
    require_pull_request = models.BooleanField(default=True)
    required_approvals = models.PositiveIntegerField(default=1)
    dismiss_stale_reviews = models.BooleanField(default=False)
    require_status_checks = models.BooleanField(default=False)
    allow_force_push = models.BooleanField(default=False)
    restrict_pushes = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"Protection: {self.branch}"


class Commit(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='commits')
    message = models.TextField()
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='commits')
    author_name = models.CharField(max_length=100, blank=True)
    author_email = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    hash = models.CharField(max_length=40, unique=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.hash[:7]} — {self.message[:60]}"


# ─────────────────────────────────────────────────────────────────────────────
#  Labels & Milestones
# ─────────────────────────────────────────────────────────────────────────────

class Label(models.Model):
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='labels')
    name = models.CharField(max_length=50)
    color = models.CharField(max_length=7, default='#0075ca')   # CSS hex
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = ('repository', 'name')

    def __str__(self):
        return f"{self.repository.name} / {self.name}"


class Milestone(models.Model):
    STATE_CHOICES = [('open', 'Open'), ('closed', 'Closed')]
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='milestones')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default='open')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_milestones')
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['due_date', 'title']

    def __str__(self):
        return f"{self.repository.name} — {self.title}"

    @property
    def open_issue_count(self):
        return self.issues.filter(state='open').count()

    @property
    def closed_issue_count(self):
        return self.issues.filter(state='closed').count()

    @property
    def progress_pct(self):
        total = self.issues.count()
        if not total:
            return 0
        return int(self.closed_issue_count / total * 100)


# ─────────────────────────────────────────────────────────────────────────────
#  Issues
# ─────────────────────────────────────────────────────────────────────────────

class Issue(models.Model):
    STATE_CHOICES = [('open', 'Open'), ('closed', 'Closed')]

    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='issues')
    number = models.PositiveIntegerField(editable=False)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default='open')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_issues')
    assignees = models.ManyToManyField(User, blank=True, related_name='assigned_issues')
    labels = models.ManyToManyField(Label, blank=True, related_name='issues')
    milestone = models.ForeignKey(
        Milestone, on_delete=models.SET_NULL, null=True, blank=True, related_name='issues'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='closed_issues'
    )

    class Meta:
        unique_together = ('repository', 'number')
        ordering = ['-created_at']

    def __str__(self):
        return f"#{self.number} {self.title}"

    def save(self, *args, **kwargs):
        if not self.pk:
            last = Issue.objects.filter(repository=self.repository).order_by('-number').first()
            self.number = (last.number + 1) if last else 1
        super().save(*args, **kwargs)


class IssueComment(models.Model):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='issue_comments')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment on {self.issue} by {self.author}"


# ─────────────────────────────────────────────────────────────────────────────
#  Pull Requests & Reviews
# ─────────────────────────────────────────────────────────────────────────────

class PullRequest(models.Model):
    STATUS_CHOICES = (('open', 'Open'), ('closed', 'Closed'), ('merged', 'Merged'))
    DRAFT_HELP = 'Draft PRs cannot be merged until marked ready.'

    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='pull_requests')
    number = models.PositiveIntegerField(editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    author = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True,
        related_name='pull_requests_created'
    )
    source_branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='source_pull_requests')
    target_branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='target_pull_requests')
    labels = models.ManyToManyField(Label, blank=True, related_name='pull_requests')
    assignees = models.ManyToManyField(User, blank=True, related_name='assigned_prs')
    reviewers = models.ManyToManyField(User, blank=True, related_name='review_requested_prs')
    milestone = models.ForeignKey(
        Milestone, on_delete=models.SET_NULL, null=True, blank=True, related_name='pull_requests'
    )
    is_draft = models.BooleanField(default=False, help_text=DRAFT_HELP)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open')
    merged_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='merged_pull_requests'
    )
    merged_at = models.DateTimeField(null=True, blank=True)
    merge_commit_sha = models.CharField(max_length=40, blank=True)

    class Meta:
        unique_together = ('repository', 'number')
        ordering = ['-created_at']

    def __str__(self):
        return f"PR #{self.number}: {self.title}"

    def save(self, *args, **kwargs):
        if not self.pk:
            last = PullRequest.objects.filter(repository=self.repository).order_by('-number').first()
            self.number = (last.number + 1) if last else 1
        super().save(*args, **kwargs)

    @property
    def approved_count(self):
        return self.reviews.filter(state='approved').count()

    @property
    def changes_requested_count(self):
        return self.reviews.filter(state='changes_requested').count()

    def can_merge(self, user):
        """Returns (can_merge: bool, reason: str)."""
        if self.status != 'open':
            return False, f"PR is {self.status}."
        if self.is_draft:
            return False, "PR is a draft."
        target = self.target_branch
        if target.is_protected:
            rule = getattr(target, 'protection_rule', None)
            if rule:
                if rule.require_pull_request and self.approved_count < rule.required_approvals:
                    return False, f"Needs {rule.required_approvals} approval(s); has {self.approved_count}."
        if self.repository.owner != user and not user.is_staff:
            collab = self.repository.collaborators.filter(user=user, role__in=['write', 'admin']).first()
            if not collab:
                return False, "You don't have write access to this repository."
        return True, ""


class PullRequestComment(models.Model):
    pull_request = models.ForeignKey(PullRequest, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment on {self.pull_request} by {self.user}"


class PRReview(models.Model):
    STATE_CHOICES = [
        ('approved', 'Approved'),
        ('changes_requested', 'Changes Requested'),
        ('commented', 'Commented'),
        ('dismissed', 'Dismissed'),
    ]
    pull_request = models.ForeignKey(PullRequest, on_delete=models.CASCADE, related_name='reviews')
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pr_reviews')
    state = models.CharField(max_length=25, choices=STATE_CHOICES, default='commented')
    body = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Review by {self.reviewer} on {self.pull_request} [{self.state}]"


class PRReviewComment(models.Model):
    """Inline code-review comment tied to a specific file + line in a PR diff."""
    pull_request = models.ForeignKey(PullRequest, on_delete=models.CASCADE, related_name='review_comments')
    review = models.ForeignKey(PRReview, on_delete=models.SET_NULL, null=True, blank=True, related_name='line_comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    file_path = models.CharField(max_length=500)
    line_number = models.PositiveIntegerField(null=True, blank=True)
    diff_hunk = models.TextField(blank=True)
    content = models.TextField()
    in_reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['file_path', 'line_number', 'created_at']

    def __str__(self):
        return f"Inline comment on {self.file_path}:{self.line_number}"


# ─────────────────────────────────────────────────────────────────────────────
#  Reactions
# ─────────────────────────────────────────────────────────────────────────────

class Reaction(models.Model):
    EMOJI_CHOICES = [
        ('+1', '👍'), ('-1', '👎'), ('laugh', '😄'), ('hooray', '🎉'),
        ('confused', '😕'), ('heart', '❤️'), ('rocket', '🚀'), ('eyes', '👀'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    emoji = models.CharField(max_length=20, choices=EMOJI_CHOICES)
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, null=True, blank=True, related_name='reactions')
    issue_comment = models.ForeignKey(
        IssueComment, on_delete=models.CASCADE, null=True, blank=True, related_name='reactions'
    )
    pr_comment = models.ForeignKey(
        PullRequestComment, on_delete=models.CASCADE, null=True, blank=True, related_name='reactions'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} reacted {self.emoji}"


# ─────────────────────────────────────────────────────────────────────────────
#  Releases / Tags
# ─────────────────────────────────────────────────────────────────────────────

class Release(models.Model):
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='releases')
    tag_name = models.CharField(max_length=100)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_releases')
    created_at = models.DateTimeField(auto_now_add=True)
    is_prerelease = models.BooleanField(default=False)
    is_draft = models.BooleanField(default=False)
    target_commitish = models.CharField(max_length=100, default='main')

    class Meta:
        unique_together = ('repository', 'tag_name')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.repository.name} {self.tag_name}"


# ─────────────────────────────────────────────────────────────────────────────
#  Activity / Notifications
# ─────────────────────────────────────────────────────────────────────────────

class ActivityEvent(models.Model):
    EVENT_CHOICES = [
        ('push', 'Push'), ('pull_request', 'Pull Request'), ('issue', 'Issue'),
        ('comment', 'Comment'), ('fork', 'Fork'), ('star', 'Star'),
        ('release', 'Release'), ('branch', 'Branch'), ('merge', 'Merge'),
        ('pipeline', 'Pipeline'), ('review', 'Review'), ('milestone', 'Milestone'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    repository = models.ForeignKey(
        Repository, on_delete=models.CASCADE, null=True, blank=True, related_name='activities'
    )
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES)
    description = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} {self.event_type} @ {self.created_at:%Y-%m-%d %H:%M}"


def log_activity(user, event_type, description, repository=None, **metadata):
    """Helper to create an ActivityEvent without boilerplate."""
    ActivityEvent.objects.create(
        user=user, event_type=event_type, description=description,
        repository=repository, metadata=metadata,
    )


class Notification(models.Model):
    TYPE_CHOICES = [
        ('mention', 'Mention'),
        ('review_requested', 'Review Requested'),
        ('push', 'Push'),
        ('pull_request', 'Pull Request'),
        ('issue', 'Issue'),
        ('pipeline', 'Pipeline'),
        ('release', 'Release'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    title = models.CharField(max_length=200)
    content = models.TextField()
    link = models.CharField(max_length=500, blank=True)
    is_read = models.BooleanField(default=False)
    repository = models.ForeignKey(
        Repository, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.notification_type}] {self.title} → {self.user}"


def notify(users, notification_type, title, content, link='', repository=None):
    """Create Notification records for one or many users."""
    if isinstance(users, User):
        users = [users]
    objs = [
        Notification(
            user=u, notification_type=notification_type,
            title=title, content=content, link=link, repository=repository,
        )
        for u in users
    ]
    Notification.objects.bulk_create(objs)
