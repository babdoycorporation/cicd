# ⚡ ReleaseRocket

> Self-hosted Git hosting + CI/CD in one platform. Think GitHub meets Jenkins — running entirely on your own servers.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![Django](https://img.shields.io/badge/Django-5.0-green.svg)](https://djangoproject.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What Is It?

ReleaseRocket gives your team a complete DevOps platform without depending on external cloud services:

- **Git hosting** with a full web UI — browse code, review diffs, edit files in the browser
- **Pull requests** with code review, inline comments, approvals, and merge protection
- **Issue tracker** with labels, milestones, and assignees
- **CI/CD pipelines** triggered automatically on every push, with live log streaming
- **Build agents** that run on any Linux machine in your network

---

## Quick Start (5 minutes)

### Prerequisites
- Python 3.11+
- Git installed on the server

### Install & Run

```bash
# Clone the project
git clone <releaserocket-url> && cd releaserocket/cicd_tool

# Set up Python environment
python -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install django gitpython pillow

# Configure (minimum required)
export DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(50))')"
export REPO_BASE_PATH="/var/releaserocket/repos"

# Set up database
python manage.py migrate
python manage.py createsuperuser

# Start
python manage.py runserver 0.0.0.0:8001
```

Visit `http://localhost:8001` and log in with your superuser credentials.

---

## Using Git With ReleaseRocket

Any standard Git client works. Authenticate with a Personal Access Token (create one at **Profile → Personal Access Tokens**):

```bash
# Clone a repository
git clone http://localhost:8001/git/username/my-repo.git

# Push (uses your PAT as the password)
git remote set-url origin http://username:YOUR_PAT@localhost:8001/git/username/my-repo.git
git push origin main
```

---

## Setting Up a CI/CD Pipeline

**1.** Add a `rockerci.yaml` to your repository root:

```yaml
name: Build and Deploy

on:
  push:
    branches: [main]

jobs:
  build:
    steps:
      - name: Install
        run: npm install
      - name: Test
        run: npm test
      - name: Deploy
        run: ./scripts/deploy.sh
```

**2.** In the ReleaseRocket UI: create a **Project → Application → Pipeline**, point it at this repo and branch.

**3.** Push to `main` — the pipeline runs automatically and logs stream live.

---

## Documentation

| | |
|---|---|
| 📗 [User Guide](docs/USER_GUIDE.md) | For team members using the platform day-to-day |
| 📘 [Developer Guide](docs/DEVELOPER.md) | For engineers building on or deploying ReleaseRocket |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | Django 5.0 (Python 3.11) |
| Database | SQLite (dev) · PostgreSQL (production) |
| Git | GitPython + Git Smart HTTP Protocol |
| Real-time | Server-Sent Events (SSE) for live log streaming |
| Agents | Python HTTP server with HMAC-SHA256 authentication |
| UI | Dark theme · Phosphor Icons · Inter font |

---

## Project Layout

```
cicd_tool/
├── gitmgmt/         # Git hosting — repos, PRs, issues, reviews, releases
├── pipeline/        # CI/CD — projects, pipelines, agents, runs, metrics
├── templates/       # Shared HTML base layout
├── linux_agent.py   # Standalone build agent (deploy on any Linux host)
└── docs/
    ├── USER_GUIDE.md
    └── DEVELOPER.md
```

---

## License

MIT — see [LICENSE](LICENSE).
