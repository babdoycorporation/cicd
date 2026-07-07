"""
Manual migration: adds all new GitHub/GitLab-level models.

New models:
  Label, Milestone, Issue, IssueComment, Reaction,
  PRReview, PRReviewComment, BranchProtectionRule,
  Release, ActivityEvent, Notification,
  plus fields added to Repository, Branch, PullRequest,
  PersonalAccessToken, UserProfile, Organization, Team.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('gitmgmt', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── Repository — new fields ───────────────────────────────────────────
        migrations.AddField(
            model_name='repository',
            name='default_branch',
            field=models.CharField(default='main', max_length=100),
        ),
        migrations.AddField(
            model_name='repository',
            name='watchers',
            field=models.ManyToManyField(
                blank=True, related_name='watched_repositories',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='repository',
            name='forked_from',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='forks', to='gitmgmt.repository',
            ),
        ),
        migrations.AddField(
            model_name='repository',
            name='is_fork',
            field=models.BooleanField(default=False),
        ),

        # ── UserProfile — new fields ──────────────────────────────────────────
        migrations.AddField(
            model_name='userprofile',
            name='company',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='twitter_handle',
            field=models.CharField(blank=True, max_length=50),
        ),

        # ── PersonalAccessToken — replace token with token_hash + prefix ──────
        migrations.AddField(
            model_name='personalaccesstoken',
            name='token_hash',
            field=models.CharField(default='', max_length=64, unique=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='personalaccesstoken',
            name='prefix',
            field=models.CharField(blank=True, default='', max_length=8),
        ),
        migrations.AddField(
            model_name='personalaccesstoken',
            name='scopes',
            field=models.CharField(blank=True, default='repo', max_length=200),
        ),
        migrations.AddField(
            model_name='personalaccesstoken',
            name='expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),

        # ── Organization — new fields ─────────────────────────────────────────
        migrations.AddField(
            model_name='organization',
            name='avatar',
            field=models.ImageField(blank=True, null=True, upload_to='org_avatars/'),
        ),
        migrations.AddField(
            model_name='organization',
            name='website',
            field=models.URLField(blank=True),
        ),

        # ── Team — unique_together + description ──────────────────────────────
        migrations.AddField(
            model_name='team',
            name='description',
            field=models.TextField(blank=True),
        ),
        migrations.AlterUniqueTogether(
            name='team',
            unique_together={('organization', 'name')},
        ),

        # ── Branch — unique_together ──────────────────────────────────────────
        migrations.AlterUniqueTogether(
            name='branch',
            unique_together={('repository', 'name')},
        ),

        # ── PullRequest — new fields ──────────────────────────────────────────
        migrations.AddField(
            model_name='pullrequest',
            name='number',
            field=models.PositiveIntegerField(default=1, editable=False),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='pullrequest',
            name='is_draft',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='pullrequest',
            name='merge_commit_sha',
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name='pullrequest',
            name='assignees',
            field=models.ManyToManyField(
                blank=True, related_name='assigned_prs',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='pullrequest',
            name='reviewers',
            field=models.ManyToManyField(
                blank=True, related_name='review_requested_prs',
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # ── Commit — new fields ───────────────────────────────────────────────
        migrations.AddField(
            model_name='commit',
            name='author_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='commit',
            name='author_email',
            field=models.CharField(blank=True, max_length=200),
        ),

        # ── BranchProtectionRule ──────────────────────────────────────────────
        migrations.CreateModel(
            name='BranchProtectionRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('require_pull_request', models.BooleanField(default=True)),
                ('required_approvals', models.PositiveIntegerField(default=1)),
                ('dismiss_stale_reviews', models.BooleanField(default=False)),
                ('require_status_checks', models.BooleanField(default=False)),
                ('allow_force_push', models.BooleanField(default=False)),
                ('restrict_pushes', models.BooleanField(default=False)),
                ('branch', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='protection_rule', to='gitmgmt.branch')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),

        # ── Label ─────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Label',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50)),
                ('color', models.CharField(default='#0075ca', max_length=7)),
                ('description', models.CharField(blank=True, max_length=200)),
                ('repository', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='labels', to='gitmgmt.repository')),
            ],
            options={'unique_together': {('repository', 'name')}},
        ),

        # ── Milestone ─────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Milestone',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('due_date', models.DateField(blank=True, null=True)),
                ('state', models.CharField(choices=[('open', 'Open'), ('closed', 'Closed')], default='open', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('repository', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='milestones', to='gitmgmt.repository')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_milestones', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['due_date', 'title']},
        ),

        # ── PullRequest — M2M labels + milestone ──────────────────────────────
        migrations.AddField(
            model_name='pullrequest',
            name='labels',
            field=models.ManyToManyField(blank=True, related_name='pull_requests', to='gitmgmt.label'),
        ),
        migrations.AddField(
            model_name='pullrequest',
            name='milestone',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pull_requests', to='gitmgmt.milestone'),
        ),

        # ── Issue ─────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Issue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number', models.PositiveIntegerField(editable=False)),
                ('title', models.CharField(max_length=200)),
                ('body', models.TextField(blank=True)),
                ('state', models.CharField(choices=[('open', 'Open'), ('closed', 'Closed')], default='open', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('assignees', models.ManyToManyField(blank=True, related_name='assigned_issues', to=settings.AUTH_USER_MODEL)),
                ('author', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_issues', to=settings.AUTH_USER_MODEL)),
                ('closed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='closed_issues', to=settings.AUTH_USER_MODEL)),
                ('labels', models.ManyToManyField(blank=True, related_name='issues', to='gitmgmt.label')),
                ('milestone', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='issues', to='gitmgmt.milestone')),
                ('repository', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='issues', to='gitmgmt.repository')),
            ],
            options={'ordering': ['-created_at'], 'unique_together': {('repository', 'number')}},
        ),

        # ── IssueComment ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name='IssueComment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('body', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='issue_comments', to=settings.AUTH_USER_MODEL)),
                ('issue', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='comments', to='gitmgmt.issue')),
            ],
            options={'ordering': ['created_at']},
        ),

        # ── Reaction ──────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Reaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('emoji', models.CharField(choices=[('+1', '👍'), ('-1', '👎'), ('laugh', '😄'), ('hooray', '🎉'), ('confused', '😕'), ('heart', '❤️'), ('rocket', '🚀'), ('eyes', '👀')], max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('issue', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='reactions', to='gitmgmt.issue')),
                ('issue_comment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='reactions', to='gitmgmt.issuecomment')),
                ('pr_comment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='reactions', to='gitmgmt.pullrequestcomment')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),

        # ── PRReview ──────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='PRReview',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('state', models.CharField(choices=[('approved', 'Approved'), ('changes_requested', 'Changes Requested'), ('commented', 'Commented'), ('dismissed', 'Dismissed')], default='commented', max_length=25)),
                ('body', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('submitted_at', models.DateTimeField(blank=True, null=True)),
                ('pull_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reviews', to='gitmgmt.pullrequest')),
                ('reviewer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pr_reviews', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),

        # ── PRReviewComment ───────────────────────────────────────────────────
        migrations.CreateModel(
            name='PRReviewComment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file_path', models.CharField(max_length=500)),
                ('line_number', models.PositiveIntegerField(blank=True, null=True)),
                ('diff_hunk', models.TextField(blank=True)),
                ('content', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('in_reply_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='replies', to='gitmgmt.prreviewcomment')),
                ('pull_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='review_comments', to='gitmgmt.pullrequest')),
                ('review', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='line_comments', to='gitmgmt.prreview')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['file_path', 'line_number', 'created_at']},
        ),

        # ── Release ───────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Release',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tag_name', models.CharField(max_length=100)),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('is_prerelease', models.BooleanField(default=False)),
                ('is_draft', models.BooleanField(default=False)),
                ('target_commitish', models.CharField(default='main', max_length=100)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_releases', to=settings.AUTH_USER_MODEL)),
                ('repository', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='releases', to='gitmgmt.repository')),
            ],
            options={'ordering': ['-created_at'], 'unique_together': {('repository', 'tag_name')}},
        ),

        # ── ActivityEvent ─────────────────────────────────────────────────────
        migrations.CreateModel(
            name='ActivityEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(choices=[('push', 'Push'), ('pull_request', 'Pull Request'), ('issue', 'Issue'), ('comment', 'Comment'), ('fork', 'Fork'), ('star', 'Star'), ('release', 'Release'), ('branch', 'Branch'), ('merge', 'Merge'), ('pipeline', 'Pipeline'), ('review', 'Review'), ('milestone', 'Milestone')], max_length=30)),
                ('description', models.TextField()),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('repository', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='activities', to='gitmgmt.repository')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='activities', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),

        # ── Notification ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('notification_type', models.CharField(choices=[('mention', 'Mention'), ('review_requested', 'Review Requested'), ('push', 'Push'), ('pull_request', 'Pull Request'), ('issue', 'Issue'), ('pipeline', 'Pipeline'), ('release', 'Release')], max_length=30)),
                ('title', models.CharField(max_length=200)),
                ('content', models.TextField()),
                ('link', models.CharField(blank=True, max_length=500)),
                ('is_read', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('repository', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to='gitmgmt.repository')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
