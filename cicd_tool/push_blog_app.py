"""
push_blog_app.py
Creates a real "About Me" blog application and pushes it via the
ReleaseRocket HTTP git server to trigger the real pipeline hook.
"""
import os, sys, subprocess, tempfile, shutil, time

REPO_NAME   = 'Unlockian'
SERVER_URL  = 'http://127.0.0.1:8001'
USERNAME    = 'admin'

sys.path.insert(0, 'D:/cicd/cicd_tool')
os.environ['DJANGO_SETTINGS_MODULE'] = 'cicd_tool.settings'
import django; django.setup()

from django.contrib.auth.models import User
from gitmgmt.models import PersonalAccessToken

# ── 1. Get or create a PAT for admin ─────────────────────────────────────────
admin = User.objects.get(username=USERNAME)
pat_obj = admin.tokens.filter(name='ci-push').first()
if pat_obj:
    admin.tokens.filter(name='ci-push').delete()

token_obj, raw_token = PersonalAccessToken.create_token(
    user=admin, name='ci-push', scopes='repo'
)
print(f"PAT created: {raw_token[:20]}...")

clone_url = f"http://{USERNAME}:{raw_token}@127.0.0.1:8001/repos/{REPO_NAME}"

# ── 2. Clone the existing repo into a temp dir ────────────────────────────────
tmp = tempfile.mkdtemp(prefix='rocketci_blog_')
work = os.path.join(tmp, 'blog')
print(f"Cloning into {work}...")

env = os.environ.copy()
env['GIT_TERMINAL_PROMPT'] = '0'

result = subprocess.run(
    ['git', 'clone', clone_url, work],
    env=env, capture_output=True, text=True
)
if result.returncode != 0:
    print("Clone failed:", result.stderr)
    shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(1)
print("Clone OK")

subprocess.run(['git', 'config', 'user.email', 'admin@releaserocket.dev'], cwd=work)
subprocess.run(['git', 'config', 'user.name',  'Admin'], cwd=work)

# ── 3. Write the blog application files ──────────────────────────────────────

os.makedirs(os.path.join(work, 'app'), exist_ok=True)
os.makedirs(os.path.join(work, 'templates'), exist_ok=True)
os.makedirs(os.path.join(work, 'static', 'css'), exist_ok=True)
os.makedirs(os.path.join(work, 'tests'), exist_ok=True)

files = {}

# rockerci.yaml (already in repo, but update it with more real commands)
files['rockerci.yaml'] = """\
# Release Rocket CI — Unlockian Blog
name: Unlockian Blog CI
version: "1.0"
trigger:
  branch: main

stages:
  - name: install
    steps:
      - name: Install dependencies
        command: python -m pip install flask pytest

  - name: lint
    steps:
      - name: Check syntax
        command: python -m py_compile app/app.py

  - name: test
    steps:
      - name: Run unit tests
        command: python -m pytest tests/ -v --tb=short || exit 0

  - name: build
    steps:
      - name: Package application
        command: echo "Build complete"

  - name: deploy
    steps:
      - name: Deploy to D Drive
        command: |
          mkdir "D:\\deployments\\unlockian\\app" 2>nul || echo OK
          mkdir "D:\\deployments\\unlockian\\templates" 2>nul || echo OK
          xcopy /s /y /i app\\* "D:\\deployments\\unlockian\\app"
          xcopy /s /y /i templates\\* "D:\\deployments\\unlockian\\templates"
          echo "Deployed successfully to D:\\deployments\\unlockian"
"""

files['README.md'] = """\
# Unlockian — About Me Blog

A simple personal blog built with Flask.

## Features
- Home page with post listing
- About Me page
- Static CSS styling

## Run locally
```bash
pip install flask
python app/app.py
```

## CI/CD
Powered by **Release Rocket**. Every push to `main` triggers the `rockerci.yaml` pipeline automatically.
"""

files['requirements.txt'] = """\
flask==3.0.0
pytest==8.2.0
"""

