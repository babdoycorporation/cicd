import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pipeline', '0004_deploytarget_credential_type'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── BuildArtifact ─────────────────────────────────────────────────────
        migrations.CreateModel(
            name='BuildArtifact',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name',         models.CharField(max_length=255)),
                ('file_path',    models.CharField(max_length=500)),
                ('file_size',    models.BigIntegerField(default=0)),
                ('content_type', models.CharField(default='application/octet-stream', max_length=100)),
                ('created_at',   models.DateTimeField(auto_now_add=True)),
                ('pipeline_run', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='artifacts',
                    to='pipeline.pipelinerun',
                )),
            ],
            options={'ordering': ['name']},
        ),

        # ── NotificationIntegration ───────────────────────────────────────────
        migrations.CreateModel(
            name='NotificationIntegration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('integration_type', models.CharField(
                    choices=[
                        ('email', 'Email (SMTP)'),
                        ('slack', 'Slack'),
                        ('teams', 'Microsoft Teams'),
                    ],
                    max_length=20,
                    unique=True,
                )),
                ('name',       models.CharField(max_length=100)),
                ('config',     models.JSONField(blank=True, default=dict)),
                ('is_active',  models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),

        # ── UserNotificationPreference ────────────────────────────────────────
        migrations.CreateModel(
            name='UserNotificationPreference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pipeline_success', models.BooleanField(default=True)),
                ('pipeline_failure', models.BooleanField(default=True)),
                ('pr_assigned',      models.BooleanField(default=True)),
                ('pr_merged',        models.BooleanField(default=False)),
                ('issue_assigned',   models.BooleanField(default=True)),
                ('issue_commented',  models.BooleanField(default=False)),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='notification_prefs',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
    ]
