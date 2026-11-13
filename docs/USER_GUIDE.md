# ReleaseRocket — User Guide

> **Audience:** Team members and clients using ReleaseRocket day-to-day.
> No programming knowledge required for most sections.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Repositories](#2-repositories)
3. [Pull Requests & Code Review](#3-pull-requests--code-review)
4. [Issues & Project Tracking](#4-issues--project-tracking)
5. [CI/CD Pipelines](#5-cicd-pipelines)
6. [Notifications](#6-notifications)
7. [Your Profile & Access Tokens](#7-your-profile--access-tokens)
8. [Organizations & Teams](#8-organizations--teams)
9. [Frequently Asked Questions](#9-frequently-asked-questions)

---

## 1. Getting Started

### Logging In

Navigate to your ReleaseRocket URL (e.g. `http://your-server:8001`). Enter your username and password on the login page. If you don't have an account, ask your administrator to create one or register on the signup page.

### The Dashboard

After logging in you land on the **Dashboard**, which shows:

- Recent pipeline runs and their status (success / failed / running)
- Active build agents
- Quick-access links to your projects and repositories

The left sidebar is your main navigation. It changes context depending on whether you are in the global hub or inside a specific project.

---

## 2. Repositories

Repositories store your code and its full history.

### Creating a Repository

1. Click **Repositories** in the sidebar, then **New Repository** (top right).
2. Fill in:
   - **Name** — lowercase, hyphens only (e.g. `api-service`)
   - **Description** — optional, but helpful for teammates
   - **Visibility** — Public (anyone can see) or Private (collaborators only)
   - **Default branch** — usually `main`
3. Click **Create Repository**.

### Browsing Code

On the repository page you can:

- Switch branches using the branch dropdown
- Click folders and files to navigate the code tree
- Click any file to view its contents with syntax highlighting
- Use the **Edit** button (pencil icon) to edit a file directly in the browser
- Use **Upload File** to add files without a local Git client

### Cloning to Your Computer

You need Git installed locally. Find your **Personal Access Token** first (see [Section 7](#7-your-profile--access-tokens)), then:

```bash
git clone http://your-server:8001/git/your-username/repo-name.git
```

When prompted for a password, use your Personal Access Token.

### Forking a Repository

Forking creates your own copy of someone else's repository so you can make changes without affecting the original.

1. Go to any repository.
2. Click the **Fork** button (top right of the repository page).
3. Your fork appears in your repository list.

### Stars & Watching

- ⭐ **Star** a repository to bookmark it and show appreciation.
- 👁️ **Watch** a repository to receive notifications when things change.

---

## 3. Pull Requests & Code Review

A Pull Request (PR) proposes merging code changes from one branch into another. This is the standard code review workflow.

### Opening a Pull Request

1. Push your branch to ReleaseRocket.
2. Go to the repository → **Pull Requests** → **New Pull Request**.
3. Select your **source branch** (the one with your changes) and the **target branch** (usually `main`).
4. Fill in a **title** and **description** explaining what changed and why.
5. Optionally assign **reviewers**, **labels**, or a **milestone**.
6. Click **Create Pull Request** (or **Create as Draft** if it's not ready for review).

### Reviewing a Pull Request

On a PR page you can:

- Read the **description** and view the **diff** (the changes made)
- Leave a **comment** at the bottom
- Add **inline comments** on specific lines of the diff (click the `+` icon next to any line)
- Submit a **review**:
  - ✅ **Approve** — the code is good to merge
  - 🔄 **Request Changes** — something needs fixing before merge
  - 💬 **Comment** — leave feedback without approving or blocking

### Merging

Once the required approvals are received and all checks pass, the **Merge Pull Request** button becomes available. Click it to merge. If branch protection rules require a certain number of approvals, the button is locked until those are met.

### Emoji Reactions

Click the smiley face icon on any comment to add a quick reaction (👍 👎 😄 🎉 ❤️ 🚀).

---

## 4. Issues & Project Tracking

Issues are used to track bugs, feature requests, tasks, and any other work items.

### Creating an Issue

1. Go to **Repository → Issues → New Issue**.
2. Write a **title** (short summary) and **body** (full description, steps to reproduce, screenshots etc.).
3. Assign **labels** (e.g. `bug`, `enhancement`, `help wanted`).
4. Set a **milestone** if this issue belongs to a sprint or release.
5. Assign it to a team member under **Assignees**.
6. Click **Submit new issue**.

### Labels

Labels categorise issues and pull requests. Common labels:

| Label | Colour | Meaning |
|---|---|---|
| `bug` | Red | Something is broken |
| `enhancement` | Blue | New feature or improvement |
| `documentation` | Purple | Docs need updating |
| `good first issue` | Green | Good for newcomers |
| `help wanted` | Yellow | Extra attention needed |

Create custom labels at **Repository → Labels → New Label**.

### Milestones

A milestone groups issues into a target (e.g. `v1.0 Release`, `Q3 Sprint`). You can set a due date and track progress as issues are closed. View milestones at **Repository → Milestones**.

### Closing an Issue

Issues are closed when the work is complete. You can:
- Close manually by clicking **Close Issue** on the issue page.
- Close automatically by including `Closes #42` in a pull request description — the issue closes when the PR merges.

---

## 5. CI/CD Pipelines

Pipelines automatically build, test, and deploy your code every time someone pushes a change.

### Understanding the Structure

```
Project
└── Application (e.g. "api-service")
    └── Pipeline (reads rockerci.yaml → runs steps on an Agent)
```

- A **Project** is a top-level grouping (e.g. "Acme Core")
- An **Application** is a deployable service inside that project
- A **Pipeline** is the set of automated steps that run on code changes

### Viewing Pipeline Runs

Go to **CI Dashboard** or open any **Project → View Build History**. You'll see:

| Column | Meaning |
|---|---|
| Status | ✅ Success · ❌ Failed · ⏳ Running · ⏸ Pending |
| Pipeline | Which pipeline ran |
| Agent | Which build server ran it |
| Duration | How long it took |
| Started | When it started |

Click any run to see the full **live log output**, step by step.

### Triggering a Build Manually

Inside a project, click the green **Trigger Build** button. This kicks off the latest pipeline immediately regardless of a code push.

### Reading Build Logs

Each step in your `rockerci.yaml` appears as a collapsible section in the run log. Green = passed, red = failed. Click any step to expand its full console output.

### What Happens When a Pipeline Fails

1. The run status turns red.
2. If notifications are enabled, you receive an in-app notification and optionally an email.
3. Open the run, expand the failed step, and read the error output.
4. Fix the code, push again — a new run starts automatically.

---

## 6. Notifications

The 🔔 bell icon in the top bar shows your unread notification count.

Click it to open the **Notification Center**, which lists:

- Pipeline failures and successes on your projects
- Pull request reviews and approvals
- Mentions of your username (`@you`) in comments
- Issues and PRs assigned to you
- New releases on repositories you watch

Click any notification to go directly to the relevant page. Click **Mark as Read** or open the notification detail to clear it.

---

## 7. Your Profile & Access Tokens

### Editing Your Profile

Click your username in the bottom-left sidebar → **Profile**. You can update your bio, company, and Twitter handle.

### Personal Access Tokens (PATs)

PATs are passwords used by Git clients and automation tools instead of your main password.

**Creating a token:**

1. Go to **Profile → Personal Access Tokens**.
2. Enter a name for the token (e.g. `laptop`, `CI script`, `VS Code`).
3. Click **Generate Token**.
4. **Copy the token immediately** — you will not see it again.

**Using a token with Git:**

```bash
# When git prompts for your password, paste the PAT
git clone http://your-server:8001/git/username/repo.git
Username: your-username
Password: paste-your-token-here
```

**Revoking a token:**

Click the trash icon next to any token to delete it immediately. Any system using that token will lose access.

---

## 8. Organizations & Teams

Organizations let you group multiple people and repositories under one umbrella (e.g. your company or department).

### Creating an Organization

1. Click **Organizations** in the sidebar.
2. Click **New Organization**, fill in the name and description.

### Inviting Members

Inside an organization, use the **Add Member** form on the right sidebar. Enter the username and select which team they join.

### Teams

Teams are sub-groups within an organization (e.g. `Backend`, `Frontend`, `DevOps`). Create a team with **Create Team**, then invite members to it.

### Creating Repositories Under an Organization

When creating a repository, an `?org=` parameter in the URL pre-selects the organization. Or simply go to the organization page and click **New Repo**.

---

## 9. Frequently Asked Questions

**Q: I forgot my password. How do I reset it?**
Contact your ReleaseRocket administrator. They can reset your password from the Django admin panel at `/admin/`.

**Q: I pushed code but my pipeline didn't trigger. Why?**
Check that the pipeline's **monitored branch** matches the branch you pushed to. Also confirm that at least one build agent is online (Dashboard → Agents).

**Q: Can I use VS Code or GitHub Desktop with ReleaseRocket?**
Yes — any Git client that supports HTTP works. Use your username and a Personal Access Token as the password.

**Q: My build failed but the code looks correct. What should I check?**
- Open the build run and expand each step to find the failed one.
- Check that required environment variables are set in **Project Settings → CI/CD Variables**.
- Verify the build agent has the required tools installed (Node.js, Docker, etc.).

**Q: How do I make a repository private?**
Go to **Repository → Settings** and change **Visibility** to Private. Only collaborators with access can then view or clone it.

**Q: What is the difference between a Project and a Repository?**
A **Repository** (in the Git section) stores your source code with full version history. A **Project** (in the CI/CD section) is a grouping for your pipelines and build agents. They are separate but related — your pipeline pulls code from a repository to build it.

**Q: Can multiple people review the same pull request?**
Yes. Add multiple reviewers when creating the PR. Each reviewer can approve or request changes independently. Branch protection rules can require a minimum number of approvals before merging.

---

*ReleaseRocket User Guide · Version 2.0 · July 2026*
