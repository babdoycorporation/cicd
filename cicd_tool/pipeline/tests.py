import os
import tempfile

from django.contrib.auth.models import User
from django.test import TestCase
from git import Repo

from gitmgmt.models import Repository
from gitmgmt.views import _get_head_commits, _trigger_repo_pipelines_on_push
from pipeline.forms import GlobalCredentialForm, LocalCredentialForm
from pipeline.models import (Agent, Application, Credential, DeploymentTarget,
                             GlobalSettings, Pipeline, PipelineRun,
                             PipelineStep, Project)
from pipeline.utils import (_parse_ssh_target, _resolve_repo_path,
                            ensure_local_runner_agent,
                            sync_pipeline_from_repo_workdir,
                            sync_steps_from_yaml)
from pipeline.worker import _should_run_step


class Phase1PipelineFixesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('tester', 'tester@cogfocus.com', 'Pass1234!')
        self.project = Project.objects.create(name='DemoProj')
        self.app = Application.objects.create(name='DemoApp', project=self.project, default_branch='main')

    def test_resolve_repo_path_uses_global_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            GlobalSettings.objects.create(key='REPO_STORAGE_PATH', value=tmp)
            bare_dir = os.path.join(tmp, 'DemoRepo.git')
            os.makedirs(bare_dir)
            self.assertEqual(_resolve_repo_path('DemoRepo'), bare_dir)

    def test_sync_steps_from_yaml_preserves_conditions(self):
        pipe = Pipeline.objects.create(name='DemoPipe', application=self.app)
        yaml_doc = """
stages:
  - name: Build
    steps:
      - name: Lint
        command: echo lint
      - name: Rollback
        command: echo rollback
        condition: on_failure
      - name: Cleanup
        command: echo cleanup
        condition: always
"""
        count = sync_steps_from_yaml(pipe, yaml_doc)
        self.assertEqual(count, 3)
        steps = list(PipelineStep.objects.filter(pipeline=pipe).order_by('id'))
        self.assertEqual(steps[1].condition, 'on_failure')
        self.assertEqual(steps[2].condition, 'always')

        self.assertTrue(_should_run_step('', 'success'))
        self.assertFalse(_should_run_step('', 'failed'))
        self.assertFalse(_should_run_step('on_failure', 'success'))
        self.assertTrue(_should_run_step('on_failure', 'failed'))
        self.assertTrue(_should_run_step('always', 'failed'))

    def test_parse_ssh_target_port_and_command(self):
        cred = Credential.objects.create(
            service_name='prod_ssh',
            credential_type='ssh',
            username='sshadmin',
            password='SecretPassword',
            extra={'port': 1966, 'deploy_command': 'systemctl restart gstbook'},
        )
        target = DeploymentTarget.objects.create(
            name='ProdServer',
            target_type='ssh',
            endpoint='100.74.126.231',
            namespace='/opt/gstbook',
            credential=cred,
        )
        host, port, user, cmd, key_text, pw = _parse_ssh_target(target, cred)
        self.assertEqual(host, '100.74.126.231')
        self.assertEqual(port, 1966)
        self.assertEqual(user, 'sshadmin')
        self.assertEqual(cmd, 'systemctl restart gstbook')
        self.assertEqual(key_text, '')
        self.assertEqual(pw, 'SecretPassword')

        # Host:port syntax without extra overrides
        cred.extra = {}
        cred.password = ''
        cred.token = '-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----'
        cred.save()
        target.endpoint = '100.74.126.231:2222'
        host, port, user, cmd, key_text, pw = _parse_ssh_target(target, cred)
        self.assertEqual((host, port, cmd), ('100.74.126.231', 2222, 'cd "/opt/gstbook" && ./deploy.sh'))
        self.assertIn('PRIVATE KEY', key_text)

    def test_credential_forms_allow_type_and_fallback(self):
        f1 = GlobalCredentialForm(data={
            'service_name': 'docker',
            'credential_type': 'docker_registry',
            'username': 'ci',
            'password': 'pw',
        })
        self.assertTrue(f1.is_valid(), f1.errors)

        f2 = LocalCredentialForm(data={
            'service_name': 'api_key',
            'username': 'user',
            'token': 'tok123',
        })
        self.assertTrue(f2.is_valid(), f2.errors)
        self.assertEqual(f2.cleaned_data['credential_type'], 'generic')

    def test_trigger_repo_pipelines_on_push_and_workdir_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            GlobalSettings.objects.create(key='REPO_STORAGE_PATH', value=tmp)
            bare_path = os.path.join(tmp, 'DemoAppRepo.git')
            Repo.init(bare_path, bare=True)
            work_path = os.path.join(tmp, 'work')
            r = Repo.clone_from(bare_path, work_path)
            r.config_writer().set_value('user', 'name', 'Dev').set_value('user', 'email', 'dev@cogfocus.com').release()
            with open(os.path.join(work_path, 'rockerci.yaml'), 'w', encoding='utf-8') as fh:
                fh.write("stages:\n  - name: Deploy\n    steps:\n      - name: Print\n        command: echo deployed\n")
            r.index.add(['rockerci.yaml'])
            r.index.commit('Add pipeline yaml')
            r.git.branch('-M', 'main')
            r.git.push('-u', 'origin', 'main')
            r.close()

            heads = _get_head_commits(bare_path)
            self.assertIn('main', heads)

            Repository.objects.create(name='DemoAppRepo', owner=self.user, application=self.app)
            pipe = Pipeline.objects.create(
                name='DemoAutoDeploy',
                application=self.app,
                yaml_path='rockerci.yaml',
                monitored_branch='main',
            )
            _trigger_repo_pipelines_on_push('DemoAppRepo', 'main', trigger_source='test push')
            run = PipelineRun.objects.filter(pipeline=pipe).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, 'pending')
            self.assertIn("branch 'main'", run.log)
            self.assertEqual(pipe.pipelinestep_set.count(), 1)

            # Workdir YAML sync also works directly
            with open(os.path.join(work_path, 'rockerci.yaml'), 'w', encoding='utf-8') as fh:
                fh.write("stages:\n  - name: Deploy\n    steps:\n      - name: S1\n        command: echo 1\n      - name: S2\n        command: echo 2\n")
            self.assertEqual(sync_pipeline_from_repo_workdir(pipe, work_path), 2)

    def test_ensure_local_runner_agent_and_atomic_claim(self):
        agent = ensure_local_runner_agent()
        self.assertTrue(agent.live)
        pipe = Pipeline.objects.create(name='AtomicPipe', application=self.app)
        run = PipelineRun.objects.create(pipeline=pipe, status='pending')

        # First claim succeeds, second claim sees 0
        c1 = PipelineRun.objects.filter(pk=run.pk, status='pending').update(status='running', agent=agent)
        c2 = PipelineRun.objects.filter(pk=run.pk, status='pending').update(status='running', agent=agent)
        self.assertEqual((c1, c2), (1, 0))

    def test_sync_steps_from_top_level_steps_yaml(self):
        pipe = Pipeline.objects.create(name='TopLevelStepsPipe', application=self.app)
        yaml_doc = """
version: "1.0"
name: Direct Steps
branch: main
steps:
  - name: Install
    command: pip install -r requirements.txt
  - name: Test
    command: pytest
  - name: Deploy
    command: docker compose up -d
    condition: on_success
"""
        count = sync_steps_from_yaml(pipe, yaml_doc)
        self.assertEqual(count, 3)
        steps = list(PipelineStep.objects.filter(pipeline=pipe).order_by('id'))
        self.assertEqual([s.name for s in steps], ['Install', 'Test', 'Deploy'])
        self.assertEqual(steps[2].condition, 'on_success')

    def test_auto_provision_pipeline_on_repo_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            GlobalSettings.objects.create(key='REPO_STORAGE_PATH', value=tmp)
            bare_path = os.path.join(tmp, 'UnconfiguredRepo.git')
            Repo.init(bare_path, bare=True)

            work_path = os.path.join(tmp, 'workdir')
            r = Repo.clone_from(bare_path, work_path)
            with open(os.path.join(work_path, 'README.md'), 'w') as fh:
                fh.write('# Hello')
            r.index.add(['README.md'])
            r.index.commit('Initial commit')
            r.git.branch('-M', 'main')
            r.git.push('-u', 'origin', 'main')
            r.close()

            # Create Repository without application or pipeline
            repo = Repository.objects.create(name='UnconfiguredRepo', owner=self.user)
            _trigger_repo_pipelines_on_push('UnconfiguredRepo', 'main', trigger_source='auto test')

            repo.refresh_from_db()
            self.assertIsNotNone(repo.application)
            self.assertEqual(repo.application.name, 'UnconfiguredRepo')
            pipeline = Pipeline.objects.filter(application=repo.application).first()
            self.assertIsNotNone(pipeline)
            run = PipelineRun.objects.filter(pipeline=pipeline).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, 'pending')

