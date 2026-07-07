"""
setup_unlockian_test.py
Sets up:
1. Unlockian test data (pipeline, application, credentials)
2. Creates rockerci.yaml in the repo
3. Tests the full push -> pipeline trigger flow
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, 'D:/cicd/cicd_tool')
os.environ['DJANGO_SETTINGS_MODULE'] = 'cicd_tool.settings'

import django
django.setup()

from django.contrib.auth.models import User
from gitmgmt.models import Organization, Repository, UserProfile
from pipeline.models import Project, Application, Pipeline, PipelineRun, Environment

REPO_BASE = 'D:/repos'
REPO_NAME = 'Unlockian'

def run():
    print("=" * 60)
    print("Setting up Unlockian end-to-end test environment")
    print("=" * 60)

    # ── 1. Ensure admin user exists ─────────────────────────────
    admin = User.objects.filter(username='admin').first()
    if not admin:
        print("ERROR: admin user not found. Run setup_test_data.py first.")
        return

    # ── 2. Get or create Organization ───────────────────────────
    org, _ = Organization.objects.get_or_create(
        name='Unlockian',
        defaults={'owner': admin, 'description': 'Unlockian test organization'}
    )
    print(f"Organization: {org.name}")

    # ── 3. Get or create Project ─────────────────────────────────
    project, _ = Project.objects.get_or_create(
        name='Unlockian',
        defaults={'organization': org}
    )
    print(f"Project: {project.name}")

    # ── 4. Get or create Repository in gitmgmt ───────────────────
    repo_qs = Repository.objects.filter(name=REPO_NAME)
    if repo_qs.exists():
        repo = repo_qs.first()
        print(f"Repository: {repo.name} (existing)")
    else:
        repo = Repository.objects.create(
            name=REPO_NAME,
            owner=admin,
            description='Unlockian test repository',
            visibility='private',
        )
        # Init bare git repo on disk
        repo_path = os.path.join(REPO_BASE, f"{REPO_NAME}.git")
        if not os.path.exists(repo_path):
            os.makedirs(repo_path, exist_ok=True)
            subprocess.run(['git', 'init', '--bare', repo_path], check=True)
            print(f"  Initialized bare repo at {repo_path}")
        print(f"Repository: {repo.name} (created)")

    # ── 5. Get or create Application ─────────────────────────────
    app, _ = Application.objects.get_or_create(
        name='unlockian-app',
        defaults={'project': project}
    )
    # Link the repo to the application
    if not hasattr(repo, 'application') or repo.application_id != app.id:
        repo.application = app
        repo.save()
    print(f"Application: {app.name} linked to repo")

    # ── 6. Create Environment ─────────────────────────────────────
    env, _ = Environment.objects.get_or_create(name='dev', defaults={'description': 'Development'})

    # ── 7. Create Pipeline ────────────────────────────────────────
    pipeline, created = Pipeline.objects.get_or_create(
        name='unlockian-ci',
        defaults={
            'application': app,
            'monitored_branch': 'main',
            'yaml_path': 'rockerci.yaml',
        }
    )
    if not created:
        # Ensure fields are set
        pipeline.monitored_branch = 'main'
        pipeline.yaml_path = 'rockerci.yaml'
        pipeline.save()
    print(f"Pipeline: {pipeline.name} (monitored_branch=main, yaml_path=rockerci.yaml)")

    # ── 8. Push test data + rockerci.yaml into repo ───────────────
    repo_path = os.path.join(REPO_BASE, f"{REPO_NAME}.git")
    with tempfile.TemporaryDirectory() as tmp:
        print(f"\nCloning bare repo into temp dir for push test...")
        clone_url = repo_path  # local path clone
        subprocess.run(['git', 'clone', clone_url, tmp + '/work'], check=True, capture_output=True)
        work = tmp + '/work'

        # Configure git identity for the push
        subprocess.run(['git', 'config', 'user.email', 'ci@releaserocket.dev'], cwd=work, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Release Rocket CI'], cwd=work, capture_output=True)

        # Write rockerci.yaml
        yaml_content = """# Release Rocket CI - Unlockian
name: Unlockian CI Pipeline
version: "1.0"
trigger:
  branch: main