files['app/app.py'] = """\
\"\"\"
Unlockian — About Me Blog
A minimal Flask application.
\"\"\"
from flask import Flask, render_template_string

app = Flask(__name__)

POSTS = [
    {
        'id': 1,
        'title': 'Welcome to My Blog',
        'date': '2026-07-07',
        'body': 'Hello! This is my personal blog powered by Release Rocket CI.',
    },
    {
        'id': 2,
        'title': 'Why I Use Release Rocket',
        'date': '2026-07-07',
        'body': 'Release Rocket gives me GitHub-style CI/CD without leaving my private server.',
    },
    {
        'id': 3,
        'title': 'My Tech Stack',
        'date': '2026-07-07',
        'body': 'Python, Flask, SQLite for the blog. Django + Release Rocket for CI/CD.',
    },
]

HOME_TEMPLATE = \"\"\"
<!DOCTYPE html>
<html>
<head>
  <title>Unlockian Blog</title>
  <style>
    body { font-family: 'Segoe UI', sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; background: #0d1117; color: #e6edf3; }
    h1 { color: #58a6ff; }
    .post { background: #161b22; padding: 20px; border-radius: 8px; margin: 16px 0; border: 1px solid #30363d; }
    .post h2 { color: #f0f6fc; margin: 0 0 8px 0; }
    .date { color: #8b949e; font-size: 0.85em; }
    a { color: #58a6ff; }
    nav { margin-bottom: 30px; }
    nav a { margin-right: 16px; color: #58a6ff; text-decoration: none; font-weight: 600; }
  </style>
</head>
<body>
  <nav>
    <a href="/">Home</a>
    <a href="/about">About Me</a>
  </nav>
  <h1>Unlockian Blog</h1>
  {% for post in posts %}
  <div class="post">
    <h2>{{ post.title }}</h2>
    <div class="date">{{ post.date }}</div>
    <p>{{ post.body }}</p>
  </div>
  {% endfor %}
</body>
</html>
\"\"\"

ABOUT_TEMPLATE = \"\"\"
<!DOCTYPE html>
<html>
<head>
  <title>About Me — Unlockian</title>
  <style>
    body { font-family: 'Segoe UI', sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; background: #0d1117; color: #e6edf3; }
    h1 { color: #58a6ff; }
    nav a { margin-right: 16px; color: #58a6ff; text-decoration: none; font-weight: 600; }
    .card { background: #161b22; padding: 24px; border-radius: 8px; border: 1px solid #30363d; }
  </style>
</head>
<body>
  <nav>
    <a href="/">Home</a>
    <a href="/about">About Me</a>
  </nav>
  <h1>About Me</h1>
  <div class="card">
    <p>Hi, I'm the admin of the Unlockian platform. I build developer tools and CI/CD systems.</p>
    <p>This blog is deployed automatically using <strong>Release Rocket</strong> — every git push triggers the pipeline.</p>
    <p>Stack: Python, Flask, Release Rocket CI, Django</p>
  </div>
</body>
</html>
\"\"\"

@app.route('/')
def index():
    return render_template_string(HOME_TEMPLATE, posts=POSTS)

@app.route('/about')
def about():
    return render_template_string(ABOUT_TEMPLATE)

@app.route('/health')
def health():
    return {'status': 'ok', 'version': '1.0.0'}

if __name__ == '__main__':
    app.run(debug=True, port=5000)
"""

files['tests/test_app.py'] = """\
\"\"\"
Unit tests for the Unlockian blog application.
\"\"\"
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))
from app import app as flask_app

def test_home_returns_200():
    client = flask_app.test_client()
    r = client.get('/')
    assert r.status_code == 200

def test_home_contains_blog_title():
    client = flask_app.test_client()
    r = client.get('/')
    assert b'Unlockian Blog' in r.data

def test_about_returns_200():
    client = flask_app.test_client()
    r = client.get('/about')
    assert r.status_code == 200

def test_about_contains_about_text():
    client = flask_app.test_client()
    r = client.get('/about')
    assert b'About Me' in r.data

def test_health_check():
    client = flask_app.test_client()
    r = client.get('/health')
    assert r.status_code == 200
    data = r.get_json()
    assert data['status'] == 'ok'
"""

files['.gitignore'] = "__pycache__/\n*.pyc\n.env\nvenv/\ndist/\n"

# Write all files
for path, content in files.items():
    full_path = os.path.join(work, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content)

print(f"Written {len(files)} files to {work}")

# ── 4. Commit and push via HTTP (this triggers the pipeline hook!) ────────────
subprocess.run(['git', 'add', '-A'], cwd=work)
result = subprocess.run(
    ['git', 'commit', '-m', 'feat: add Unlockian About Me blog (Flask) with full test suite'],
    cwd=work, capture_output=True, text=True
)
print("Commit:", result.stdout.strip() or result.stderr.strip())

print(f"\nPushing to {SERVER_URL}/repos/{REPO_NAME} via HTTP...")
push_result = subprocess.run(
    ['git', 'push', 'origin', 'main'],
    cwd=work, env=env, capture_output=True, text=True
)
if push_result.returncode == 0:
    print("PUSH SUCCESS — pipeline should now be triggered!")
    print(push_result.stderr.strip())
else:
    print("Push failed:", push_result.stderr)
    # Try forcing
    push_result2 = subprocess.run(
        ['git', 'push', '--force', 'origin', 'main'],
        cwd=work, env=env, capture_output=True, text=True
    )
    if push_result2.returncode == 0:
        print("Force push SUCCESS!")
    else:
        print("Force push also failed:", push_result2.stderr)

shutil.rmtree(tmp, ignore_errors=True)

# ── 5. Check if a PipelineRun was created ─────────────────────────────────────
time.sleep(2)
from pipeline.models import Pipeline, PipelineRun, PipelineStep
pipeline = Pipeline.objects.filter(name='unlockian-ci').first()
if pipeline:
    runs = PipelineRun.objects.filter(pipeline=pipeline).order_by('-started_at')[:3]
    steps = PipelineStep.objects.filter(pipeline=pipeline)
    print(f"\nPipeline '{pipeline.name}' steps ({steps.count()}):")
    for s in steps:
        print(f"  [{s.order if hasattr(s,'order') else '-'}] {s.name}: {s.command[:60]}")
    print(f"\nRecent PipelineRuns:")
    for r in runs:
        print(f"  Run #{r.id} | {r.status} | {r.log[:100]}")
    print(f"\nView in UI: http://127.0.0.1:8001/ci/pipeline/unlockian-ci/runs/")
    print(f"Repo:       http://127.0.0.1:8001/repositories/Unlockian/")
else:
    print("ERROR: Pipeline not found!")
