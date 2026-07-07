# ReleaseRocket — Developer Guide

> **Audience:** Backend engineers, DevOps engineers, and contributors working on or deploying ReleaseRocket.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Project Structure](#2-project-structure)
3. [Local Development Setup](#3-local-development-setup)
4. [Environment Variables](#4-environment-variables)
5. [Data Models](#5-data-models)
6. [URL & View Reference](#6-url--view-reference)
7. [Authentication & Security](#7-authentication--security)
8. [CI/CD Pipeline Engine](#8-cicd-pipeline-engine)
9. [Git Smart HTTP Protocol](#9-git-smart-http-protocol)
10. [Background Worker](#10-background-worker)
11. [Build Agent (linux_agent.py)](#11-build-agent-linux_agentpy)
12. [Database Migrations](#12-database-migrations)
13. [Production Deployment](#13-production-deployment)
14. [Contributing](#14-contributing)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         Browser                             │
│              Web UI · git push/pull · SSE logs              │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP / WebSocket
┌──────────────────────▼──────────────────────────────────────┐
│                   Django Application                        │
│  ┌─────────────────────┐  ┌──────────────────────────────┐  │
│  │      gitmgmt        │  │          pipeline            │  │
│  │  Git hosting, PRs,  │  │  Projects, pipelines, runs,  │  │
│  │  Issues, Reviews,   │  │  agents, metrics, SSE logs   │  │
│  │  Releases, Activity │  │  Background worker thread    │  │
│  └─────────────────────┘  └──────────────────────────────┘  │
└──────────┬──────────────────────────────┬───────────────────┘
           │                              │ HMAC-signed HTTP
┌──────────▼──────────┐       ┌───────────▼──────────────────┐
│   Storage Layer      │       │        Build Agents          │
│  SQLite/PostgreSQL   │       │   linux_agent.py             │
│  Bare git repos      │       │   (any Linux machine)        │
│  Media files         │       │   Executes shell steps       │
└──────────────────────┘       └──────────────────────────────┘
```

### Two Django Apps

| App | Responsibility |
|---|---|
| `gitmgmt` | Repository hosting, branches, commits, PRs, reviews, issues, labels, milestones, reactions, releases, notifications, activity, forking, search |
| `pipeline` | Projects, applications, pipelines, pipeline runs, steps, agents, credentials, global settings, dashboard, SSE streaming |

Both apps share the Django auth system and the `pipeline/base.html` dark-theme layout.

---

## 2. Project Structure

```
cicd_tool/                    ← Django project root
├── cicd_tool/
│   ├── settings.py           ← All configuration (reads from env vars)
│   ├── urls.py               ← Root URL dispatcher
│   └── wsgi.py
│
├── gitmgmt/                  ← Git hosting app
│   ├── models.py             ← 20+ models
│   ├── views.py              ← ~60 view functions
│   ├── urls.py               ← /repositories/*, /git/*, /search/, etc.
│   ├── forms.py
│   ├── admin.py
│   └── migrations/
│       ├── 0001_initial.py
│       ├── 0002_new_models.py   ← All GitHub-level models added
│       └── 0003_merge.py        ← Merge migration (resolves conflict)
│
├── pipeline/                 ← CI/CD app
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   ├── utils.py              ← execute_step(), prepare_credentials()
│   ├── worker.py             ← Background polling daemon thread
│   ├── apps.py               ← Starts worker in ready()
│   ├── admin.py
│   └── templates/pipeline/
│
├── templates/                ← Shared templates (if any global ones)
├── docs/
│   ├── USER_GUIDE.md         ← End-user documentation
│   └── DEVELOPER.md          ← This file
├── linux_agent.py            ← Standalone build agent
└── manage.py
```

---

## 3. Local Development Setup

```bash
# Clone and enter project
git clone <url> releaserocket
cd releaserocket/cicd_tool

# Create virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install dependencies
pip install django gitpython pillow

# Minimum environment variables
export DJANGO_SECRET_KEY="dev-only-change-in-production-$(python -c 'import secrets; print(secrets.token_hex(20))')"
export REPO_BASE_PATH="/tmp/releaserocket/repos"
export CI_RUNS_DIR="/tmp/releaserocket/ci-runs"
mkdir -p $REPO_BASE_PATH $CI_RUNS_DIR

# Apply migrations
python manage.py migrate

# Create admin user
python manage.py createsuperuser

# Start dev server
python manage.py runserver 0.0.0.0:8001
```

Visit `http://localhost:8001`. The admin panel is at `http://localhost:8001/admin/`.

---

## 4. Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DJANGO_SECRET_KEY` | ✅ Yes | — | Django cryptographic secret. Generate: `python -c "import secrets; print(secrets.token_hex(50))"` |
| `REPO_BASE_PATH` | ✅ Yes | `/repos` | Filesystem path where bare git repositories are stored |
| `CI_RUNS_DIR` | ✅ Yes | `/tmp/ci-runs` | Working directory for pipeline execution |
| `DEBUG` | No | `True` | Set `False` in production |
| `ALLOWED_HOSTS` | Prod | `*` | Comma-separated hostnames |
| `DATABASE_URL` | No | SQLite | PostgreSQL: `postgres://user:pass@host:5432/dbname` |
| `MEDIA_ROOT` | No | `BASE_DIR/media` | Path for uploaded media files |
| `MEDIA_URL` | No | `/media/` | URL prefix for media files |

---

## 5. Data Models

### gitmgmt Models

#### Repository
```python
name            CharField           # unique, slug-like
description     TextField           # optional
visibility      CharField           # 'public' | 'private'
owner           ForeignKey(User)
organization    ForeignKey(Org)     # nullable
default_branch  CharField           # default: 'main'
stars           ManyToManyField(User)
watchers        ManyToManyField(User)
forked_from     ForeignKey(self)    # nullable, for forks
is_fork         BooleanField

# Properties (no DB column):
star_count, fork_count, open_issues_count, open_pr_count
```

#### PersonalAccessToken
```python
user            ForeignKey(User)
name            CharField
prefix          CharField(8)        # first 8 chars of raw token — shown in UI
token_hash      CharField(64)       # SHA-256 of full raw token — ONLY this is stored
scopes          CharField           # default 'repo'
expires_at      DateTimeField       # nullable = never expires
created_at      DateTimeField

# Class methods:
PersonalAccessToken.hash_token(raw)          # → SHA-256 hex string
PersonalAccessToken.create_token(user, name) # → (instance, raw_token)
instance.verify(raw_token)                   # → bool
```

#### PullRequest
```python
repository      ForeignKey(Repository)
number          PositiveIntegerField    # sequential per repo (like GitHub)
title, description
source_branch, target_branch  → Branch
author          ForeignKey(User)
status          CharField              # 'open' | 'merged' | 'closed'
is_draft        BooleanField
merge_commit_sha CharField
assignees       ManyToManyField(User)
reviewers       ManyToManyField(User)
labels          ManyToManyField(Label)
milestone       ForeignKey(Milestone)

# Method:
pr.can_merge(user)  # enforces BranchProtectionRule required_approvals
```

#### Issue
```python
repository      ForeignKey(Repository)
number          PositiveIntegerField    # sequential per repo
title, body
state           CharField              # 'open' | 'closed'
author          ForeignKey(User)
assignees       ManyToManyField(User)
labels          ManyToManyField(Label)
milestone       ForeignKey(Milestone)
closed_at       DateTimeField          # nullable
closed_by       ForeignKey(User)       # nullable
```

#### Other gitmgmt Models

| Model | Purpose |
|---|---|
| `Branch` | Branch record per repo; OneToOne `BranchProtectionRule` |
| `Commit` | Stores commit sha, message, author_name, author_email |
| `IssueComment` | Comments on issues |
| `PRReview` | Approved / changes_requested / commented / dismissed |
| `PRReviewComment` | Inline diff comment with file_path, line_number, diff_hunk |
| `Label` | Repo-scoped labels with name + hex color |
| `Milestone` | Grouping for issues/PRs with due_date; `progress_pct` property |
| `BranchProtectionRule` | Per-branch rules enforced at merge time |
| `Reaction` | Emoji reactions on Issues, IssueComments, PRReviewComments |
| `Release` | Git tag + release notes; supports prerelease/draft |
| `ActivityEvent` | Immutable event log per user+repo |
| `Notification` | Per-user notifications with `is_read` flag |
| `Organization` | Groups users and repositories |
| `Team` | Sub-groups within an Organization |

#### Module-level helpers (gitmgmt/models.py)
```python
log_activity(user, repository, event_type, description, metadata={})
notify(user, repository, notification_type, title, content, link='')
```

---

### pipeline Models

| Model | Key Fields | Notes |
|---|---|---|
| `Project` | name, organization FK, repository_url, notifications_enabled, environment_variables (JSONField), notification_emails, slack_webhook_url | Top-level grouping |
| `Application` | name, project FK | Groups pipelines; each app = one deployable service |
| `Pipeline` | name, description, yaml_path, monitored_branch, application FK | Reads rockerci.yaml |
| `PipelineRun` | run_id (UUID), status, pipeline FK, agent FK, started_at, finished_at, log | status: pending/running/success/failed/cancelled |
| `PipelineStep` | name, status, log, started_at, finished_at, run FK | One record per yaml step |
| `Agent` | hostname, ip_address, port, hash_key, live, is_busy, scope_level, last_heartbeat | scope_level: 'global' \| 'project' |
| `Credential` | service_name, username, password, token, scope_level, project FK | scope: 'global' \| 'local' |
| `GlobalSettings` | key, value | Key-value store for system config |

---

## 6. URL & View Reference

### gitmgmt URLs (`/repositories/` prefix)

```
GET  /repositories/                           repository_list
POST /repositories/create/                    create_repository
GET  /repositories/<name>/                    repository_detail
GET  /repositories/<name>/tree/<branch>/      file_tree (with path)
GET  /repositories/<name>/blob/<branch>/<path> view_file
POST /repositories/<name>/edit/<path>/        edit_and_save_file (JSON API)
POST /repositories/<name>/upload/             upload_file
POST /repositories/<name>/fork/               fork_repository
POST /repositories/<name>/star/               toggle_star
POST /repositories/<name>/watch/              toggle_watch

GET  /repositories/<name>/pulls/              pull_request_list
POST /repositories/<name>/pulls/create/       create_pull_request
GET  /repositories/<name>/pulls/<id>/         pull_request_detail
POST /repositories/<name>/pulls/<id>/merge/   merge_pull_request
POST /repositories/<name>/pulls/<id>/close/   close_pull_request
POST /repositories/<name>/pulls/<id>/reopen/  reopen_pull_request
POST /repositories/<name>/pulls/<id>/review/  submit_pr_review
POST /repositories/<name>/pulls/<id>/inline-comment/ add_inline_comment

GET  /repositories/<name>/issues/             repository_issues
POST /repositories/<name>/issues/create/      create_issue
GET  /repositories/<name>/issues/<number>/    issue_detail
POST /repositories/<name>/issues/<number>/edit/ edit_issue

GET  /repositories/<name>/releases/           release_list
POST /repositories/<name>/releases/create/    create_release

GET  /repositories/<name>/settings/           repository_settings
POST /repositories/<name>/collaborators/add/  add_collaborator
POST /repositories/<name>/branches/<b>/delete/ delete_branch
GET  /repositories/<name>/branches/<b>/protection/ branch_protection

GET  /notifications/                          notification_list
GET  /notifications/count/                    notification_count  (JSON)
POST /notifications/<id>/read/                mark_notification_read
GET  /activity/                               activity_feed
GET  /repositories/<name>/activity/           repository_activity
POST /reactions/toggle/                       toggle_reaction  (JSON)
GET  /search/                                 global_search
GET  /profile/                                user_profile_view

# Git Smart HTTP
GET  /git/<owner>/<repo>.git/info/refs        GitService (upload-pack / receive-pack)
POST /git/<owner>/<repo>.git/git-upload-pack  GitService
POST /git/<owner>/<repo>.git/git-receive-pack GitService
```

### pipeline URLs (`/ci/` prefix)

```
GET  /ci/dashboard/                           DashboardView
GET  /ci/projects/                            project_list
POST /ci/projects/create/                     project_create
GET  /ci/projects/<name>/                     project_detail
GET  /ci/projects/<name>/configure/           configure_project
POST /ci/projects/<name>/trigger-build/       trigger_build  (async thread)
GET  /ci/projects/<name>/history/             build_history
GET  /ci/projects/<name>/applications/create/ create_application

GET  /ci/applications/                        application_list  (?project= filter)
GET  /ci/applications/<name>/                 application_detail
GET  /ci/pipelines/<name>/                    pipeline_detail

GET  /ci/runs/<run_id>/stream/                pipeline_log_stream  (SSE)
POST /ci/runs/<run_id>/cancel/                cancel_pipeline_run
GET  /ci/runs/                                pipeline_run_list
GET  /ci/metrics/                             pipeline_metrics_api  (JSON)

GET  /ci/agents/                              agent_list
GET  /ci/global-credentials/                  global_credential_list
GET  /ci/global-settings/                     global_settings
```

---

## 7. Authentication & Security

### Session Authentication (Web UI)

All views require `@login_required`. CSRF middleware is enabled for all POST endpoints. The session cookie is `HttpOnly`.

### Personal Access Token Authentication (Git + API)

Git pushes use HTTP Basic Auth. The `GitService` view authenticates as follows:

```python
# pipeline/views.py — simplified
def _authenticate(self, request, repository):
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    encoded = auth_header[6:]                              # strip 'Basic '
    username, raw_token = base64.b64decode(encoded).decode().split(':', 1)
    token_hash = PersonalAccessToken.hash_token(raw_token)
    token = PersonalAccessToken.objects.filter(
        user__username=username,
        token_hash=token_hash,
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now())
    ).first()
    return token is not None
```

**Key points:**
- Tokens are SHA-256 hashed before storage — the raw token is never persisted
- `token_hash` has a `unique=True` constraint — no duplicates
- Expiry is enforced at authentication time
- The `prefix` field (first 8 chars) is stored in plaintext for display in the UI only

### Branch Protection

`BranchProtectionRule` is checked in `PullRequest.can_merge(user)`:

```python
def can_merge(self, user):
    if self.is_draft:
        return False, "Cannot merge a draft PR"
    rule = getattr(self.target_branch, 'protection_rule', None)
    if rule and rule.require_pull_request:
        approvals = self.reviews.filter(state='approved').count()
        if approvals < rule.required_approvals:
            return False, f"Needs {rule.required_approvals} approvals, has {approvals}"
    return True, "OK"
```

### Agent Security

Each `Agent` has a `hash_key`. The pipeline worker signs all HTTP requests to agents with HMAC-SHA256. Agents can optionally run with TLS by passing `--ssl-cert` and `--ssl-key` to `linux_agent.py`.

---

## 8. CI/CD Pipeline Engine

### Execution Flow

```
User clicks "Trigger Build"
    │
    ▼
PipelineRun created (status='pending')
    │
    ▼ (within 10 seconds)
pipeline/worker.py daemon polls DB
    │
    ├─ Finds available Agent (live=True, is_busy=False)
    │
    ▼
Agent marked is_busy=True
New thread spawned → _execute_run(run_pk, agent_pk)
    │
    ▼
For each step in rockerci.yaml:
    execute_step(step, agent, run_dir, env_vars)
        │── Sends POST to agent's HTTP server
        │── Streams stdout back line by line
        └── Writes to PipelineStep.log
    │
    ▼
PipelineRun.status = 'success' | 'failed'
Agent.is_busy = False
Notifications dispatched (if enabled)
```

### rockerci.yaml Schema

```yaml
name: string              # Display name
on:
  push:
    branches: [list]      # Trigger on push to these branches

jobs:
  <job-name>:
    steps:
      - name: string      # Step display name
        run: string       # Shell command to execute
```

### Injected Environment Variables

Every step receives these automatically:

| Variable | Value |
|---|---|
| `CI_COMMIT_SHA` | Full git commit hash |
| `CI_BRANCH` | Branch that triggered the run |
| `CI_PROJECT` | Project name |
| `CI_PIPELINE` | Pipeline name |
| `CI_RUN_ID` | UUID of this PipelineRun |
| `CI` | `true` |

Plus all key-value pairs from **Project Settings → CI/CD Variables** and any injected credentials.

---

## 9. Git Smart HTTP Protocol

The `GitService` class-based view in `gitmgmt/views.py` implements the full Git Smart HTTP transfer protocol (RFC-compliant), supporting:

- `git clone` → info/refs + upload-pack
- `git fetch` → info/refs + upload-pack  
- `git push` → info/refs + receive-pack

Repositories are stored as **bare git repos** on disk at `REPO_BASE_PATH/<owner>/<repo-name>.git`.

On a successful push the view:
1. Calls `git receive-pack` via `subprocess`
2. Reads the new HEAD commit and updates `Branch` / `Commit` records in the DB
3. Creates an `ActivityEvent` for the push
4. Triggers any `Pipeline` whose `monitored_branch` matches the pushed ref

---

## 10. Background Worker

`pipeline/worker.py` runs as a daemon thread started in `PipelineConfig.ready()`:

```python
# pipeline/apps.py
class PipelineConfig(AppConfig):
    def ready(self):
        import threading
        from .worker import start_pipeline_worker
        t = threading.Thread(target=start_pipeline_worker, daemon=True, name='pipeline-worker')
        t.start()
```

The worker loop:

```python
def start_pipeline_worker():
    while True:
        _dispatch_pending()
        time.sleep(10)

def _dispatch_pending():
    pending = PipelineRun.objects.filter(status='pending').select_related('pipeline__application__project')
    for run in pending:
        agent = get_available_agent()
        if not agent:
            break
        agent.is_busy = True
        agent.save()
        run.status = 'running'
        run.save()
        t = threading.Thread(target=_execute_run, args=(run.pk, agent.pk), daemon=True)
        t.start()
```

**Note:** In production with multiple Gunicorn workers, the daemon thread starts in each worker process. Use a process-level lock or external queue (Celery, Redis) if you need exactly-once dispatch.

---

## 11. Build Agent (linux_agent.py)

A lightweight standalone Python HTTP server that runs on any Linux build machine.

### Starting an Agent

```bash
python linux_agent.py \
  --server http://releaserocket-host:8001 \
  --port 9000 \
  --hash-key "your-secret-hmac-key"

# With TLS
python linux_agent.py \
  --port 9443 \
  --hash-key "secret" \
  --ssl-cert /etc/ssl/agent.crt \
  --ssl-key /etc/ssl/agent.key
```

### How It Works

1. On startup, the agent sends a heartbeat POST to the ReleaseRocket server to register itself.
2. A daemon thread sends heartbeats every 30 seconds to keep `Agent.live = True`.
3. The main thread runs `HTTPServer.serve_forever()` to accept job commands.
4. When the server sends a job, the agent runs it via `subprocess.run(cmd, shell=True, timeout=300)` and streams stdout back.

### Registering in the UI

After starting the agent, register it at **Dashboard → Agents → Add Agent** with the same host, port, and hash key.

---

## 12. Database Migrations

```bash
# Create migrations after model changes
python manage.py makemigrations gitmgmt
python manage.py makemigrations pipeline

# Apply migrations
python manage.py migrate

# If you see "conflicting migrations" (multiple leaf nodes)
python manage.py makemigrations --merge
python manage.py migrate
```

### Migration Files

| File | Description |
|---|---|
| `gitmgmt/0001_initial.py` | Base models from original project |
| `gitmgmt/0002_new_models.py` | All GitHub/GitLab-level additions |
| `gitmgmt/0003_merge.py` | Merge migration resolving graph conflict |

---

## 13. Production Deployment

### Recommended Stack

| Component | Choice |
|---|---|
| WSGI server | Gunicorn |
| Reverse proxy | Nginx or Caddy |
| Database | PostgreSQL 15+ |
| Process manager | systemd or Docker Compose |
| Repo storage | Local disk, NFS, or S3-backed FUSE |

### Gunicorn Command

```bash
gunicorn cicd_tool.wsgi \
  --workers 4 \
  --bind 0.0.0.0:8001 \
  --timeout 120 \
  --keep-alive 5
```

### Nginx Configuration

```nginx
server {
    listen 443 ssl http2;
    server_name git.example.com;

    ssl_certificate     /etc/ssl/certs/releaserocket.crt;
    ssl_certificate_key /etc/ssl/private/releaserocket.key;

    # Allow large git push payloads
    client_max_body_size 500M;

    # Static and media files
    location /static/ { alias /var/www/releaserocket/static/; }
    location /media/  { alias /var/www/releaserocket/media/; }

    # Django app
    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Critical: disable buffering for SSE (live log streaming)
        proxy_buffering  off;
        proxy_cache      off;
        proxy_read_timeout 300s;
    }
}
```

### Collect Static Files

```bash
python manage.py collectstatic --noinput
```

### systemd Service

```ini
[Unit]
Description=ReleaseRocket
After=network.target postgresql.service

[Service]
User=releaserocket
WorkingDirectory=/opt/releaserocket/cicd_tool
EnvironmentFile=/opt/releaserocket/.env
ExecStart=/opt/releaserocket/.venv/bin/gunicorn cicd_tool.wsgi -w 4 -b 0.0.0.0:8001
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## 14. Contributing

### Branch Strategy

| Branch | Purpose |
|---|---|
| `main` | Production releases only |
| `develop` | Integration branch for features |
| `feature/<name>` | New features (branch from `develop`) |
| `fix/<name>` | Bug fixes (branch from `develop` or `main`) |

### Adding a New Feature — Checklist

- [ ] **Model** — add to `models.py` with proper `Meta.ordering` and `__str__`
- [ ] **Migration** — run `makemigrations`, review the output before committing
- [ ] **View** — decorate with `@login_required`, use `get_object_or_404`
- [ ] **URL** — register with a named pattern in `urls.py`
- [ ] **Template** — extend `pipeline/base.html`, use CSS variables (`var(--card-bg)` etc.)
- [ ] **Admin** — register in `admin.py` with `list_display` and `search_fields`
- [ ] **Activity** — call `log_activity()` for significant user actions
- [ ] **Notifications** — call `notify()` where users should be alerted

### Code Style

- Follow PEP 8
- Use Django ORM — no raw SQL
- Keep business logic in model methods or view helpers, not templates
- URL names use **hyphens** (e.g. `pipeline-detail`), not underscores
- All templates must extend `pipeline/base.html` and use the dark-theme CSS variables

### CSS / UI Conventions

The dark theme is defined in `pipeline/base.html`. Always use these variables — never hardcode colours:

```css
var(--dark-bg)        /* #0d1117 — page background */
var(--card-bg)        /* #161b22 — card/panel background */
var(--border-color)   /* #30363d — borders */
var(--text-primary)   /* #e6edf3 — main text */
var(--text-secondary) /* #7d8590 — muted text */
var(--accent-color)   /* #2f81f7 — links, buttons, highlights */
var(--success-color)  /* #3fb950 — success states */
var(--danger-color)   /* #f85149 — errors */
var(--warning-color)  /* #d29922 — warnings */
```

---

*ReleaseRocket Developer Guide · Version 2.0 · July 2026*
