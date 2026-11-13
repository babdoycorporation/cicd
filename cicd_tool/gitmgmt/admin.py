from django.contrib import admin
from .models import (
    ActivityEvent, Branch, BranchProtectionRule, Collaborator, Commit,
    Issue, IssueComment, Label, Milestone, Notification, Organization,
    OrganizationMember, PersonalAccessToken, PRReview, PRReviewComment,
    PullRequest, PullRequestComment, Reaction, Release, Repository, Team,
    UserProfile,
)

admin.site.register(OrganizationMember)


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'visibility', 'star_count', 'fork_count', 'created_at')
    list_filter = ('visibility', 'is_fork')
    search_fields = ('name', 'owner__username')


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ('number', 'title', 'repository', 'state', 'author', 'created_at')
    list_filter = ('state', 'repository')
    search_fields = ('title', 'body')


@admin.register(PullRequest)
class PullRequestAdmin(admin.ModelAdmin):
    list_display = ('number', 'title', 'repository', 'status', 'author', 'is_draft', 'created_at')
    list_filter = ('status', 'is_draft')
    search_fields = ('title',)


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ('name', 'repository', 'color')


@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ('title', 'repository', 'state', 'due_date', 'progress_pct')


@admin.register(Release)
class ReleaseAdmin(admin.ModelAdmin):
    list_display = ('tag_name', 'repository', 'title', 'is_prerelease', 'is_draft', 'created_at')


@admin.register(ActivityEvent)
class ActivityEventAdmin(admin.ModelAdmin):
    list_display = ('user', 'event_type', 'repository', 'created_at')
    list_filter = ('event_type',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'notification_type', 'title', 'is_read', 'created_at')
    list_filter = ('is_read', 'notification_type')


admin.site.register(Organization)
admin.site.register(Team)
admin.site.register(Collaborator)
admin.site.register(UserProfile)
admin.site.register(PersonalAccessToken)
admin.site.register(Branch)
admin.site.register(BranchProtectionRule)
admin.site.register(Commit)
admin.site.register(PullRequestComment)
admin.site.register(PRReview)
admin.site.register(PRReviewComment)
admin.site.register(IssueComment)
admin.site.register(Reaction)
