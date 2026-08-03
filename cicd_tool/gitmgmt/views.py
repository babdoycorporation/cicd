"""
gitmgmt/views.py  —  Git hosting + collaboration views
Fixes applied:
  • create_pull_request: created_by → author
  • GitService.authenticate: compare hashed token
  • All views login_required
  • Issues, Labels, Milestones, Releases, Forking, Reviews, Notifications, Activity
"""

import base64
import json
import logging
import os
import re
import subprocess
import tempfile

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate as django_authenticate
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import (FileResponse, HttpResponse, HttpResponseForbidden,
                          HttpResponseServerError, JsonResponse)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from git import GitCommandError, Repo

from .forms import (IssueCommentForm, IssueForm, LabelForm, MilestoneForm,
                     PRReviewCommentForm, PRReviewForm, PullRequestCommentForm,
                     PullRequestForm, ReleaseForm, RepositoryForm,
                     UploadFileForm, UserProfileForm)
from .models import (ActivityEvent, Branch, BranchProtectionRule, Commit,
                      Issue, IssueComment, Label, Milestone, Notification,
                      Organization, PersonalAccessToken, PRReview,
                      PRReviewComment, PullRequest, PullRequestComment,
                      Reaction, Release, Repository, Team, UserProfile,
                      log_activity, notify)

logger = logging.getLogger(__name__)

def _get_repo_base_path():
    try:
        from pipeline.models import GlobalSettings
        setting = GlobalSettings.objects.filter(key='REPO_STORAGE_PATH').first()
        if setting and setting.value.strip():
            return setting.value.strip()
    except Exception:
        pass
    return getattr(settings, 'REPO_BASE_PATH', str(settings.BASE_DIR / 'repos'))

def _repo_path(name):
    base_dir = _get_repo_base_path()
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, f"{name}.git")


# ─────────────────────────────────────────────────────────────────────────────
#  Repository list / create
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def repository_list(request):
    query = request.GET.get('q', '').strip()
    visibility_filter = request.GET.get('visibility', '').strip().lower()

    # User's organizations
    user_orgs = Organization.objects.filter(
        Q(owner=request.user) | Q(memberships__user=request.user) | Q(teams__members=request.user)
    ).distinct()

    # Repositories user has access to (owned, organization, collaborator, or public)
    repos = Repository.objects.filter(
        Q(owner=request.user) |
        Q(organization__in=user_orgs) |
        Q(collaborators__user=request.user) |
        Q(visibility='public')
    ).distinct().order_by('-updated_at')

    if visibility_filter == 'public':
        repos = repos.filter(visibility='public')
    elif visibility_filter == 'private':
        repos = repos.filter(visibility='private')

    if query:
        repos = repos.filter(Q(name__icontains=query) | Q(description__icontains=query))

    favorites = repos.filter(stars=request.user)

    return render(request, 'gitmgmt/repository_list.html', {
        'repositories': repos,
        'favorites': favorites,
        'query': query,
        'visibility_filter': visibility_filter,
    })


