import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pipeline', '0003_projectpipeline_projectorchestrationstep_and_more'),
    ]

    operations = [
        # ── Add credential_type + extra to Credential ─────────────────────────
        migrations.AddField(
            model_name='credential',
            name='credential_type',
            field=models.CharField(
                choices=[
                    ('generic',         'Generic / Other'),
                    ('aws',             'AWS (Access Key)'),
                    ('azure',           'Azure (Service Principal)'),
                    ('gcp',             'GCP (Service Account)'),
                    ('kubernetes',      'Kubernetes (Kubeconfig / Token)'),
                    ('docker_registry', 'Docker Registry'),
                    ('ssh',             'SSH Key / Password'),
                    ('git',             'Git (Username + Token)'),
                ],
                default='generic',
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name='credential',
            name='extra',
            field=models.JSONField(blank=True, default=dict),
        ),
        # Widen password / token fields (they were 100, now 500)
        migrations.AlterField(
            model_name='credential',
            name='password',
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AlterField(
            model_name='credential',
            name='token',
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AlterField(
            model_name='credential',
            name='username',
            field=models.CharField(blank=True, max_length=100),
        ),

        # ── Create DeploymentTarget ───────────────────────────────────────────
        migrations.CreateModel(
            name='DeploymentTarget',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('description', models.TextField(blank=True)),
                ('target_type', models.CharField(
                    choices=[
                        ('kubernetes',       'Kubernetes (kubectl / Helm)'),
                        ('aws_ecs',          'AWS ECS'),
                        ('aws_eks',          'AWS EKS'),
                        ('aws_lambda',       'AWS Lambda'),
                        ('azure_aks',        'Azure AKS'),
                        ('azure_appservice', 'Azure App Service'),
                        ('gcp_gke',          'GCP GKE'),
                        ('gcp_cloudrun',     'GCP Cloud Run'),
                        ('docker_registry',  'Docker Registry (push image)'),
                        ('ssh',              'SSH / Server (shell over SSH)'),
                    ],
                    max_length=30,
                )),
                ('endpoint',  models.CharField(blank=True, max_length=500)),
                ('region',    models.CharField(blank=True, max_length=100)),
                ('namespace', models.CharField(blank=True, max_length=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('credential', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='deployment_targets',
                    to='pipeline.credential',
                )),
                ('environment', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='deployment_targets',
                    to='pipeline.environment',
                )),
                ('project', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='deployment_targets',
                    to='pipeline.project',
                )),
            ],
            options={'ordering': ['name']},
        ),
    ]
