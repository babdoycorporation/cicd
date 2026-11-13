import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gitmgmt', '0006_alter_repository_visibility'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='notification_type',
            field=models.CharField(choices=[('mention', 'Mention'), ('review_requested', 'Review Requested'), ('push', 'Push'), ('pull_request', 'Pull Request'), ('issue', 'Issue'), ('pipeline', 'Pipeline'), ('release', 'Release'), ('access_request', 'Access Request'), ('access_granted', 'Access Granted')], max_length=30),
        ),
        migrations.CreateModel(
            name='RepositoryAccessRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('permission_requested', models.CharField(choices=[('clone', 'Clone / Pull Access'), ('push', 'Push / Write Access')], default='clone', max_length=10)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending', max_length=10)),
                ('reason', models.TextField(blank=True, help_text='Reason for requesting repository access.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('repository', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='access_requests', to='gitmgmt.repository')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_repo_requests', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='repo_access_requests', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]

