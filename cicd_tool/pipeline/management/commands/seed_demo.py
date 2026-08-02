"""
seed_demo — wipe all application data and build a complete demo environment.

Creates:
  • Users:  admin/admin123, alice/alice123 (org admin), bob/bob123 (developer),
            carol/carol123 (viewer)
  • Org:    acme-corp (owner: admin) with members, teams, and policies
  • Project: acme-platform with members, CI/CD variables, notifications
  • Apps:   auth-service, web-frontend — each with an initialized Git repo
            containing real code + rockerci.yaml
  • Pipelines: one per app, monitoring 'main'
  • Data:   labels, milestone, issues, a feature branch and a pull request
  • PAT:    printed once at the end — use it as the git password

Usage:
    python manage.py seed_demo            # asks for confirmation
    python manage.py seed_demo --yes      # no prompt
"""

import os
import shutil
import stat
import subprocess

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from gitmgmt.models import (ActivityEvent, Branch, Collaborator, Commit,
                            Issue, IssueComment, Label, Milestone,
                            Notification, Organization, OrganizationMember,
                            PersonalAccessToken, PRReview, PullRequest,
                            PullRequestComment, Reaction, Release, Repository,
                            Team, UserProfile)
from pipeline.models import (Agent, Application, Build, Command as AgentCommand,
                             Credential, Environment, GlobalSettings, Heartbeat,
                             Pipeline, PipelineRun, PipelineStep, Project,
                             ProjectMember, Stage, Step, Tag, YamlFileVersion)

REPO_BASE_PATH = getattr(settings, 'REPO_BASE_PATH', 'D:/repos')

AUTH_SERVICE_YAML = """name: Auth Service CI
on:
  push:
    branches: [main]

jobs:
  build:
    steps:
      - name: Show environment
        run: echo Building %CI_PIPELINE% on branch %CI_BRANCH% run %CI_RUN_ID%

      - name: List workspace
        run: dir

      - name: Run unit tests
        run: python -m unittest discover -s tests -v

      - name: Package
        run: echo Packaging auth-service... && echo Done.
"""

AUTH_SERVICE_APP = '''"""auth-service — demo authentication microservice."""


def authenticate(username, password):
    """Toy authentication: accepts any non-empty credentials."""
    return bool(username) and bool(password)


def issue_token(username):
    return f"token-{username}-demo"
'''

AUTH_SERVICE_TESTS = '''import unittest

from app import authenticate, issue_token


class AuthTests(unittest.TestCase):
    def test_valid_login(self):
        self.assertTrue(authenticate("alice", "s3cret"))

    def test_empty_password_rejected(self):
        self.assertFalse(authenticate("alice", ""))

    def test_token_format(self):
        self.assertTrue(issue_token("bob").startswith("token-bob"))


if __name__ == "__main__":
    unittest.main()
'''

WEB_FRONTEND_YAML = """name: Web Frontend CI
on:
  push:
    branches: [main]

jobs:
  build:
    steps:
      - name: Show environment
        run: echo Building %CI_PIPELINE% for project %CI_PROJECT%

      - name: Verify assets
        run: dir src

      - name: Bundle
        run: echo Bundling static assets... && echo Bundle complete.
"""


def _rmtree_force(path):
    """shutil.rmtree that also clears read-only flags (git objects on Windows)."""
    def onerror(func, p, exc_info):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if os.path.exists(path):
        shutil.rmtree(path, onerror=onerror)