@login_required
def toggle_favorite(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    if request.method == 'POST':
        if request.user in repo.stars.all():
            repo.stars.remove(request.user)
            log_activity(request.user, 'star', f"Unstarred {repo.name}", repository=repo)
        else:
            repo.stars.add(request.user)
            log_activity(request.user, 'star', f"Starred {repo.name}", repository=repo)
    return redirect('repository_list')


@login_required
def toggle_watch(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    if request.method == 'POST':
        if request.user in repo.watchers.all():
            repo.watchers.remove(request.user)
        else:
            repo.watchers.add(request.user)
    return redirect('repository_detail', repository_name=repo.name)


def _initialize_repository(name, user=None):
    """Create a bare git repo on disk with an initial README commit."""
    repo_path = _repo_path(name)
    if not os.path.exists(repo_path):
        os.makedirs(repo_path)

    repo = Repo.init(repo_path, bare=True)
    author_name = user.get_full_name() or user.username if user else 'System'
    author_email = user.email if user else 'system@rockerci.local'

    env = os.environ.copy()
    env.update({
        'GIT_AUTHOR_NAME': author_name,
        'GIT_AUTHOR_EMAIL': author_email,
        'GIT_COMMITTER_NAME': author_name,
        'GIT_COMMITTER_EMAIL': author_email,
    })

    readme = f"# {name}\n\nWelcome to **{name}**.\n"
    blob_hash = subprocess.check_output(
        ['git', 'hash-object', '-w', '--stdin'],
        input=readme.encode(), cwd=repo_path, env=env
    ).decode().strip()
    tree_content = f"100644 blob {blob_hash}\tREADME.md"
    tree_hash = subprocess.check_output(
        ['git', 'mktree'], input=tree_content.encode(), cwd=repo_path, env=env
    ).decode().strip()
    commit_hash = subprocess.check_output(
        ['git', 'commit-tree', tree_hash, '-m', 'Initial commit'],
        cwd=repo_path, env=env
    ).decode().strip()
    subprocess.run(['git', 'update-ref', 'refs/heads/main', commit_hash], check=True, cwd=repo_path, env=env)
    subprocess.run(['git', 'symbolic-ref', 'HEAD', 'refs/heads/main'], check=True, cwd=repo_path, env=env)
    return repo


@login_required
def create_repository(request):
    org_id = request.GET.get('org')
    initial = {}
    if org_id and str(org_id).isdigit():
        org = Organization.objects.filter(pk=int(org_id)).first()
        if org:
            initial['organization'] = org.pk

    if request.method == 'POST':
        form = RepositoryForm(request.POST)
        if form.is_valid():
            repo = form.save(commit=False)
            repo.owner = request.user
            try:
                _initialize_repository(repo.name, user=request.user)
                repo.save()
                branch = Branch.objects.create(repository=repo, name=repo.default_branch, is_default=True)
                _create_default_labels(repo)
                log_activity(request.user, 'push', f"Created repository {repo.name}", repository=repo)
                messages.success(request, f"Repository '{repo.name}' created.")
                return redirect('repository_detail', repository_name=repo.name)
            except Exception as e:
                form.add_error(None, f"Failed to initialize repository: {e}")
    else:
        form = RepositoryForm(initial=initial)
    return render(request, 'gitmgmt/repository_form.html', {'form': form})


def _create_default_labels(repo):
    defaults = [
        ('bug', '#d73a4a', 'Something is not working'),
        ('documentation', '#0075ca', 'Improvements or additions to documentation'),
        ('enhancement', '#84b6eb', 'New feature or request'),
        ('good first issue', '#7057ff', 'Good for newcomers'),
        ('help wanted', '#008672', 'Extra attention is needed'),
        ('invalid', '#e4e669', "This doesn't seem right"),
        ('question', '#d876e3', 'Further information is requested'),
        ('wontfix', '#ffffff', 'This will not be worked on'),
    ]
    Label.objects.bulk_create([
        Label(repository=repo, name=n, color=c, description=d)
        for n, c, d in defaults
    ])


# ─────────────────────────────────────────────────────────────────────────────
#  Repository detail / file browser
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def repository_detail(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    rp = _repo_path(repo.name)
    branches, files, current_branch = [], [], None
    last_commit_hash = last_commit_message = readme_content = error_message = None

    try:
        git_repo = Repo(rp)
        branches = [b.name for b in git_repo.heads]
        # Bare repos have no active_branch — use the request param, then DB default, then first head
        requested = request.GET.get('branch')
        default = repo.default_branch or 'main'
        if requested and any(b == requested for b in branches):
            current_branch = requested
        elif default in branches:
            current_branch = default
        elif branches:
            current_branch = branches[0]
        else:
            error_message = "Repository has no branches yet."

        if current_branch:
            branch_head = next(h for h in git_repo.heads if h.name == current_branch)
            tree = branch_head.commit.tree
            files = []
            for item in tree.traverse():
                if item.type == 'blob':
                    files.append({
                        'path': item.path,
                        'size': item.size,
                    })
            last_commit = branch_head.commit
            last_commit_hash = last_commit.hexsha
            last_commit_message = last_commit.message.strip()
            for name in ('README.md', 'readme.md', 'Readme.md'):
                if name in tree:
                    readme_content = tree[name].data_stream.read().decode('utf-8', errors='replace')
                    break
    except Exception as e:
        error_message = str(e)



    is_starred = request.user in repo.stars.all()
    is_watching = request.user in repo.watchers.all()
    user_role = None
    if repo.owner == request.user:
        user_role = 'owner'
    else:
        collab = repo.collaborators.filter(user=request.user).first()
        if collab:
            user_role = collab.role

    return render(request, 'gitmgmt/repository_detail.html', {
        'repository': repo,
        'branches': branches,
        'current_branch': current_branch,
        'files': files,
        'last_commit_hash': last_commit_hash,
        'last_commit_message': last_commit_message,
        'readme_content': readme_content,
        'error_message': error_message,
        'is_starred': is_starred,
        'is_watching': is_watching,
        'user_role': user_role,
        'can_manage_repo': _user_can_manage_repo(request.user, repo),
    })


# ─────────────────────────────────────────────────────────────────────────────
#  Fork
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def fork_repository(request, repository_name):
    original = get_object_or_404(Repository, name=repository_name)
    if request.method == 'POST':
        fork_name = f"{request.user.username}-{original.name}"
        if Repository.objects.filter(name=fork_name).exists():
            messages.error(request, f"Repository '{fork_name}' already exists.")
            return redirect('repository_detail', repository_name=original.name)

        orig_path = _repo_path(original.name)
        fork_path = _repo_path(fork_name)
        try:
            subprocess.run(['git', 'clone', '--bare', orig_path, fork_path], check=True)
            fork = Repository.objects.create(
                name=fork_name,
                description=f"Fork of {original.name}",
                owner=request.user,
                visibility=original.visibility,
                default_branch=original.default_branch,
                forked_from=original,
                is_fork=True,
            )
            # Mirror Branch records
            for b in original.branches.all():
                Branch.objects.create(repository=fork, name=b.name, is_default=b.is_default)
            _create_default_labels(fork)
            log_activity(request.user, 'fork', f"Forked {original.name} → {fork_name}", repository=original)
            messages.success(request, f"Repository forked as '{fork_name}'.")
            return redirect('repository_detail', repository_name=fork_name)
        except Exception as e:
            messages.error(request, f"Fork failed: {e}")
    return redirect('repository_detail', repository_name=original.name)


# ─────────────────────────────────────────────────────────────────────────────
#  Collaborators / Settings
# ─────────────────────────────────────────────────────────────────────────────

def _user_can_manage_repo(user, repo):
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff or repo.owner == user:
        return True
    if repo.organization:
        role = repo.organization.get_member_role(user)
        if role in ('owner', 'admin'):
            return True
    if repo.project:
        role = repo.project.get_member_role(user)
        if role in ('maintainer',):
            return True
    collab = repo.collaborators.filter(user=user).first()
    if collab and collab.role in ('admin', 'write'):
        return True
    return False


@login_required
def repository_settings(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    if not _user_can_manage_repo(request.user, repo):
        messages.error(request, "Access Denied: You need Maintainer or Repository Admin permissions to manage repository settings.")
        return redirect('repository_detail', repository_name=repo.name)
    collaborators = repo.collaborators.select_related('user').all()
    return render(request, 'gitmgmt/repository_settings.html', {
        'repository': repo,
        'collaborators': collaborators,
        'can_manage_repo': True,
    })


@login_required
def add_collaborator(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    if not _user_can_manage_repo(request.user, repo):
        messages.error(request, "Access Denied: Permission required to manage collaborators.")
        return redirect('repository_detail', repository_name=repo.name)
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        role = request.POST.get('role', 'read')
        user = User.objects.filter(username=username).first()
        if user:
            from .models import Collaborator
            Collaborator.objects.update_or_create(repository=repo, user=user, defaults={'role': role})
            messages.success(request, f"Added {username} as {role}.")
        else:
            messages.error(request, f"User '{username}' not found.")
    return redirect('repository_settings', repository_name=repo.name)


@login_required
def remove_collaborator(request, repository_name, user_id):
    repo = get_object_or_404(Repository, name=repository_name)
    if not _user_can_manage_repo(request.user, repo):
        messages.error(request, "Access Denied: Permission required to remove collaborators.")
        return redirect('repository_detail', repository_name=repo.name)
    if request.method == 'POST':
        from .models import Collaborator
        Collaborator.objects.filter(repository=repo, user_id=user_id).delete()
        messages.success(request, "Collaborator removed.")
    return redirect('repository_settings', repository_name=repo.name)


# ─────────────────────────────────────────────────────────────────────────────
#  Branch management
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def create_branch(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    rp = _repo_path(repo.name)
    if request.method == 'POST':
        branch_name = request.POST.get('branch_name', '').strip()
        source = request.POST.get('source_branch', 'main').strip()
        if not branch_name or not _validate_branch_name(branch_name):
            messages.error(request, "Invalid branch name.")
            return redirect('repository_detail', repository_name=repo.name)
        try:
            git_repo = Repo(rp)
            if branch_name in [h.name for h in git_repo.heads]:
                messages.error(request, f"Branch '{branch_name}' already exists.")
            elif source not in [h.name for h in git_repo.heads]:
                messages.error(request, f"Source branch '{source}' not found.")
            else:
                git_repo.create_head(branch_name, git_repo.heads[source].commit)
                Branch.objects.get_or_create(repository=repo, name=branch_name)
                log_activity(request.user, 'branch', f"Created branch {branch_name}", repository=repo)
                messages.success(request, f"Branch '{branch_name}' created from '{source}'.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect('repository_detail', repository_name=repo.name)


@login_required
def merge_branch(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    rp = _repo_path(repo.name)
    if request.method == 'POST':
        target = request.POST.get('merge_target', '').strip()
        current = request.GET.get('branch', 'main').strip()
        if not _validate_branch_name(target) or not _validate_branch_name(current):
            messages.error(request, "Invalid branch name."); return redirect('repository_detail', repository_name=repo.name)
        if target == current:
            messages.error(request, "Cannot merge a branch into itself."); return redirect('repository_detail', repository_name=repo.name)
        target_obj = Branch.objects.filter(repository=repo, name=target).first()
        if target_obj and target_obj.is_protected:
            if repo.owner != request.user and not request.user.is_staff:
                messages.error(request, f"'{target}' is protected."); return redirect('repository_detail', repository_name=repo.name)
        with tempfile.TemporaryDirectory() as td:
            try:
                r = Repo.clone_from(rp, td)
                r.git.fetch('--all')
                remote_branches = [ref.name.split('/')[-1] for ref in r.remotes.origin.refs]
                if target not in remote_branches or current not in remote_branches:
                    messages.error(request, "Branch not found remotely."); return redirect('repository_detail', repository_name=repo.name)
                r.git.checkout('--', current)
                r.git.pull('origin', current)
                r.git.merge(f'origin/{target}')
                r.git.push('origin', current)
                log_activity(request.user, 'merge', f"Merged {target} → {current}", repository=repo)
                messages.success(request, f"Merged {target} into {current}.")
            except GitCommandError as e:
                try: r.git.merge('--abort')
                except Exception: pass
                messages.error(request, f"Merge failed: {e}")
            except Exception as e:
                messages.error(request, f"Unexpected error: {e}")
    return redirect('repository_detail', repository_name=repo.name)


@login_required
def delete_branch(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    rp = _repo_path(repo.name)
    if request.method == 'POST':
        branch_name = request.POST.get('branch_name', '').strip()
        if not _validate_branch_name(branch_name):
            messages.error(request, "Invalid branch name."); return redirect('repository_detail', repository_name=repo.name)
        b_obj = Branch.objects.filter(repository=repo, name=branch_name).first()
        if b_obj and b_obj.is_default:
            messages.error(request, "Cannot delete default branch."); return redirect('repository_detail', repository_name=repo.name)
        if b_obj and b_obj.is_protected:
            messages.error(request, "Branch is protected."); return redirect('repository_detail', repository_name=repo.name)
        try:
            git_repo = Repo(rp)
            git_repo.delete_head(branch_name, force=True)
            Branch.objects.filter(repository=repo, name=branch_name).delete()
            messages.success(request, f"Branch '{branch_name}' deleted.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect('repository_detail', repository_name=repo.name)


@login_required
def branch_protection(request, repository_name, branch_name):
    repo = get_object_or_404(Repository, name=repository_name)
    if repo.owner != request.user and not request.user.is_staff:
        return HttpResponseForbidden()
    branch = get_object_or_404(Branch, repository=repo, name=branch_name)
    rule, _ = BranchProtectionRule.objects.get_or_create(branch=branch, defaults={'created_by': request.user})
    if request.method == 'POST':
        rule.require_pull_request = 'require_pull_request' in request.POST
        rule.required_approvals = int(request.POST.get('required_approvals', 1))
        rule.dismiss_stale_reviews = 'dismiss_stale_reviews' in request.POST
        rule.require_status_checks = 'require_status_checks' in request.POST
        rule.allow_force_push = 'allow_force_push' in request.POST
        rule.save()
        branch.is_protected = True
        branch.save()
        messages.success(request, "Branch protection rule saved.")
        return redirect('repository_settings', repository_name=repo.name)
    return render(request, 'gitmgmt/branch_protection.html', {'repository': repo, 'branch': branch, 'rule': rule})


# ─────────────────────────────────────────────────────────────────────────────
#  File operations
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def upload_file(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    rp = _repo_path(repo.name)
    current_branch = request.GET.get('branch', 'main')

    if request.method == 'POST' and request.FILES.get('file'):
        f = request.FILES['file']
        safe_name = os.path.basename(f.name)
        if not safe_name:
            messages.error(request, "Invalid filename."); return redirect('repository_detail', repository_name=repo.name)
        if not _validate_branch_name(current_branch):
            messages.error(request, "Invalid branch name."); return redirect('repository_detail', repository_name=repo.name)
        commit_msg = request.POST.get('commit_message', f"Upload {safe_name}").strip() or f"Upload {safe_name}"
        try:
            with tempfile.TemporaryDirectory() as td:
                r = Repo.clone_from(rp, td)
                r.git.fetch('--all')
                remote = r.git.branch('-r')
                if f'origin/{current_branch}' in remote:
                    r.git.checkout('-B', current_branch, f'origin/{current_branch}')
                else:
                    r.git.checkout('-b', current_branch)
                dest = os.path.join(td, safe_name)
                if not os.path.abspath(dest).startswith(os.path.abspath(td)):
                    raise ValueError("Path traversal detected")
                with open(dest, 'wb+') as fh:
                    for chunk in f.chunks():
                        fh.write(chunk)
                r.git.add('--', safe_name)
                r.index.commit(commit_msg)
                r.git.push('origin', current_branch)
                log_activity(request.user, 'push', f"Uploaded {safe_name} to {current_branch}", repository=repo)
                messages.success(request, f"'{safe_name}' uploaded to '{current_branch}'.")
        except Exception as e:
            messages.error(request, f"Upload failed: {e}")
    return redirect('repository_detail', repository_name=repo.name)


@login_required
@csrf_exempt
def edit_and_save_file(request, repository_name, file_path):
    repo = get_object_or_404(Repository, name=repository_name)
    rp = _repo_path(repo.name)

    def _read(branch):
        with tempfile.TemporaryDirectory() as td:
            tp = os.path.join(td, repo.name)
            subprocess.run(['git', 'clone', rp, tp], check=True, capture_output=True)
            subprocess.run(['git', 'checkout', branch], cwd=tp, check=True, capture_output=True)
            normalized = os.path.normpath(file_path.replace('\\', '/')).lstrip('/')
            fp = os.path.abspath(os.path.join(tp, normalized))
            if not fp.startswith(os.path.abspath(tp)):
                raise ValueError("Path traversal")
            with open(fp, 'r', encoding='utf-8') as fh:
                return fh.read()

    if request.method == 'GET':
        branch = request.GET.get('branch', 'main')
        try:
            content = _read(branch)
        except Exception as e:
            return JsonResponse({'status': 'error', 'error': str(e)}, status=500)
        return render(request, 'gitmgmt/edit_and_save_file.html', {
            'repository': repo, 'file_path': file_path,
            'file_content': content, 'current_branch': branch,
        })

    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            content = data.get('code', '')
            commit_msg = data.get('commit_message', '').strip()
            branch = data.get('branch', '').strip()
            if not commit_msg:
                return JsonResponse({'status': 'error', 'error': 'Commit message required'}, status=400)
            if not _validate_branch_name(branch):
                return JsonResponse({'status': 'error', 'error': 'Invalid branch name'}, status=400)
            with tempfile.TemporaryDirectory() as td:
                tp = os.path.join(td, repo.name)
                subprocess.run(['git', 'clone', rp, tp], check=True, capture_output=True)
                subprocess.run(['git', 'checkout', branch], cwd=tp, check=True, capture_output=True)
                normalized = os.path.normpath(file_path.replace('\\', '/')).lstrip('/')
                fp = os.path.abspath(os.path.join(tp, normalized))
                if not fp.startswith(os.path.abspath(tp)):
                    return JsonResponse({'status': 'error', 'error': 'Invalid path'}, status=400)
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, 'w', encoding='utf-8') as fh:
                    fh.write(content)
                subprocess.run(['git', 'config', 'user.email', request.user.email or 'user@rockerci'], cwd=tp, check=True)
                subprocess.run(['git', 'config', 'user.name', request.user.username], cwd=tp, check=True)
                subprocess.run(['git', 'add', '--', normalized], cwd=tp, check=True, capture_output=True)
                cr = subprocess.run(['git', 'commit', '-m', commit_msg], cwd=tp, capture_output=True, text=True)
                if cr.returncode != 0:
                    return JsonResponse({'status': 'error', 'error': 'Commit failed: ' + cr.stderr}, status=500)
                pr2 = subprocess.run(['git', 'push', 'origin', f'{branch}:{branch}'], cwd=tp, capture_output=True, text=True)
                if pr2.returncode != 0:
                    return JsonResponse({'status': 'error', 'error': 'Push failed: ' + pr2.stderr}, status=500)
                log_activity(request.user, 'push', f"Edited {file_path}", repository=repo)
            return JsonResponse({'status': 'success', 'updated_content': content})
        except Exception as e:
            return JsonResponse({'status': 'error', 'error': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'error': 'Method not allowed'}, status=405)


@login_required
def view_logs(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    rp = _repo_path(repo.name)
    branch = request.GET.get('branch', 'main')
    logs, error_message = [], None
    try:
        git_repo = Repo(rp)
        git_repo.git.fetch('--all')
        ref = branch if branch in [h.name for h in git_repo.heads] else 'HEAD'
        
        users_by_email = {u.email.lower(): u for u in User.objects.exclude(email='')}
        users_by_name = {u.username.lower(): u for u in User.objects.all()}

        for c in git_repo.iter_commits(ref, max_count=100):
            author_email = (c.author.email or '').strip().lower()
            author_name = (c.author.name or '').strip().lower()

            matched_user = users_by_email.get(author_email) or users_by_name.get(author_name)
            author_display = matched_user.username if matched_user else (c.author.name or c.author.email or 'Unknown')

            logs.append({
                'hash': c.hexsha[:7],
                'full_hash': c.hexsha,
                'message': c.message.strip(),
                'author': author_display,
                'user': matched_user,
                'email': c.author.email,
                'date': c.committed_datetime.isoformat(),
                'date_display': c.committed_datetime.strftime('%b %d, %Y %H:%M'),
            })
    except Exception:
        error_message = None
    return render(request, 'gitmgmt/view_logs.html', {
        'repository': repo, 'logs': logs,
        'error_message': error_message, 'current_branch': branch,
        'can_manage_repo': _user_can_manage_repo(request.user, repo),
    })


# ─────────────────────────────────────────────────────────────────────────────
#  Git HTTP Smart Protocol
# ─────────────────────────────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name='dispatch')
class GitService(View):

    def dispatch(self, request, *args, **kwargs):
        user = self._authenticate(request)
        if not user:
            resp = HttpResponse("Unauthorized", status=401)
            resp['WWW-Authenticate'] = 'Basic realm="RockerCI Git"'
            return resp
        request.user = user
        return super().dispatch(request, *args, **kwargs)

    def _authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Basic '):
            return None
        try:
            decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
            username, _, password = decoded.partition(':')
            # 1. Django password auth
            user = django_authenticate(username=username, password=password)
            if user:
                return user
            # 2. Personal Access Token (compare hash)
            user_obj = User.objects.filter(username=username).first()
            if user_obj:
                token_hash = PersonalAccessToken.hash_token(password)
                token_obj = PersonalAccessToken.objects.filter(
                    user=user_obj, token_hash=token_hash
                ).first()
                if token_obj:
                    if token_obj.expires_at and timezone.now() > token_obj.expires_at:
                        return None
                    token_obj.last_used = timezone.now()
                    token_obj.save(update_fields=['last_used'])
                    return user_obj
        except Exception as e:
            logger.error(f"Git auth error: {e}")
        return None

    def get(self, request, repo_name, owner=None, path=None):
        clean_name = repo_name.removesuffix('.git')
        repo = Repository.objects.filter(name__iexact=clean_name).first()
        if not repo:
            return HttpResponse(f"Repository '{clean_name}' not found.", status=404)
        repo_name = repo.name
        rp = _repo_path(repo_name)
        if not os.path.exists(rp):
            return HttpResponse(f"Repository '{repo_name}' not found.", status=404)
        service = request.GET.get('service')
        if service in ('git-upload-pack', 'git-receive-pack'):
            return self._advertise(rp, service)
        if path:
            return self._static_file(rp, path)
        return self._info_refs(rp)

    def post(self, request, repo_name, owner=None, path=None):
        clean_name = repo_name.removesuffix('.git')
        repo = Repository.objects.filter(name__iexact=clean_name).first()
        if not repo:
            return HttpResponse(f"Repository '{clean_name}' not found.", status=404)
        repo_name = repo.name
        rp = _repo_path(repo_name)
        if not os.path.exists(rp):
            return HttpResponse(f"Repository '{repo_name}' not found.", status=404)
        if path in ('git-upload-pack', 'git-receive-pack'):
            return self._handle_service(rp, path, request.body, repo_name)
        return HttpResponseServerError("Invalid service")

    def _advertise(self, rp, service):
        cmd = ['git', service[4:], '--advertise-refs', rp]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            return HttpResponseServerError(result.stderr.decode())
        resp = HttpResponse(content_type=f'application/x-{service}-advertisement')
        pkt = f"# service={service}\n"
        resp.write(f"{len(pkt) + 4:04x}{pkt}0000".encode())
        resp.write(result.stdout)
        return resp

    def _info_refs(self, rp):
        subprocess.run(['git', 'update-server-info'], cwd=rp, capture_output=True)
        refs_file = os.path.join(rp, 'info', 'refs')
        if not os.path.exists(refs_file):
            return HttpResponseServerError("info/refs not found")
        with open(refs_file, 'rb') as fh:
            return HttpResponse(fh.read(), content_type='text/plain')

    def _handle_service(self, rp, service, body, repo_name):
        cmd = ['git', service[4:], '--stateless-rpc', rp]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate(input=body)
        if proc.returncode != 0:
            return HttpResponseServerError(stderr.decode())
        if service == 'git-receive-pack':
            try:
                repo_obj = Repository.objects.filter(name__iexact=repo_name).first()
                if repo_obj:
                    log_activity(repo_obj.owner, 'push', f"Pushed commits to {repo_obj.name}", repository=repo_obj)
                self._trigger_yaml_pipeline(rp, repo_name)
            except Exception as e:
                logger.error(f"Error in post-receive hook for {repo_name}: {e}")
        return HttpResponse(stdout, content_type=f'application/x-{service}-result')

    def _trigger_yaml_pipeline(self, rp, repo_name):
        try:
            from pipeline.models import Application, Pipeline, PipelineRun, YamlFileVersion, Project
            from pipeline.utils import sync_steps_from_yaml

            git_repo = Repo(rp)
            repo_obj = Repository.objects.filter(name__iexact=repo_name).first()
            if not repo_obj:
                return

            app = Application.objects.filter(repository=repo_obj).first()
            if not app:
                proj = repo_obj.project
                if not proj and repo_obj.organization:
                    proj = Project.objects.filter(organization=repo_obj.organization).first()
                if not proj:
                    proj = Project.objects.first()
                if proj:
                    app, _ = Application.objects.get_or_create(
                        name=repo_obj.name,
                        project=proj,
                        defaults={'repository': repo_obj, 'framework': 'python'}
                    )

            if not app:
                return

            yaml_candidates = ['.rocketci.yml', 'rocketci.yml', '.rocketci.yaml', 'rocketci.yaml', 'pipeline.yml', 'ci.yml']

            for head in git_repo.heads:
                branch = head.name
                tree = head.commit.tree
                found_yaml_name = None
                yaml_content = None

                for y_name in yaml_candidates:
                    if y_name in tree:
                        found_yaml_name = y_name
                        yaml_content = tree[y_name].data_stream.read().decode('utf-8')
                        break

                if not yaml_content and app.pipelines.exists():
                    for p in app.pipelines.all():
                        if p.yaml_path in tree:
                            found_yaml_name = p.yaml_path
                            yaml_content = tree[p.yaml_path].data_stream.read().decode('utf-8')
                            break

                if yaml_content:
                    pipeline = app.pipelines.filter(monitored_branch=branch).first()
                    if not pipeline:
                        pipeline = app.pipelines.first()
                    if not pipeline:
                        pipeline = Pipeline.objects.create(
                            name=f"{app.name} Main Pipeline",
                            application=app,
                            monitored_branch=branch,
                            yaml_path=found_yaml_name or '.rocketci.yml'
                        )
                    else:
                        pipeline.monitored_branch = branch
                        if found_yaml_name:
                            pipeline.yaml_path = found_yaml_name
                        pipeline.save(update_fields=['monitored_branch', 'yaml_path'])

                    version = YamlFileVersion.objects.filter(pipeline=pipeline).count() + 1
                    YamlFileVersion.objects.create(
                        pipeline=pipeline, version_number=version, yaml_content=yaml_content
                    )

                    n_steps = sync_steps_from_yaml(pipeline, yaml_content)
                    commit = head.commit
                    run = PipelineRun.objects.create(
                        pipeline=pipeline,
                        status='pending',
                        log=(f'Triggered via git push on {branch} '
                             f'(commit {commit.hexsha[:10]}, {n_steps} steps)')
                    )
                    logger.info(f"Auto-triggered pipeline '{pipeline.name}' (Run ID {run.run_id}) for {repo_name} with {n_steps} steps.")
        except Exception as e:
            logger.error(f"Pipeline trigger failed for {repo_name}: {e}")

    def _static_file(self, rp, path):
        fp = os.path.join(rp, path)
        if not os.path.exists(fp):
            return HttpResponse("Not found", status=404)
        return FileResponse(open(fp, 'rb'))


# ─────────────────────────────────────────────────────────────────────────────
#  Pull Requests
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def pull_request_list(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    state = request.GET.get('state', 'open')
    prs = repo.pull_requests.filter(status=state).select_related('author', 'source_branch', 'target_branch').order_by('-created_at')
    return render(request, 'gitmgmt/pull_request_list.html', {
        'repository': repo, 'pull_requests': prs, 'state': state,
        'open_count': repo.pull_requests.filter(status='open').count(),
        'closed_count': repo.pull_requests.filter(status__in=['closed', 'merged']).count(),
    })


@login_required
def create_pull_request(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    if request.method == 'POST':
        form = PullRequestForm(request.POST, repository=repo)
        if form.is_valid():
            pr = form.save(commit=False)
            pr.repository = repo
            pr.author = request.user   # ← BUG FIX: was created_by
            pr.save()
            form.save_m2m()
            log_activity(request.user, 'pull_request', f"Opened PR #{pr.number}: {pr.title}", repository=repo)
            # In-app: notify reviewers
            if pr.reviewers.exists():
                notify(
                    list(pr.reviewers.all()), 'review_requested',
                    f"Review requested on PR #{pr.number}",
                    f"{request.user.username} requested your review on '{pr.title}'",
                    link=pr.repository.get_absolute_url(),
                    repository=repo,
                )
                # Email: notify reviewers
                try:
                    from pipeline.notifications import send_notification
                    send_notification(
                        event_type='pr_assigned',
                        subject=f"Review requested: PR #{pr.number} — {pr.title}",
                        body=(
                            f"{request.user.username} requested your review on:\n\n"
                            f"  PR #{pr.number}: {pr.title}\n"
                            f"  Repository: {repo.name}"
                        ),
                        users=list(pr.reviewers.all()),
                    )
                except Exception as _ne:
                    pass
            messages.success(request, f"Pull request #{pr.number} created.")
            return redirect('pull_request_detail', pull_request_id=pr.id)
    else:
        src = request.GET.get('source_branch')
        initial = {}
        if src:
            b = Branch.objects.filter(repository=repo, name=src).first()
            if b:
                initial['source_branch'] = b
        form = PullRequestForm(repository=repo, initial=initial)
    return render(request, 'gitmgmt/pull_request_form.html', {'form': form, 'repository': repo})


@login_required
def pull_request_detail(request, pull_request_id):
    pr = get_object_or_404(PullRequest, id=pull_request_id)
    repo = pr.repository
    comments = pr.comments.select_related('user').all()
    review_comments = pr.review_comments.select_related('user').order_by('file_path', 'line_number', 'created_at')
    reviews = pr.reviews.select_related('reviewer').all()

    # Diff
    diff = None
    rp = _repo_path(repo.name)
    try:
        with tempfile.TemporaryDirectory() as td:
            r = Repo.clone_from(rp, td)
            diff = r.git.diff(f'{pr.target_branch.name}...{pr.source_branch.name}')
    except Exception as e:
        diff = f"# Could not compute diff: {e}"

    can_merge, merge_reason = pr.can_merge(request.user)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'comment':
            form = PullRequestCommentForm(request.POST)
            if form.is_valid():
                c = form.save(commit=False)
                c.pull_request = pr
                c.user = request.user
                c.save()
                return redirect('pull_request_detail', pull_request_id=pr.id)
        elif action == 'review':
            rf = PRReviewForm(request.POST)
            if rf.is_valid():
                rev = rf.save(commit=False)
                rev.pull_request = pr
                rev.reviewer = request.user
                rev.submitted_at = timezone.now()
                rev.save()
                log_activity(request.user, 'review', f"Reviewed PR #{pr.number} [{rev.state}]", repository=repo)
                return redirect('pull_request_detail', pull_request_id=pr.id)
    else:
        form = PullRequestCommentForm()

    review_form = PRReviewForm()
    inline_form = PRReviewCommentForm()

    return render(request, 'gitmgmt/pull_request_detail.html', {
        'pull_request': pr,
        'repository': repo,
        'comments': comments,
        'review_comments': review_comments,
        'reviews': reviews,
        'comment_form': form,
        'review_form': review_form,
        'inline_form': inline_form,
        'diff': diff,
        'can_merge': can_merge,
        'merge_reason': merge_reason,
    })


@login_required
def merge_pull_request(request, pull_request_id):
    pr = get_object_or_404(PullRequest, id=pull_request_id)
    if request.method != 'POST':
        return redirect('pull_request_detail', pull_request_id=pr.id)

    can_merge, reason = pr.can_merge(request.user)
    if not can_merge:
        messages.error(request, reason)
        return redirect('pull_request_detail', pull_request_id=pr.id)

    rp = _repo_path(pr.repository.name)
    src = pr.source_branch.name
    tgt = pr.target_branch.name

    with tempfile.TemporaryDirectory() as td:
        try:
            r = Repo.clone_from(rp, td)
            r.git.fetch('--all')
            r.git.checkout('--', tgt)
            r.git.pull('origin', tgt)
            r.git.merge(f'origin/{src}', '--no-ff', '-m', f"Merge PR #{pr.number}: {pr.title}")
            push_result = subprocess.run(
                ['git', 'push', 'origin', tgt],
                cwd=td, capture_output=True, text=True
            )
            if push_result.returncode != 0:
                messages.error(request, f"Push failed: {push_result.stderr}")
                return redirect('pull_request_detail', pull_request_id=pr.id)
            pr.status = 'merged'
            pr.merged_by = request.user
            pr.merged_at = timezone.now()
            pr.save()
            log_activity(request.user, 'merge', f"Merged PR #{pr.number}: {pr.title}", repository=pr.repository)
            # Notify PR author (in-app + email)
            if pr.author and pr.author != request.user:
                notify(pr.author, 'pull_request', f"PR #{pr.number} merged",
                       f"{request.user.username} merged your PR '{pr.title}'",
                       repository=pr.repository)
                try:
                    from pipeline.notifications import send_notification
                    send_notification(
                        event_type='pr_merged',
                        subject=f"PR #{pr.number} merged — {pr.title}",
                        body=(
                            f"{request.user.username} merged your pull request:\n\n"
                            f"  PR #{pr.number}: {pr.title}\n"
                            f"  Repository: {pr.repository.name}\n"
                            f"  Merged into: {pr.target_branch.name}"
                        ),
                        users=[pr.author],
                    )
                except Exception:
                    pass
            messages.success(request, f"PR #{pr.number} merged successfully.")
        except GitCommandError as e:
            try: r.git.merge('--abort')
            except Exception: pass
            if 'CONFLICT' in str(e):
                messages.error(request, "Merge conflicts detected. Resolve them manually.")
            else:
                messages.error(request, f"Merge failed: {e}")
    return redirect('pull_request_detail', pull_request_id=pr.id)


@login_required
def close_pull_request(request, pull_request_id):
    pr = get_object_or_404(PullRequest, id=pull_request_id)
    if request.method == 'POST':
        if pr.author != request.user and pr.repository.owner != request.user and not request.user.is_staff:
            return HttpResponseForbidden()
        pr.status = 'closed'
        pr.save()
        log_activity(request.user, 'pull_request', f"Closed PR #{pr.number}", repository=pr.repository)
        messages.info(request, f"PR #{pr.number} closed.")
    return redirect('pull_request_detail', pull_request_id=pr.id)


@login_required
def reopen_pull_request(request, pull_request_id):
    pr = get_object_or_404(PullRequest, id=pull_request_id)
    if request.method == 'POST' and pr.status == 'closed':
        pr.status = 'open'
        pr.save()
        messages.info(request, f"PR #{pr.number} reopened.")
    return redirect('pull_request_detail', pull_request_id=pr.id)


@login_required
def add_inline_comment(request, pull_request_id):
    pr = get_object_or_404(PullRequest, id=pull_request_id)
    if request.method == 'POST':
        form = PRReviewCommentForm(request.POST)
        if form.is_valid():
            c = form.save(commit=False)
            c.pull_request = pr
            c.user = request.user
            c.save()
    return redirect('pull_request_detail', pull_request_id=pr.id)


# ─────────────────────────────────────────────────────────────────────────────
#  Issues
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def repository_issues(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    state = request.GET.get('state', 'open')
    label = request.GET.get('label')
    milestone_id = request.GET.get('milestone')
    assignee = request.GET.get('assignee')
    q = request.GET.get('q', '').strip()

    issues = repo.issues.filter(state=state).select_related('author', 'milestone').prefetch_related('labels', 'assignees')
    if label:
        issues = issues.filter(labels__name=label)
    if milestone_id:
        issues = issues.filter(milestone_id=milestone_id)
    if assignee:
        issues = issues.filter(assignees__username=assignee)
    if q:
        issues = issues.filter(Q(title__icontains=q) | Q(body__icontains=q))

    return render(request, 'gitmgmt/repository_issues.html', {
        'repository': repo,
        'issues': issues,
        'state': state,
        'open_count': repo.issues.filter(state='open').count(),
        'closed_count': repo.issues.filter(state='closed').count(),
        'labels': repo.labels.all(),
        'milestones': repo.milestones.filter(state='open'),
        'query': q,
    })


@login_required
def create_issue(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    if request.method == 'POST':
        form = IssueForm(request.POST, repository=repo)
        if form.is_valid():
            issue = form.save(commit=False)
            issue.repository = repo
            issue.author = request.user
            issue.save()
            form.save_m2m()
            log_activity(request.user, 'issue', f"Opened issue #{issue.number}: {issue.title}", repository=repo)
            # Notify assignees (in-app + email)
            assignees = list(issue.assignees.exclude(id=request.user.id))
            if assignees:
                notify(assignees, 'issue', f"Issue #{issue.number} assigned to you",
                       issue.title, repository=repo)
                try:
                    from pipeline.notifications import send_notification
                    send_notification(
                        event_type='issue_assigned',
                        subject=f"Issue #{issue.number} assigned to you — {issue.title}",
                        body=(
                            f"{request.user.username} assigned you to issue #{issue.number}:\n\n"
                            f"  {issue.title}\n"
                            f"  Repository: {repo.name}"
                        ),
                        users=assignees,
                    )
                except Exception:
                    pass
            # Notify watchers
            watchers = list(repo.watchers.exclude(id=request.user.id))
            if watchers:
                notify(watchers, 'issue', f"New issue #{issue.number} in {repo.name}",
                       issue.title, repository=repo)
            messages.success(request, f"Issue #{issue.number} created.")
            return redirect('issue_detail', repository_name=repo.name, issue_number=issue.number)
    else:
        form = IssueForm(repository=repo)
    return render(request, 'gitmgmt/issue_form.html', {'form': form, 'repository': repo})


@login_required
def issue_detail(request, repository_name, issue_number):
    repo = get_object_or_404(Repository, name=repository_name)
    issue = get_object_or_404(Issue, repository=repo, number=issue_number)
    comments = issue.comments.select_related('author').all()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'comment':
            form = IssueCommentForm(request.POST)
            if form.is_valid():
                c = form.save(commit=False)
                c.issue = issue
                c.author = request.user
                c.save()
                # Email: notify issue author
                if issue.author and issue.author != request.user:
                    try:
                        from pipeline.notifications import send_notification
                        send_notification(
                            event_type='issue_commented',
                            subject=f"New comment on issue #{issue.number} — {issue.title}",
                            body=(
                                f"{request.user.username} commented on your issue:\n\n"
                                f"  {c.body[:200]}\n\n"
                                f"  Issue: #{issue.number} {issue.title}\n"
                                f"  Repository: {repo.name}"
                            ),
                            users=[issue.author],
                        )
                    except Exception:
                        pass
                return redirect('issue_detail', repository_name=repo.name, issue_number=issue.number)
        elif action == 'close' and issue.state == 'open':
            issue.state = 'closed'
            issue.closed_at = timezone.now()
            issue.closed_by = request.user
            issue.save()
            log_activity(request.user, 'issue', f"Closed issue #{issue.number}", repository=repo)
            return redirect('issue_detail', repository_name=repo.name, issue_number=issue.number)
        elif action == 'reopen' and issue.state == 'closed':
            issue.state = 'open'
            issue.closed_at = None
            issue.closed_by = None
            issue.save()
            return redirect('issue_detail', repository_name=repo.name, issue_number=issue.number)
    form = IssueCommentForm()
    return render(request, 'gitmgmt/issue_detail.html', {
        'repository': repo, 'issue': issue,
        'comments': comments, 'comment_form': form,
    })


@login_required
def edit_issue(request, repository_name, issue_number):
    repo = get_object_or_404(Repository, name=repository_name)
    issue = get_object_or_404(Issue, repository=repo, number=issue_number)
    if issue.author != request.user and repo.owner != request.user and not request.user.is_staff:
        return HttpResponseForbidden()
    if request.method == 'POST':
        form = IssueForm(request.POST, instance=issue, repository=repo)
        if form.is_valid():
            form.save()
            return redirect('issue_detail', repository_name=repo.name, issue_number=issue.number)
    else:
        form = IssueForm(instance=issue, repository=repo)
    return render(request, 'gitmgmt/issue_form.html', {'form': form, 'repository': repo, 'issue': issue})


# ─────────────────────────────────────────────────────────────────────────────
#  Labels
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def label_list(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    labels = repo.labels.all()
    return render(request, 'gitmgmt/label_list.html', {'repository': repo, 'labels': labels})


@login_required
def label_create(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    if request.method == 'POST':
        form = LabelForm(request.POST)
        if form.is_valid():
            label = form.save(commit=False)
            label.repository = repo
            label.save()
            messages.success(request, f"Label '{label.name}' created.")
            return redirect('label_list', repository_name=repo.name)
    else:
        form = LabelForm()
    return render(request, 'gitmgmt/label_form.html', {'form': form, 'repository': repo})


@login_required
def label_edit(request, repository_name, label_id):
    repo = get_object_or_404(Repository, name=repository_name)
    label = get_object_or_404(Label, id=label_id, repository=repo)
    if request.method == 'POST':
        form = LabelForm(request.POST, instance=label)
        if form.is_valid():
            form.save()
            return redirect('label_list', repository_name=repo.name)
    else:
        form = LabelForm(instance=label)
    return render(request, 'gitmgmt/label_form.html', {'form': form, 'repository': repo, 'label': label})


@login_required
def label_delete(request, repository_name, label_id):
    repo = get_object_or_404(Repository, name=repository_name)
    label = get_object_or_404(Label, id=label_id, repository=repo)
    if request.method == 'POST':
        label.delete()
        messages.success(request, f"Label '{label.name}' deleted.")
    return redirect('label_list', repository_name=repo.name)


# ─────────────────────────────────────────────────────────────────────────────
#  Milestones
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def milestone_list(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    state = request.GET.get('state', 'open')
    milestones = repo.milestones.filter(state=state).order_by('due_date')
    return render(request, 'gitmgmt/milestone_list.html', {
        'repository': repo, 'milestones': milestones, 'state': state,
    })


@login_required
def milestone_create(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    if request.method == 'POST':
        form = MilestoneForm(request.POST)
        if form.is_valid():
            m = form.save(commit=False)
            m.repository = repo
            m.created_by = request.user
            m.save()
            messages.success(request, f"Milestone '{m.title}' created.")
            return redirect('milestone_list', repository_name=repo.name)
    else:
        form = MilestoneForm()
    return render(request, 'gitmgmt/milestone_form.html', {'form': form, 'repository': repo})


@login_required
def milestone_detail(request, repository_name, milestone_id):
    repo = get_object_or_404(Repository, name=repository_name)
    milestone = get_object_or_404(Milestone, id=milestone_id, repository=repo)
    issues = milestone.issues.all()
    return render(request, 'gitmgmt/milestone_detail.html', {
        'repository': repo, 'milestone': milestone, 'issues': issues,
    })


@login_required
def milestone_close(request, repository_name, milestone_id):
    repo = get_object_or_404(Repository, name=repository_name)
    milestone = get_object_or_404(Milestone, id=milestone_id, repository=repo)
    if request.method == 'POST':
        milestone.state = 'closed'
        milestone.closed_at = timezone.now()
        milestone.save()
    return redirect('milestone_list', repository_name=repo.name)


# ─────────────────────────────────────────────────────────────────────────────
#  Releases
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def release_list(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    releases = repo.releases.filter(is_draft=False).order_by('-created_at')
    drafts = repo.releases.filter(is_draft=True, created_by=request.user).order_by('-created_at')
    return render(request, 'gitmgmt/release_list.html', {
        'repository': repo, 'releases': releases, 'drafts': drafts,
    })


@login_required
def create_release(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    if request.method == 'POST':
        form = ReleaseForm(request.POST)
        if form.is_valid():
            release = form.save(commit=False)
            release.repository = repo
            release.created_by = request.user
            release.save()
            # Create git tag in the bare repo
            rp = _repo_path(repo.name)
            try:
                git_repo = Repo(rp)
                target = release.target_commitish
                if target in [h.name for h in git_repo.heads]:
                    commit = git_repo.heads[target].commit
                    git_repo.create_tag(release.tag_name, ref=commit, message=release.title)
            except Exception as e:
                logger.warning(f"Tag creation failed for {release.tag_name}: {e}")
            log_activity(request.user, 'release', f"Released {release.tag_name}", repository=repo)
            if not release.is_draft:
                watchers = list(repo.watchers.exclude(id=request.user.id))
                notify(watchers, 'release', f"New release: {release.tag_name} in {repo.name}",
                       release.title, repository=repo)
            messages.success(request, f"Release '{release.tag_name}' created.")
            return redirect('release_list', repository_name=repo.name)
    else:
        form = ReleaseForm()
    return render(request, 'gitmgmt/release_form.html', {'form': form, 'repository': repo})


@login_required
def release_detail(request, repository_name, tag_name):
    repo = get_object_or_404(Repository, name=repository_name)
    release = get_object_or_404(Release, repository=repo, tag_name=tag_name)
    return render(request, 'gitmgmt/release_detail.html', {'repository': repo, 'release': release})


# ─────────────────────────────────────────────────────────────────────────────
#  Auth / Profile
# ─────────────────────────────────────────────────────────────────────────────

def signup(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            UserProfile.objects.get_or_create(user=user)
            auth_login(request, user)
            messages.success(request, f"Welcome to RockerCI, {user.username}!")
            return redirect('repository_list')
    else:
        form = UserCreationForm()
    return render(request, 'gitmgmt/signup.html', {'form': form})


def user_logout(request):
    """Cleanly log out the user (GET & POST) and redirect to login page."""
    auth_logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect('login')


@login_required
def profile(request):
    user_profile, _ = UserProfile.objects.get_or_create(user=request.user)
    tokens = request.user.tokens.all()
    new_token_raw = None

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_profile':
            form = UserProfileForm(request.POST, request.FILES, instance=user_profile)
            if form.is_valid():
                form.save()
                messages.success(request, "Profile updated.")
                return redirect('profile')
        elif action == 'create_token':
            token_name = request.POST.get('token_name', '').strip()
            if token_name:
                token_obj, new_token_raw = PersonalAccessToken.create_token(
                    user=request.user,
                    name=token_name,
                    scopes=request.POST.get('scopes', 'repo'),
                )
                messages.success(request, f"Token '{token_name}' created. Copy it now — it won't be shown again.")
        elif action == 'delete_token':
            token_id = request.POST.get('token_id')
            request.user.tokens.filter(id=token_id).delete()
            messages.success(request, "Token deleted.")
            return redirect('profile')

    profile_form = UserProfileForm(instance=user_profile)
    return render(request, 'gitmgmt/profile.html', {
        'profile': user_profile,
        'tokens': tokens,
        'new_token': new_token_raw,
        'profile_form': profile_form,
    })


@login_required
def user_profile_view(request, username):
    target_user = get_object_or_404(User, username=username)
    user_profile, _ = UserProfile.objects.get_or_create(user=target_user)
    repos = Repository.objects.filter(
        Q(owner=target_user, visibility='public') |
        Q(owner=target_user, collaborators__user=request.user)
    ).distinct()
    activities = ActivityEvent.objects.filter(user=target_user).select_related('repository')[:20]
    return render(request, 'gitmgmt/user_profile.html', {
        'target_user': target_user,
        'user_profile': user_profile,
        'repos': repos,
        'activities': activities,
    })


# ─────────────────────────────────────────────────────────────────────────────
#  Notifications
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def notification_list(request):
    notes = request.user.notifications.all()
    unread = notes.filter(is_read=False)
    if request.method == 'POST' and request.POST.get('action') == 'mark_all_read':
        unread.update(is_read=True)
        return redirect('notification_list')
    return render(request, 'gitmgmt/notification_list.html', {
        'notifications': notes,
        'unread_count': unread.count(),
    })


@login_required
def mark_notification_read(request, notification_id):
    n = get_object_or_404(Notification, id=notification_id, user=request.user)
    n.is_read = True
    n.save()
    return redirect(n.link or 'notification_list')


@login_required
def notification_count(request):
    """JSON endpoint for the header badge."""
    count = request.user.notifications.filter(is_read=False).count()
    return JsonResponse({'count': count})


# ─────────────────────────────────────────────────────────────────────────────
#  Activity feed
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def activity_feed(request):
    """Global activity feed for repos the user has access to."""
    my_repos = Repository.objects.filter(
        Q(owner=request.user) | Q(collaborators__user=request.user) | Q(visibility='public')
    ).values_list('id', flat=True)
    events = ActivityEvent.objects.filter(repository_id__in=my_repos).select_related('user', 'repository').order_by('-created_at')[:100]
    return render(request, 'gitmgmt/activity_feed.html', {'events': events})


@login_required
def repository_activity(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    events = repo.activities.select_related('user').order_by('-created_at')[:100]
    return render(request, 'gitmgmt/repository_activity.html', {'repository': repo, 'events': events})


# ─────────────────────────────────────────────────────────────────────────────
#  Reactions
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def toggle_reaction(request, target_type, target_id, emoji):
    valid_emojis = [e for e, _ in Reaction.EMOJI_CHOICES]
    if emoji not in valid_emojis:
        return JsonResponse({'error': 'Invalid emoji'}, status=400)
    kwargs = {'user': request.user, 'emoji': emoji}
    if target_type == 'issue':
        issue = get_object_or_404(Issue, id=target_id)
        kwargs['issue'] = issue
    elif target_type == 'issue_comment':
        c = get_object_or_404(IssueComment, id=target_id)
        kwargs['issue_comment'] = c
    elif target_type == 'pr_comment':
        c = get_object_or_404(PullRequestComment, id=target_id)
        kwargs['pr_comment'] = c
    else:
        return JsonResponse({'error': 'Invalid target'}, status=400)

    existing = Reaction.objects.filter(**kwargs).first()
    if existing:
        existing.delete()
        action = 'removed'
    else:
        Reaction.objects.create(**kwargs)
        action = 'added'
    count = Reaction.objects.filter(**{k: v for k, v in kwargs.items() if k != 'user'}).count()
    return JsonResponse({'action': action, 'count': count})


# ─────────────────────────────────────────────────────────────────────────────
#  Organisations
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def organization_list(request):
    orgs = Organization.objects.filter(
        Q(owner=request.user) | Q(teams__members=request.user)
    ).distinct()
    return render(request, 'gitmgmt/organization_list.html', {'organizations': orgs})


@login_required
def create_organization(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        if not name:
            messages.error(request, "Organisation name required.")
            return render(request, 'gitmgmt/organization_form.html')
        if Organization.objects.filter(name=name).exists():
            messages.error(request, "Name already taken.")
            return render(request, 'gitmgmt/organization_form.html')
        Organization.objects.create(name=name, description=description, owner=request.user)
        return redirect('organization_list')
    return render(request, 'gitmgmt/organization_form.html')


def _get_org(org_name):
    if str(org_name).isdigit():
        found = Organization.objects.filter(Q(id=int(org_name)) | Q(name__iexact=str(org_name))).first()
        if found:
            return found
    return get_object_or_404(Organization, name__iexact=org_name)


@login_required
def organization_detail(request, org_name):
    from django.contrib.auth import get_user_model
    org = _get_org(org_name)
    teams = org.teams.prefetch_related('members').all()
    member_ids = set()
    for t in teams:
        member_ids.update(t.members.values_list('id', flat=True))
    member_ids.update(org.memberships.values_list('user_id', flat=True))
    if org.owner_id:
        member_ids.add(org.owner_id)
        
    members = list(get_user_model().objects.filter(id__in=member_ids).order_by('username'))
    
    # Map exact member roles for this organization
    member_roles = {}
    if org.owner_id:
        member_roles[org.owner_id] = 'owner'
    for mem in org.memberships.all():
        if mem.user_id not in member_roles or member_roles[mem.user_id] != 'owner':
            member_roles[mem.user_id] = mem.role or 'member'

    for u in members:
        u.org_role = member_roles.get(u.id, 'owner' if u.id == org.owner_id else 'member')

    projects = org.projects.all()
    repositories = Repository.objects.filter(
        Q(organization=org) | Q(owner=org.owner) | Q(owner__in=members)
    ).distinct().order_by('-updated_at')

    # All onboarded non-staff users in CogFocus One eligible to be added to this organization
    available_users = get_user_model().objects.filter(is_staff=False, is_superuser=False).exclude(id__in=member_ids).order_by('username')

    return render(request, 'gitmgmt/organization_detail.html', {
        'organization': org,
        'org': org,
        'projects': projects,
        'repositories': repositories,
        'repos': repositories,
        'teams': teams,
        'members': members,
        'available_users': available_users,
        'my_role': org.get_member_role(request.user),
    })


@login_required
def add_org_member(request, org_name):
    org = _get_org(org_name)
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        role = request.POST.get('role', 'member')
        if role not in ('owner', 'admin', 'member'):
            role = 'member'
        user = User.objects.filter(username=username).first()
        if user:
            from .models import OrganizationMember
            OrganizationMember.objects.update_or_create(
                organization=org, user=user, defaults={'role': role})
            team, _ = Team.objects.get_or_create(name='Members', organization=org)
            team.members.add(user)
            messages.success(request, f"{username} added to {org.name} as {role}.")
            try:
                from pipeline.notifications import send_notification
                send_notification(
                    event_type='member_added',
                    subject=f"Welcome to {org.name} on CogFocus One",
                    body=f"Hello {user.first_name or user.username},\n\nYou have been added to Organization '{org.name}' with the role '{role.title()}'.",
                    users=[user]
                )
            except Exception as notify_err:
                logger.warning(f"Failed to send member email notification: {notify_err}")
        else:
            messages.error(request, f"User '{username}' not found.")
    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect('organization_detail', org_name=org.name)


@login_required
def create_team(request, org_name):
    org = _get_org(org_name)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            Team.objects.get_or_create(name=name, organization=org)
            messages.success(request, f"Team '{name}' created.")
    return redirect('organization_detail', org_name=org.name)


@login_required
def organization_settings(request, org_name):
    """Organization settings — general, members with roles, and policies."""
    from .models import OrganizationMember
    org = _get_org(org_name)

    role = org.get_member_role(request.user)
    if role not in ('owner', 'admin'):
        messages.error(request, "You need admin access to manage organization settings.")
        return redirect('organization_detail', org_name=org.name)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_general':
            org.description = request.POST.get('description', org.description)
            org.website = request.POST.get('website', org.website)
            org.save()
            messages.success(request, "Organization details updated.")

        elif action == 'update_policies':
            visibility = request.POST.get('default_repo_visibility')
            if visibility in ('public', 'private'):
                org.default_repo_visibility = visibility
            policy = request.POST.get('project_creation_policy')
            if policy in ('owner', 'admin', 'member'):
                org.project_creation_policy = policy
            org.onboarding_notes = request.POST.get('onboarding_notes', org.onboarding_notes)
            org.save()
            messages.success(request, "Organization policies updated.")

        elif action == 'update_member_role':
            member = OrganizationMember.objects.filter(
                organization=org, id=request.POST.get('member_id')).first()
            new_role = request.POST.get('role')
            if member and new_role in ('owner', 'admin', 'member'):
                if role != 'owner' and new_role == 'owner':
                    messages.error(request, "Only the organization owner can grant the owner role.")
                else:
                    member.role = new_role
                    member.save()
                    messages.success(request, f"{member.user.username} is now {new_role}.")

        elif action == 'remove_member':
            member = OrganizationMember.objects.filter(
                organization=org, id=request.POST.get('member_id')).first()
            if member:
                if member.user == org.owner:
                    messages.error(request, "The organization owner cannot be removed.")
                else:
                    for team in org.teams.all():
                        team.members.remove(member.user)
                    member.delete()
                    messages.success(request, f"{member.user.username} removed from {org.name}.")

        return redirect('organization_settings', org_name=org.name)

    memberships = OrganizationMember.objects.filter(organization=org).select_related('user').order_by('user__username')
    return render(request, 'gitmgmt/organization_settings.html', {
        'organization': org,
        'org': org,
        'memberships': memberships,
        'my_role': role,
        'projects': org.projects.all(),
    })


# ─────────────────────────────────────────────────────────────────────────────
#  CI integration tab
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def repository_rocket_ci(request, repository_name):
    from pipeline.models import PipelineRun
    repo = get_object_or_404(Repository, name=repository_name)
    app = repo.application
    pipelines = app.pipelines.all() if app else []
    recent_runs = PipelineRun.objects.filter(
        pipeline__application=app
    ).order_by('-started_at')[:10] if app else []
    return render(request, 'gitmgmt/repository_rocket_ci.html', {
        'repository': repo, 
        'app': app,
        'project': app.project if app else None,
        'pipelines': pipelines, 
        'recent_runs': recent_runs,
    })


@login_required
def initialize_rocket_ci(request, repository_name):
    if request.method != 'POST':
        return HttpResponseForbidden()
    
    from pipeline.models import Project, Application, Pipeline
    repo = get_object_or_404(Repository, name=repository_name)
    
    if repo.application:
        messages.info(request, "Rocket CI is already initialized for this repository.")
        return redirect('repository_rocket_ci', repository_name=repo.name)

    # Auto-initialize
    project, _ = Project.objects.get_or_create(name=repo.name)
    app, _ = Application.objects.get_or_create(
        name=f"{repo.name.lower()}-app",
        project=project,
        defaults={'linked_repository': repo}
    )
    
    if not repo.application:
        repo.application = app
        repo.save(update_fields=['application'])

    # Create default pipeline
    Pipeline.objects.get_or_create(
        name=f"{repo.name.lower()}-ci",
        application=app,
        defaults={
            'monitored_branch': repo.default_branch or 'main',
            'yaml_path': 'rockerci.yaml'
        }
    )

    messages.success(request, f"Rocket CI initialized! Linked to project {project.name}.")
    return redirect('repository_rocket_ci', repository_name=repo.name)



# ─────────────────────────────────────────────────────────────────────────────
#  Search
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def global_search(request):
    q = request.GET.get('q', '').strip()
    repos = issues = prs = []
    if q:
        repos = Repository.objects.filter(
            Q(name__icontains=q) | Q(description__icontains=q),
            Q(visibility='public') | Q(owner=request.user)
        )[:10]
        issues = Issue.objects.filter(
            Q(title__icontains=q) | Q(body__icontains=q),
            Q(repository__visibility='public') | Q(repository__owner=request.user)
        )[:10]
        prs = PullRequest.objects.filter(
            Q(title__icontains=q) | Q(description__icontains=q),
            Q(repository__visibility='public') | Q(repository__owner=request.user)
        )[:10]
    return render(request, 'gitmgmt/search_results.html', {
        'query': q, 'repos': repos, 'issues': issues, 'prs': prs,
    })


def global_search_api(request):
    q = request.GET.get('q', '').strip()
    results = []

    try:
        from pipeline.models import Project, Application, Pipeline
    except ImportError:
        Project = Application = Pipeline = None

    user = request.user if request.user.is_authenticated else None

    if user:
        repo_access = Q(visibility='public') | Q(owner=user)
        issue_access = Q(repository__visibility='public') | Q(repository__owner=user)
    else:
        repo_access = Q(visibility='public')
        issue_access = Q(repository__visibility='public')

    if q:
        # 1. Repositories (search name or description)
        for r in Repository.objects.filter(
            Q(name__icontains=q) | Q(description__icontains=q),
            repo_access
        ).distinct()[:5]:
            results.append({
                'category': 'Repositories',
                'title': r.name,
                'url': f'/repositories/{r.name}/',
                'icon': 'ph-git-branch',
                'sub': r.description or f"Owner: {r.owner.username}"
            })

        # 2. Projects
        if Project:
            for p in Project.objects.filter(Q(name__icontains=q) | Q(description__icontains=q))[:5]:
                results.append({
                    'category': 'Projects',
                    'title': p.name,
                    'url': f'/ci/projects/{p.name}/',
                    'icon': 'ph-tree-structure',
                    'sub': p.description or f"Org: {p.organization.name if p.organization else 'Global'}"
                })

        # 3. Organizations
        for o in Organization.objects.filter(Q(name__icontains=q) | Q(description__icontains=q))[:5]:
            results.append({
                'category': 'Organizations',
                'title': o.name,
                'url': f'/organizations/{o.id}/',
                'icon': 'ph-buildings',
                'sub': f"Owner: {o.owner.username}"
            })

        # 4. Applications
        if Application:
            for a in Application.objects.filter(name__icontains=q)[:5]:
                results.append({
                    'category': 'Applications',
                    'title': a.name,
                    'url': f'/ci/applications/{a.name}/',
                    'icon': 'ph-cube',
                    'sub': f"Project: {a.project.name if a.project else 'Global'}"
                })

        # 5. Pipelines
        if Pipeline:
            for pipe in Pipeline.objects.filter(name__icontains=q)[:5]:
                results.append({
                    'category': 'Pipelines',
                    'title': pipe.name,
                    'url': f'/ci/pipeline/{pipe.id}/',
                    'icon': 'ph-rocket-launch',
                    'sub': f"App: {pipe.application.name if pipe.application else 'Default'}"
                })

        # 6. Issues
        for i in Issue.objects.filter(
            Q(title__icontains=q) | Q(body__icontains=q),
            issue_access
        )[:4]:
            results.append({
                'category': 'Issues',
                'title': f"#{i.id} {i.title}",
                'url': f'/repositories/{i.repository.name}/issues/',
                'icon': 'ph-warning-circle',
                'sub': f"Repo: {i.repository.name}"
            })

        # 7. Pull Requests
        for pr in PullRequest.objects.filter(
            Q(title__icontains=q) | Q(description__icontains=q),
            issue_access
        )[:4]:
            results.append({
                'category': 'Pull Requests',
                'title': f"#{pr.id} {pr.title}",
                'url': f'/repositories/{pr.repository.name}/pull-requests/{pr.id}/',
                'icon': 'ph-git-pull-request',
                'sub': f"Repo: {pr.repository.name}"
            })
    else:
        # Default top suggestions when focused with empty query
        for r in Repository.objects.filter(repo_access).order_by('-updated_at')[:4]:
            results.append({
                'category': 'Recent Repositories',
                'title': r.name,
                'url': f'/repositories/{r.name}/',
                'icon': 'ph-git-branch',
                'sub': r.description or f"Owner: {r.owner.username}"
            })
        if Project:
            for p in Project.objects.all()[:3]:
                results.append({
                    'category': 'Recent Projects',
                    'title': p.name,
                    'url': f'/ci/projects/{p.name}/',
                    'icon': 'ph-tree-structure',
                    'sub': p.description or f"Org: {p.organization.name if p.organization else 'Global'}"
                })

    return JsonResponse({'results': results})