stages:
  - name: build
    steps:
      - name: Install dependencies
        command: echo "Installing dependencies..."
      - name: Build
        command: echo "Building Unlockian..."

  - name: test
    steps:
      - name: Run unit tests
        command: echo "Running tests... OK"
      - name: Lint check
        command: echo "Lint check passed"

  - name: deploy
    steps:
      - name: Deploy to dev
        command: echo "Deploying to dev environment..."
"""
        with open(os.path.join(work, 'rockerci.yaml'), 'w') as f:
            f.write(yaml_content)

        # Write some random app code
        with open(os.path.join(work, 'README.md'), 'w') as f:
            f.write("""# Unlockian

This is the main Unlockian application repository.

## Setup
```
pip install -r requirements.txt
python manage.py runserver
```

## CI/CD
This repository uses Release Rocket CI. On every push to `main`, the `rockerci.yaml` pipeline is triggered.
""")

        with open(os.path.join(work, 'main.py'), 'w') as f:
            f.write("""#!/usr/bin/env python3
\"\"\"Unlockian main entry point.\"\"\"
import datetime

def main():
    print(f"Unlockian started at {datetime.datetime.now()}")
    print("Hello from Release Rocket CI!")

if __name__ == '__main__':
    main()
""")

        # Stage and commit
        subprocess.run(['git', 'add', '.'], cwd=work, check=True)
        subprocess.run(['git', 'commit', '-m', 'feat: initial Unlockian codebase with rockerci.yaml'], cwd=work, check=True, capture_output=True)

        # Push to bare repo
        result = subprocess.run(['git', 'push', 'origin', 'main'], cwd=work, capture_output=True, text=True)
        if result.returncode == 0:
            print("Push successful!")
        else:
            # Try pushing to master or force-setting main branch
            result2 = subprocess.run(['git', 'push', 'origin', 'HEAD:main'], cwd=work, capture_output=True, text=True)
            if result2.returncode == 0:
                print("Push successful (HEAD:main)!")
            else:
                print(f"Push stderr: {result.stderr}")
                print(f"Push2 stderr: {result2.stderr}")

    # ── 9. Manually trigger the pipeline to verify ────────────────
    print("\nManually simulating pipeline trigger (as if git push happened)...")
    from git import Repo as GitRepo
    try:
        git_repo = GitRepo(repo_path)
        for head in git_repo.heads:
            if head.name == 'main':
                tree = head.commit.tree
                if 'rockerci.yaml' in [item.path for item in tree]:
                    yaml_bytes = tree['rockerci.yaml'].data_stream.read()
                    yaml_str = yaml_bytes.decode('utf-8')
                    from pipeline.models import YamlFileVersion
                    from pipeline.utils import sync_steps_from_yaml
                    version = YamlFileVersion.objects.filter(pipeline=pipeline).count() + 1
                    YamlFileVersion.objects.create(
                        pipeline=pipeline, version_number=version, yaml_content=yaml_str
                    )
                    n_steps = sync_steps_from_yaml(pipeline, yaml_str)
                    commit = head.commit
                    run_obj = PipelineRun.objects.create(
                        pipeline=pipeline,
                        status='pending',
                        log=f'Triggered via test push on main (commit {commit.hexsha[:10]}, {n_steps} steps)'
                    )
                    print(f"SUCCESS: PipelineRun #{run_obj.id} created (status=pending, {n_steps} steps)")
                else:
                    print("WARNING: rockerci.yaml not found in main branch tree yet")
    except Exception as e:
        print(f"Pipeline trigger simulation error: {e}")
        import traceback; traceback.print_exc()

    # ── 10. Print summary ─────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Repository : {REPO_NAME}")
    print(f"  Application: {app.name}")
    print(f"  Pipeline   : {pipeline.name}")
    runs = PipelineRun.objects.filter(pipeline=pipeline).order_by('-started_at')[:3]
    for r in runs:
        print(f"  Run #{r.id}: {r.status} — {r.log[:80]}")

    print(f"\nTo verify in the UI:")
    print(f"  http://127.0.0.1:8001/repositories/{REPO_NAME}/")
    print(f"  http://127.0.0.1:8001/ci/pipeline/unlockian-ci/runs/")
    print("=" * 60)

if __name__ == '__main__':
    run()