class Command(BaseCommand):
    help = 'Wipe all data and seed a complete demo environment (org, project, apps, repos, PRs, pipelines).'

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_true', help='Skip confirmation prompt')

    # ── helpers ───────────────────────────────────────────────────────────────

    def _git(self, cwd, *args, env=None):
        result = subprocess.run(['git', *args], cwd=cwd, env=env,
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def _seed_repo_files(self, repo_name, files, user, message):
        """Clone the bare repo into a temp dir, write files, commit, push back."""
        bare = os.path.join(REPO_BASE_PATH, f'{repo_name}.git')
        work = os.path.join(REPO_BASE_PATH, f'_seed_{repo_name}')
        _rmtree_force(work)

        env = os.environ.copy()
        env.update({
            'GIT_AUTHOR_NAME': user.username,
            'GIT_AUTHOR_EMAIL': f'{user.username}@acme.local',
            'GIT_COMMITTER_NAME': user.username,
            'GIT_COMMITTER_EMAIL': f'{user.username}@acme.local',
        })

        self._git(REPO_BASE_PATH, 'clone', bare, work, env=env)
        for rel_path, content in files.items():
            full = os.path.join(work, rel_path)
            os.makedirs(os.path.dirname(full) or work, exist_ok=True)
            with open(full, 'w', newline='\n') as fh:
                fh.write(content)
        self._git(work, 'add', '-A', env=env)
        self._git(work, 'commit', '-m', message, env=env)
        self._git(work, 'push', 'origin', 'main', env=env)
        sha = self._git(work, 'rev-parse', 'HEAD', env=env)
        _rmtree_force(work)
        return sha

    def _seed_branch(self, repo_name, branch, files, user, message):
        """Create a feature branch with extra commits and push it."""
        bare = os.path.join(REPO_BASE_PATH, f'{repo_name}.git')
        work = os.path.join(REPO_BASE_PATH, f'_seed_{repo_name}_branch')
        _rmtree_force(work)

        env = os.environ.copy()
        env.update({
            'GIT_AUTHOR_NAME': user.username,
            'GIT_AUTHOR_EMAIL': f'{user.username}@acme.local',
            'GIT_COMMITTER_NAME': user.username,
            'GIT_COMMITTER_EMAIL': f'{user.username}@acme.local',
        })

        self._git(REPO_BASE_PATH, 'clone', bare, work, env=env)
        self._git(work, 'checkout', '-b', branch, env=env)
        for rel_path, content in files.items():
            full = os.path.join(work, rel_path)
            os.makedirs(os.path.dirname(full) or work, exist_ok=True)
            with open(full, 'w', newline='\n') as fh:
                fh.write(content)
        self._git(work, 'add', '-A', env=env)
        self._git(work, 'commit', '-m', message, env=env)
        self._git(work, 'push', 'origin', branch, env=env)
        sha = self._git(work, 'rev-parse', 'HEAD', env=env)
        _rmtree_force(work)
        return sha

    # ── main ──────────────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        if not options['yes']:
            confirm = input(
                'This DELETES ALL data (users, repos on disk, projects, runs). '
                'Type "yes" to continue: ')
            if confirm.strip().lower() != 'yes':
                self.stdout.write(self.style.WARNING('Aborted.'))
                return

        from gitmgmt.views import _initialize_repository, _create_default_labels

        # ── 1. Wipe ───────────────────────────────────────────────────────────
        self.stdout.write('Wiping database…')
        for model in (PipelineRun, PipelineStep, YamlFileVersion, Build,
                      AgentCommand, Heartbeat, Agent, Credential, Pipeline,
                      Stage, Step, Tag, Environment, Application,
                      ProjectMember, Project, GlobalSettings):
            model.objects.all().delete()
        for model in (Reaction, PRReview, PullRequestComment, PullRequest,
                      IssueComment, Issue, Milestone, Label, Release,
                      Notification, ActivityEvent, Commit, Branch,
                      Collaborator, Repository, Team, OrganizationMember,
                      Organization, PersonalAccessToken, UserProfile):
            model.objects.all().delete()
        User.objects.all().delete()

        self.stdout.write('Wiping repositories on disk…')
        if os.path.isdir(REPO_BASE_PATH):
            for entry in os.listdir(REPO_BASE_PATH):
                _rmtree_force(os.path.join(REPO_BASE_PATH, entry))
        else:
            os.makedirs(REPO_BASE_PATH, exist_ok=True)

        # ── 2. Users ──────────────────────────────────────────────────────────
        self.stdout.write('Creating users…')
        admin = User.objects.create_superuser('admin', 'admin@acme.local', 'admin123')
        alice = User.objects.create_user('alice', 'alice@acme.local', 'alice123',
                                         first_name='Alice', last_name='Nguyen')
        bob = User.objects.create_user('bob', 'bob@acme.local', 'bob123',
                                       first_name='Bob', last_name='Martins')
        carol = User.objects.create_user('carol', 'carol@acme.local', 'carol123',
                                         first_name='Carol', last_name='Ito')

        # ── 3. Organization ───────────────────────────────────────────────────
        self.stdout.write('Creating organization acme-corp…')
        org = Organization.objects.create(
            name='acme-corp',
            description='Acme Corporation — engineering organization.',
            owner=admin,
            website='https://acme.example.com',
            default_repo_visibility='private',
            project_creation_policy='admin',
            onboarding_notes=(
                'Welcome to Acme!\n'
                '1. Create a Personal Access Token in your Profile.\n'
                '2. Clone the repo of the app you work on.\n'
                '3. All changes go through pull requests to main.'
            ),
        )
        OrganizationMember.objects.create(organization=org, user=admin, role='owner')
        OrganizationMember.objects.create(organization=org, user=alice, role='admin')
        OrganizationMember.objects.create(organization=org, user=bob, role='member')
        OrganizationMember.objects.create(organization=org, user=carol, role='member')

        backend = Team.objects.create(name='Backend', organization=org,
                                      description='Auth, APIs, data')
        frontend = Team.objects.create(name='Frontend', organization=org,
                                       description='Web UI')
        backend.members.add(alice, bob)
        frontend.members.add(carol)

        # ── 4. Project ────────────────────────────────────────────────────────
        self.stdout.write('Creating project acme-platform…')
        project = Project.objects.create(
            name='acme-platform',
            description='Core platform of Acme — auth and web frontend.',
            organization=org,
            environment_variables={
                'DEPLOY_ENV': 'staging',
                'API_BASE_URL': 'https://staging-api.acme.example.com',
                'LOG_LEVEL': 'debug',
            },
            notifications_enabled=True,
            notification_emails='dev-team@acme.local',
        )
        ProjectMember.objects.create(project=project, user=alice, role='maintainer')
        ProjectMember.objects.create(project=project, user=bob, role='developer')
        ProjectMember.objects.create(project=project, user=carol, role='viewer')

        Credential.objects.create(
            service_name='dockerhub', username='acme-ci',
            password='demo-not-real', token='demo-token',
            scope_level='project', project=project,
        )

        # ── 5. Applications + repos ───────────────────────────────────────────
        apps_spec = [
            ('auth-service', 'Authentication microservice', {
                'rockerci.yaml': AUTH_SERVICE_YAML,
                'app.py': AUTH_SERVICE_APP,
                'tests/test_auth.py': AUTH_SERVICE_TESTS,
                'tests/__init__.py': '',
                'README.md': '# auth-service\n\nAcme authentication microservice.\n',
            }),
            ('web-frontend', 'Customer-facing web UI', {
                'rockerci.yaml': WEB_FRONTEND_YAML,
                'src/index.html': '<!DOCTYPE html>\n<html><body><h1>Acme</h1></body></html>\n',
                'src/app.js': 'console.log("acme web");\n',
                'README.md': '# web-frontend\n\nAcme web UI.\n',
            }),
        ]

        repos = {}
        for app_name, desc, files in apps_spec:
            self.stdout.write(f'Creating application {app_name} + repository…')
            app = Application.objects.create(
                name=app_name, description=desc, project=project,
                default_branch='main',
            )
            _initialize_repository(app_name, user=admin)
            repo = Repository.objects.create(
                name=app_name, description=desc, owner=admin,
                organization=org, visibility='private',
                default_branch='main', application=app,
            )
            Branch.objects.create(repository=repo, name='main', is_default=True)
            _create_default_labels(repo)

            sha = self._seed_repo_files(app_name, files, alice,
                                        f'Add {app_name} sources and CI pipeline')
            Commit.objects.create(
                branch=repo.branches.get(name='main'),
                message=f'Add {app_name} sources and CI pipeline',
                author=alice, author_name='alice',
                author_email='alice@acme.local', hash=sha,
            )
            repos[app_name] = repo

            Pipeline.objects.create(
                name=f'{app_name}-ci',
                description=f'CI for {app_name}, triggered by pushes to main.',
                application=app,
                yaml_path='rockerci.yaml',
                monitored_branch='main',
            )

        # ── 6. Issues, milestone, PR on auth-service ──────────────────────────
        self.stdout.write('Creating issues, milestone, pull request…')
        auth_repo = repos['auth-service']
        milestone = Milestone.objects.create(
            repository=auth_repo, title='v1.0',
            description='First production release.',
            due_date=timezone.now().date() + timezone.timedelta(days=30),
            created_by=admin,
        )
        bug_label = auth_repo.labels.get(name='bug')
        enh_label = auth_repo.labels.get(name='enhancement')

        issue1 = Issue.objects.create(
            repository=auth_repo, title='Empty password should return 400, not 500',
            body='POST /login with an empty password crashes instead of rejecting cleanly.',
            author=bob, milestone=milestone,
        )
        issue1.labels.add(bug_label)
        issue1.assignees.add(alice)

        issue2 = Issue.objects.create(
            repository=auth_repo, title='Add token expiry',
            body='Issued tokens never expire. Add a configurable TTL.',
            author=alice, milestone=milestone,
        )
        issue2.labels.add(enh_label)
        IssueComment.objects.create(
            issue=issue1, author=alice,
            body='Reproduced. Fix incoming in the rate-limiting branch.')

        # Feature branch + PR
        feature_sha = self._seed_branch(
            'auth-service', 'feature/rate-limiting',
            {'ratelimit.py':
                '"""Simple fixed-window rate limiter."""\n\n'
                'WINDOW_SECONDS = 60\nMAX_ATTEMPTS = 5\n\n\n'
                'def allow(attempts_in_window):\n'
                '    return attempts_in_window < MAX_ATTEMPTS\n'},
            bob, 'Add fixed-window rate limiter for login attempts')
        feature_branch = Branch.objects.create(
            repository=auth_repo, name='feature/rate-limiting')
        Commit.objects.create(
            branch=feature_branch,
            message='Add fixed-window rate limiter for login attempts',
            author=bob, author_name='bob', author_email='bob@acme.local',
            hash=feature_sha,
        )

        pr = PullRequest.objects.create(
            repository=auth_repo,
            title='Add rate limiting to login endpoint',
            description=('Adds a fixed-window rate limiter (5 attempts/min).\n\n'
                         'Closes #1'),
            author=bob,
            source_branch=feature_branch,
            target_branch=auth_repo.branches.get(name='main'),
            milestone=milestone,
        )
        pr.reviewers.add(alice)
        pr.labels.add(enh_label)
        PullRequestComment.objects.create(
            pull_request=pr, author=alice,
            content='Looks reasonable — one question: should the window be configurable per-project?')
        PRReview.objects.create(
            pull_request=pr, reviewer=alice, state='approved',
            body='LGTM. Window size can be a follow-up.')

        # ── 7. Personal Access Token for git pushes ───────────────────────────
        raw_token = None
        if hasattr(PersonalAccessToken, 'create_token'):
            _, raw_token = PersonalAccessToken.create_token(admin, 'e2e-demo')
        else:
            import secrets as _secrets
            raw_token = _secrets.token_urlsafe(30)
            PersonalAccessToken.objects.create(
                user=admin, name='e2e-demo', prefix=raw_token[:8],
                token_hash=PersonalAccessToken.hash_token(raw_token))

        # ── 8. Summary ────────────────────────────────────────────────────────
        s = self.style.SUCCESS
        self.stdout.write(s('\n══════════════════════════════════════════════════'))
        self.stdout.write(s('  Demo environment ready'))
        self.stdout.write(s('══════════════════════════════════════════════════'))
        self.stdout.write('''
Users             admin / admin123   (superuser, org owner)
                  alice / alice123   (org admin, project maintainer)
                  bob   / bob123     (member, project developer)
                  carol / carol123   (member, project viewer)

Organization      acme-corp  (policies: private repos, admins create projects)
Project           acme-platform  (3 CI/CD variables, notifications on)
Applications      auth-service, web-frontend  (each with initialized Git repo)
Pipelines         auth-service-ci, web-frontend-ci  (monitor: main)
Pull request      #1 on auth-service (feature/rate-limiting → main, approved)
Issues            2 on auth-service, milestone v1.0
''')
        self.stdout.write(s(f'Git token (admin) — shown ONCE:\n\n    {raw_token}\n'))
        self.stdout.write('''Next steps for the end-to-end check:
  1. Register the agent:   python windows_agent.py --hash-key "win-agent-01"
     (in the UI: Agents → verify it appears live, or pre-register there)
  2. Clone:  git clone http://127.0.0.1:8001/git/admin/auth-service.git
     (username: admin, password: the token above)
  3. Commit anything to main and push.
  4. Watch CI Dashboard — a run of auth-service-ci should appear within ~10s.
''')
