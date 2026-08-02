from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('gitmgmt', '0003_new_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='default_repo_visibility',
            field=models.CharField(
                choices=[('public', 'Public'), ('private', 'Private')],
                default='private',
                help_text='Default visibility for new repositories created under this organization.',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='organization',
            name='project_creation_policy',
            field=models.CharField(
                choices=[('owner', 'Owners only'), ('admin', 'Owners and admins'), ('member', 'All members')],
                default='admin',
                help_text='Who is allowed to create projects in this organization.',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='organization',
            name='onboarding_notes',
            field=models.TextField(
                blank=True,
                help_text='Shown to new members — links, conventions, first steps.',
            ),
        ),
        migrations.CreateModel(
            name='OrganizationMember',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(
                    choices=[('owner', 'Owner'), ('admin', 'Admin'), ('member', 'Member')],
                    default='member', max_length=20)),
                ('joined_at', models.DateTimeField(auto_now_add=True)),
                ('organization', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='memberships', to='gitmgmt.organization')),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='org_memberships', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('organization', 'user')},
            },
        ),
    ]
