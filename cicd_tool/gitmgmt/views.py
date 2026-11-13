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
import zipfile
import shutil

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate as django_authenticate
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import (FileResponse, HttpResponse, HttpResponseForbidden,
                          HttpResponseServerError, JsonResponse)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from git import GitCommandError, Repo

from .forms import (IssueCommentForm, IssueForm, LabelForm, MilestoneForm,
                     PRReviewCommentForm, PRReviewForm, PullRequestCommentForm,
                     PullRequestForm, ReleaseForm, RepositoryForm,
                     UploadFileForm, UserProfileForm)
from .models import (ActivityEvent, Branch, BranchProtectionRule, Collaborator,
                      Commit, Issue, IssueComment, Label, Milestone, Notification,
                      Organization, PersonalAccessToken, PRReview,
                      PRReviewComment, PullRequest, PullRequestComment,
                      Reaction, Release, Repository, RepositoryAccessRequest,
                      Team, UserProfile, log_activity, notify)

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

def _validate_branch_name(name):
    """Validate git branch naming rules."""
    if not name or not isinstance(name, str):
        return False
    name = name.strip()
    if not name or len(name) > 250:
        return False
    if name.startswith(('/', '-', '.')) or name.endswith(('/', '.')):
        return False
    # Disallow invalid git branch chars: whitespace, ~, ^, :, ?, *, [, \, @{, or ..
    if re.search(r'[\s~^:?*\[\\@{}]|\.\.', name):
        return False
    return True

def _rmtree_force(path):
    """shutil.rmtree that safely clears read-only flags on Windows git objects."""
    import shutil
    import stat
    def onerror(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    if os.path.exists(path):
        try:
            shutil.rmtree(path, onerror=onerror)
        except Exception:
            try:
                shutil.rmtree(path, ignore_errors=True)
            except Exception:
                pass


def sync_repository_branches(repo):
    """Sync branches from bare git repo on disk into Branch DB model."""
    try:
        rp = _repo_path(repo.name)
        if not os.path.exists(rp):
            return
        git_repo = Repo(rp)
        disk_heads = [h.name for h in git_repo.heads]
        if not disk_heads:
            try:
                head_name = git_repo.head.reference.name
                disk_heads = [head_name]
            except Exception:
                pass

        default_branch = repo.default_branch or 'main'
        if disk_heads and default_branch not in disk_heads:
            if 'main' in disk_heads:
                default_branch = 'main'
            elif 'master' in disk_heads:
                default_branch = 'master'
            else:
                default_branch = disk_heads[0]
            repo.default_branch = default_branch
            repo.save(update_fields=['default_branch'])

        for b_name in disk_heads:
            Branch.objects.get_or_create(
                repository=repo,
                name=b_name,
                defaults={'is_default': (b_name == default_branch)}
            )

        if not disk_heads:
            Branch.objects.get_or_create(
                repository=repo,
                name=default_branch,
                defaults={'is_default': True}
            )
    except Exception as e:
        logger.warning(f"Failed to sync branches for {repo.name}: {e}")


def sync_repository_commits(repo, max_commits_per_branch=50):
    """Sync git history from disk into Commit model."""
    try:
        rp = _repo_path(repo.name)
        if not os.path.exists(rp):
            return
        gr = Repo(rp)
        for h in gr.heads:
            branch_obj, _ = Branch.objects.get_or_create(repository=repo, name=h.name)
            for c in gr.iter_commits(h.name, max_count=max_commits_per_branch):
                if not Commit.objects.filter(hash=c.hexsha).exists():
                    author_user = User.objects.filter(
                        Q(email__iexact=c.author.email) | Q(username__iexact=c.author.name)
                    ).first()
                    commit_obj = Commit.objects.create(
                        branch=branch_obj,
                        message=c.message,
                        author=author_user,
                        author_name=c.author.name or '',
                        author_email=c.author.email or '',
                        hash=c.hexsha
                    )
                    Commit.objects.filter(id=commit_obj.id).update(created_at=c.committed_datetime)
    except Exception as e:
        logger.warning(f"Failed to sync commits for {repo.name}: {e}")



def sync_disk_repositories(default_user=None):
    """Scan disk repository directory and ensure every .git bare repo has a DB Repository record."""
    try:
        base_dir = _get_repo_base_path()
        if not os.path.exists(base_dir):
            return
        owner = default_user
        if not owner or not getattr(owner, 'is_authenticated', False):
            owner = User.objects.filter(is_superuser=True).first() or User.objects.first()

        default_org = Organization.objects.filter(name='CogFocus').first() or Organization.objects.first()

        for entry in os.listdir(base_dir):
            if entry.endswith('.git'):
                repo_name = entry[:-4]
                if not repo_name or entry.startswith('.'):
                    continue
                repo = Repository.objects.filter(name__iexact=repo_name).first()
                if not repo:
                    repo = Repository.objects.create(
                        name=repo_name,
                        owner=owner,
                        organization=default_org,
                        visibility='private',
                        default_branch='main'
                    )
                sync_repository_branches(repo)
                sync_repository_commits(repo)
    except Exception as e:
        logger.warning(f"Failed to sync disk repositories: {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  Repository list / create
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def repository_list(request):
    sync_disk_repositories(request.user)

    tab = request.GET.get('tab', 'all').strip().lower()
    query = request.GET.get('q', '').strip()

    # Determine accessible repositories:
    # 1. Superusers and staff see ALL repositories across the enterprise
    # 2. Regular users see: owned, collaborator, member/owner of repository organization, or public
    if request.user.is_superuser or request.user.is_staff:
        accessible_repos = Repository.objects.all().distinct()
    else:
        accessible_repos = Repository.objects.filter(
            Q(owner=request.user) |
            Q(collaborators__user=request.user) |
            Q(organization__memberships__user=request.user) |
            Q(organization__owner=request.user) |
            Q(organization__teams__members=request.user) |
            Q(visibility='public')
        ).distinct()

    if tab == 'org':
        repos = accessible_repos.filter(
            Q(organization__memberships__user=request.user) |
            Q(organization__owner=request.user) |
            Q(organization__isnull=False)
        ).distinct()
    elif tab == 'mine':
        repos = accessible_repos.filter(
            Q(owner=request.user) | Q(collaborators__user=request.user)
        ).distinct()
    elif tab == 'public':
        repos = accessible_repos.filter(visibility='public')
    elif tab == 'private':
        repos = accessible_repos.filter(visibility='private')
    elif tab == 'favorites':
        repos = accessible_repos.filter(stars=request.user)
    else:
        repos = accessible_repos

    if query:
        repos = repos.filter(Q(name__icontains=query) | Q(description__icontains=query))

    favorites = accessible_repos.filter(stars=request.user)

    # Sync branches for visible repositories
    for r in repos[:30]:
        sync_repository_branches(r)

    return render(request, 'gitmgmt/repository_list.html', {
        'repositories': repos,
        'favorites': favorites,
        'query': query,
        'tab': tab,
        'is_admin': request.user.is_superuser or request.user.is_staff,
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
    if request.method == 'POST':
        form = RepositoryForm(request.POST)
        if form.is_valid():
            repo = form.save(commit=False)
            repo.owner = request.user
            try:
                _initialize_repository(repo.name, user=request.user)
                repo.save()
                # Create default Branch record and default labels
                branch = Branch.objects.create(repository=repo, name=repo.default_branch, is_default=True)
                _create_default_labels(repo)
                log_activity(request.user, 'push', f"Created repository {repo.name}", repository=repo)
                messages.success(request, f"Repository '{repo.name}' created.")
                return redirect('repository_detail', repository_name=repo.name)
            except Exception as e:
                form.add_error(None, f"Failed to initialize repository: {e}")
    else:
        form = RepositoryForm()
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
    branches, files, folders, current_branch = [], [], [], None
    last_commit_hash = last_commit_message = readme_content = error_message = None
    current_path = request.GET.get('path', '').strip('/')
    if '..' in current_path:
        current_path = ''
    parent_path = None
    breadcrumbs = [{'name': repo.name, 'path': ''}]

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
            root_tree = branch_head.commit.tree
            target_tree = root_tree

            if current_path:
                try:
                    target_tree = root_tree[current_path]
                    if target_tree.type != 'tree':
                        target_tree = root_tree
                        current_path = ''
                except (KeyError, Exception):
                    target_tree = root_tree
                    current_path = ''

            # Build breadcrumbs and parent path
            if current_path:
                parts = current_path.split('/')
                accum = ''
                for p in parts:
                    accum = f"{accum}/{p}".strip('/')
                    breadcrumbs.append({'name': p, 'path': accum})
                parent_dir = os.path.dirname(current_path).replace(os.sep, '/')
                parent_path = parent_dir  # '' for root or relative path to parent

            # Iterate direct children of target_tree
            for item in target_tree:
                if item.type == 'tree':
                    folders.append({
                        'type': 'tree',
                        'name': item.name,
                        'path': item.path,
                    })
                elif item.type == 'blob':
                    sz = item.size
                    if sz < 1024:
                        sz_str = f"{sz} B"
                    elif sz < 1024 * 1024:
                        sz_str = f"{sz / 1024:.1f} KB"
                    else:
                        sz_str = f"{sz / (1024 * 1024):.1f} MB"
                    ext = os.path.splitext(item.name)[1].lower()
                    files.append({
                        'type': 'blob',
                        'name': item.name,
                        'path': item.path,
                        'dirname': os.path.dirname(item.path),
                        'size': sz,
                        'size_display': sz_str,
                        'ext': ext,
                    })

            folders.sort(key=lambda x: x['name'].lower())
            files.sort(key=lambda x: x['name'].lower())

            last_commit = branch_head.commit
            last_commit_hash = last_commit.hexsha
            last_commit_message = last_commit.message.strip()
            try:
                commit_count = len(list(git_repo.iter_commits(current_branch, max_count=500)))
            except Exception:
                commit_count = Commit.objects.filter(branch__name=current_branch, branch__repository=repo).count()

            # README check: current target folder first, then root
            readme_candidates = ('README.md', 'readme.md', 'Readme.md', 'README', 'readme')
            for name in readme_candidates:
                if name in target_tree:
                    readme_content = target_tree[name].data_stream.read().decode('utf-8', errors='replace')
                    break
            if not readme_content and not current_path:
                for name in readme_candidates:
                    if name in root_tree:
                        readme_content = root_tree[name].data_stream.read().decode('utf-8', errors='replace')
                        break
            git_repo.close()
        else:
            commit_count = 0
            if git_repo:
                git_repo.close()
    except Exception as e:
        error_message = str(e)
        commit_count = 0

    is_starred = request.user in repo.stars.all()
    is_watching = request.user in repo.watchers.all()
    user_role = None
    if repo.owner == request.user:
        user_role = 'owner'
    else:
        collab = repo.collaborators.filter(user=request.user).first()
        if collab:
            user_role = collab.role

    can_clone = repo.user_can_clone(request.user)
    can_push = repo.user_can_push(request.user)
    is_owner = (repo.owner == request.user)
    pending_request = repo.access_requests.filter(user=request.user, status='pending').first()
    pending_count = repo.pending_access_requests_count if (is_owner or request.user.is_superuser or request.user.is_staff) else 0

    return render(request, 'gitmgmt/repository_detail.html', {
        'repository': repo,
        'branches': branches,
        'current_branch': current_branch,
        'folders': folders,
        'files': files,
        'current_path': current_path,
        'parent_path': parent_path,
        'breadcrumbs': breadcrumbs,
        'commit_count': commit_count,
        'last_commit_hash': last_commit_hash,
        'last_commit_message': last_commit_message,
        'readme_content': readme_content,
        'error_message': error_message,
        'is_starred': is_starred,
        'is_watching': is_watching,
        'user_role': user_role,
        'can_clone': can_clone,
        'can_push': can_push,
        'is_owner': is_owner,
        'pending_access_request': pending_request,
        'pending_requests_count': pending_count,
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
    if hasattr(repo, 'application') and repo.application and getattr(repo.application, 'project', None):
        role = repo.application.project.get_member_role(user)
        if role in ('maintainer', 'admin'):
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

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_settings':
            new_name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            visibility = request.POST.get('visibility', repo.visibility)
            default_branch = request.POST.get('default_branch', repo.default_branch).strip()

            if new_name and new_name != repo.name:
                if Repository.objects.filter(name=new_name).exists():
                    messages.error(request, f"A repository named '{new_name}' already exists.")
                    return redirect('repository_settings', repository_name=repo.name)
                # Safely rename bare repository folder on disk
                old_path = _repo_path(repo.name)
                new_path = _repo_path(new_name)
                if os.path.exists(old_path):
                    try:
                        os.rename(old_path, new_path)
                    except Exception as err:
                        messages.error(request, f"Failed to rename repository on disk: {err}")
                        return redirect('repository_settings', repository_name=repo.name)
                repo.name = new_name

            repo.description = description
            if visibility in ('public', 'private'):
                repo.visibility = visibility
            if default_branch:
                repo.default_branch = default_branch
            repo.save()
            messages.success(request, "Repository settings saved successfully.")
            return redirect('repository_settings', repository_name=repo.name)

    sync_repository_branches(repo)
    collaborators = repo.collaborators.select_related('user').all()
    branches = repo.branches.all()
    pending_requests = repo.access_requests.filter(status='pending').select_related('user').order_by('-created_at')
    return render(request, 'gitmgmt/repository_settings.html', {
        'repository': repo,
        'collaborators': collaborators,
        'branches': branches,
        'pending_requests': pending_requests,
        'can_manage_repo': True,
        'is_admin': request.user.is_superuser or request.user.is_staff,
    })


@login_required
def delete_repository(request, repository_name):
    """Admin-only deletion of repository and its disk bare repo."""
    repo = get_object_or_404(Repository, name=repository_name)
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "Access Denied: Only administrators can delete repositories.")
        return redirect('repository_settings', repository_name=repo.name)

    if request.method == 'POST':
        confirm_name = request.POST.get('confirm_name', '').strip()
        if confirm_name != repo.name:
            messages.error(request, f"Confirmation name mismatch. Please type '{repo.name}' exactly to confirm.")
            return redirect('repository_settings', repository_name=repo.name)

        # Remove bare repo from disk
        disk_path = _repo_path(repo.name)
        _rmtree_force(disk_path)

        repo_name = repo.name
        repo.delete()
        messages.success(request, f"Repository '{repo_name}' has been permanently deleted.")
        return redirect('repository_list')

    return redirect('repository_settings', repository_name=repo.name)


@login_required
def add_collaborator(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    if not _user_can_manage_repo(request.user, repo):
        messages.error(request, "Access Denied: Permission required to manage collaborators.")
        return redirect('repository_detail', repository_name=repo.name)
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        role = request.POST.get('role', 'read')
        from django.db.models import Q
        user = User.objects.filter(
            Q(username__iexact=username) | Q(email__iexact=username)
        ).first()

        if not user and '@' in username and (request.user.is_superuser or request.user.is_staff or repo.owner == request.user):
            email_addr = username.lower()
            base_u = email_addr.split('@')[0].replace('.', '_').replace('-', '_')
            clean_u = base_u
            c = 1
            while User.objects.filter(username__iexact=clean_u).exists():
                clean_u = f"{base_u}_{c}"
                c += 1
            user = User.objects.create(
                username=clean_u,
                email=email_addr,
                first_name=base_u.replace('_', ' ').title()
            )
            user.set_unusable_password()
            user.save()
            UserProfile.objects.get_or_create(user=user)
            messages.info(request, f"Created new account for '{email_addr}' (Username: {user.username}).")
        elif not user and len(username) >= 4:
            user = User.objects.filter(
                Q(username__istartswith=username[:4]) | Q(email__istartswith=username[:4])
            ).first()

        if user:
            from .models import Collaborator, RepositoryAccessRequest
            Collaborator.objects.update_or_create(repository=repo, user=user, defaults={'role': role})
            # Also sync any alternative account with matching email or username prefix
            similar_users = User.objects.filter(
                Q(email__iexact=user.email) | Q(username__iexact=user.username)
            ).exclude(id=user.id)
            for su in similar_users:
                Collaborator.objects.update_or_create(repository=repo, user=su, defaults={'role': role})

            # Auto-approve any pending access requests for this user or matching email on this repo
            req_q = Q(user=user)
            if user.email:
                req_q |= Q(user__email__iexact=user.email)
            for su in similar_users:
                req_q |= Q(user=su)
            pending_reqs = RepositoryAccessRequest.objects.filter(req_q, repository=repo, status='pending')
            for pr in pending_reqs:
                pr.status = 'approved'
                pr.reviewed_by = request.user
                pr.reviewed_at = timezone.now()
                pr.save()

            messages.success(request, f"Added {user.username} as collaborator ({role}). Access granted and pending requests approved.")
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
    sync_repository_branches(repo)
    rp = _repo_path(repo.name)
    if request.method == 'POST':
        branch_name = request.POST.get('branch_name', '').strip()
        source = request.POST.get('source_branch', repo.default_branch or 'main').strip()
        if not branch_name or not _validate_branch_name(branch_name):
            messages.error(request, "Invalid branch name. Names cannot contain spaces or special git control characters.")
            return redirect('repository_detail', repository_name=repo.name)
        try:
            git_repo = Repo(rp)
            disk_heads = [h.name for h in git_repo.heads]
            if branch_name in disk_heads:
                messages.error(request, f"Branch '{branch_name}' already exists.")
            elif source not in disk_heads:
                # If source doesn't exist, try HEAD or default
                if git_repo.heads:
                    ref_commit = git_repo.head.commit
                    git_repo.create_head(branch_name, ref_commit)
                    Branch.objects.get_or_create(repository=repo, name=branch_name)
                    log_activity(request.user, 'branch', f"Created branch {branch_name}", repository=repo)
                    messages.success(request, f"Branch '{branch_name}' created.")
                else:
                    messages.error(request, f"Source branch '{source}' not found.")
            else:
                git_repo.create_head(branch_name, git_repo.heads[source].commit)
                Branch.objects.get_or_create(repository=repo, name=branch_name)
                log_activity(request.user, 'branch', f"Created branch {branch_name}", repository=repo)
                messages.success(request, f"Branch '{branch_name}' created from '{source}'.")
        except Exception as e:
            messages.error(request, f"Error creating branch: {e}")
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
    if not _user_can_manage_repo(request.user, repo) and not request.user.is_superuser:
        return HttpResponseForbidden()
    branch = get_object_or_404(Branch, repository=repo, name=branch_name)
    rule, _ = BranchProtectionRule.objects.get_or_create(branch=branch, defaults={'created_by': request.user})
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'disable':
            branch.is_protected = False
            branch.save()
            messages.info(request, f"Branch protection disabled for '{branch.name}'.")
            return redirect('repository_settings', repository_name=repo.name)

        is_protected = 'is_protected' in request.POST
        if not is_protected:
            branch.is_protected = False
            branch.save()
            messages.info(request, f"Branch protection disabled for '{branch.name}'.")
            return redirect('repository_settings', repository_name=repo.name)

        rule.require_pull_request = 'require_pull_request' in request.POST
        rule.required_approvals = max(1, int(request.POST.get('required_approvals', 1)))
        rule.dismiss_stale_reviews = 'dismiss_stale_reviews' in request.POST
        rule.require_status_checks = 'require_status_checks' in request.POST
        rule.allow_force_push = 'allow_force_push' in request.POST
        rule.restrict_pushes = 'restrict_pushes' in request.POST
        rule.save()
        branch.is_protected = True
        branch.save()
        messages.success(request, f"Branch protection rule saved for '{branch.name}'.")
        return redirect('repository_settings', repository_name=repo.name)
    return render(request, 'gitmgmt/branch_protection.html', {'repository': repo, 'branch': branch, 'rule': rule})


# ─────────────────────────────────────────────────────────────────────────────
#  File operations
# ─────────────────────────────────────────────────────────────────────────────

def _get_head_commits(rp):
    """Return {branch_name: commit_hexsha} snapshot for a bare repository."""
    try:
        r = Repo(rp)
        try:
            return {h.name: h.commit.hexsha for h in r.heads}
        finally:
            r.close()
    except Exception:
        return {}


def _trigger_repo_pipelines_on_push(repo_name, branch, trigger_source='push'):
    """Trigger configured YAML or step-based pipelines when code changes on a monitored branch."""
    try:
        from pipeline.models import Application, Pipeline, PipelineRun, PipelineStep, Project, YamlFileVersion
        from pipeline.utils import sync_steps_from_yaml

        rp = _repo_path(repo_name)
        git_repo = Repo(rp)
        try:
            repo_obj = Repository.objects.filter(name=repo_name).first()
            app = Application.objects.filter(repository__name=repo_name).first()
            if not app:
                app = Application.objects.filter(name__iexact=repo_name).first()
                if app and repo_obj and not repo_obj.application:
                    repo_obj.application = app
                    repo_obj.save(update_fields=['application'])
            if not app and repo_obj:
                proj = Project.objects.filter(name__iexact=repo_name).first()
                if not proj:
                    proj = Project.objects.first()
                if proj:
                    app = Application.objects.create(name=repo_name, project=proj)
                    repo_obj.application = app
                    repo_obj.save(update_fields=['application'])

            if not app:
                return

            if branch not in [h.name for h in git_repo.heads]:
                return

            commit = git_repo.heads[branch].commit
            tree = commit.tree

            pipelines = list(app.pipelines.all())
            if not pipelines:
                default_pipe = Pipeline.objects.create(
                    name=f"{repo_name}-ci",
                    application=app,
                    monitored_branch=branch or (repo_obj.default_branch if repo_obj else 'main'),
                    yaml_path='rockerci.yaml',
                )
                pipelines = [default_pipe]

            for pipeline in pipelines:
                monitored = (pipeline.monitored_branch or '').strip()
                if monitored and monitored != '*' and monitored != branch:
                    continue

                yp = (pipeline.yaml_path or '').strip()
                candidates = [yp] if yp else []
                for alt in ('rockerci.yaml', '.rocketci.yml', 'rocketci.yml', '.rockerci.yaml', '.rockerci.yml'):
                    if alt not in candidates:
                        candidates.append(alt)

                matched_yaml = next((c for c in candidates if c in tree), None)
                n_steps = 0
                if matched_yaml:
                    yaml_content = tree[matched_yaml].data_stream.read().decode('utf-8', errors='replace')
                    n_steps = sync_steps_from_yaml(pipeline, yaml_content)
                    if n_steps > 0:
                        version = YamlFileVersion.objects.filter(pipeline=pipeline).count() + 1
                        YamlFileVersion.objects.create(
                            pipeline=pipeline, version_number=version, yaml_content=yaml_content
                        )
                else:
                    n_steps = pipeline.pipelinestep_set.count()

                if n_steps <= 0:
                    # Provide an automatic baseline verification step for repos without YAML yet
                    PipelineStep.objects.create(
                        pipeline=pipeline,
                        name=f"Verify {repo_name} on branch {branch}",
                        command=f"echo '[CI] Executing build check for {repo_name} @ {branch}' && git status",
                        condition='on_success',
                    )
                    n_steps = 1

                author_name = (commit.author.name if commit.author else None) or 'Developer'
                summary = (commit.message or '').strip().splitlines()[0] if commit.message else ''
                PipelineRun.objects.create(
                    pipeline=pipeline,
                    status='pending',
                    log=(
                        f"[TRIGGER] {trigger_source} on branch '{branch}' "
                        f"| commit {commit.hexsha[:10]} by {author_name}"
                        + (f" — {summary}" if summary else "")
                        + f" ({n_steps} step(s))"
                    ),
                )
                logger.info(f"Triggered pipeline '{pipeline.name}' for {repo_name}@{branch} ({n_steps} steps)")
        finally:
            git_repo.close()
    except Exception as e:
        logger.error(f"Failed to trigger repo pipelines on push for {repo_name}@{branch}: {e}")


@login_required
def upload_file(request, repository_name):
    """
    Project Structure & Folder-Based Code Upload View.
    Supports:
      • Recursive folder uploads with full directory hierarchies (webkitdirectory)
      • Drag & drop of folders and multiple files
      • ZIP project archive extraction with directory preservation
      • Automatic common root stripping (places project root in repo root)
      • Atomic Git commit and push to monitored branches with CI triggering
    """
    repo = get_object_or_404(Repository, name=repository_name)
    rp = _repo_path(repo.name)

    branches = []
    try:
        gr = Repo(rp)
        branches = [b.name for b in gr.heads]
        gr.close()
    except Exception:
        pass

    current_branch = (request.POST.get('branch') or request.GET.get('branch') or '').strip()
    if request.method == 'GET':
        if not current_branch or (branches and current_branch not in branches):
            current_branch = repo.default_branch if (repo.default_branch in branches) else (branches[0] if branches else 'main')
    else:
        if not current_branch:
            current_branch = repo.default_branch or 'main' 

    target_path = (request.POST.get('target_path') or request.GET.get('path') or '').strip('/')
    if '..' in target_path:
        target_path = ''

    if request.method == 'POST':
        # 1. Authorization & Permissions
        if not repo.user_can_push(request.user):
            msg = "Permission denied: you cannot push to this repository."
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('format') == 'json':
                return JsonResponse({'status': 'error', 'error': msg}, status=403)
            messages.error(request, msg)
            return redirect('repository_detail', repository_name=repo.name)

        # 2. Branch Protection (Enforced for non-owners/non-admins; owners and superusers can push)
        target_b = Branch.objects.filter(repository=repo, name=current_branch).first()
        is_admin_or_owner = request.user.is_superuser or request.user.is_staff or (repo.owner == request.user)
        if target_b and target_b.is_protected and not is_admin_or_owner:
            rule = getattr(target_b, 'protection_rule', None)
            if rule and (rule.require_pull_request or rule.restrict_pushes):
                msg = f"Cannot commit directly to protected branch '{current_branch}'. Direct commits are blocked by branch protection. Please upload to a feature branch and open a Pull Request."
                if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('format') == 'json':
                    return JsonResponse({'status': 'error', 'error': msg}, status=403)
                messages.error(request, msg)
                return redirect('repository_detail', repository_name=repo.name)

        if not _validate_branch_name(current_branch):
            msg = "Invalid branch name."
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('format') == 'json':
                return JsonResponse({'status': 'error', 'error': msg}, status=400)
            messages.error(request, msg)
            return redirect('repository_detail', repository_name=repo.name)

        # 3. Collect Files
        uploaded_files = request.FILES.getlist('files')
        if not uploaded_files:
            uploaded_files = request.FILES.getlist('file')
        if not uploaded_files:
            single = request.FILES.get('file') or request.FILES.get('archive')
            if single:
                uploaded_files = [single]

        if not uploaded_files:
            msg = "No files or folder were selected to upload."
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('format') == 'json':
                return JsonResponse({'status': 'error', 'error': msg}, status=400)
            messages.error(request, msg)
            return redirect(f"{reverse('upload_file', kwargs={'repository_name': repo.name})}?branch={current_branch}&path={target_path}")

        file_paths = request.POST.getlist('file_paths')
        paths_json = request.POST.get('paths_json', '').strip()
        if paths_json:
            try:
                pj = json.loads(paths_json)
                if isinstance(pj, list) and len(pj) == len(uploaded_files):
                    file_paths = pj
            except Exception:
                pass

        strip_root = request.POST.get('strip_root', '1') in ('1', 'true', 'on', 'yes')
        extract_zip = request.POST.get('extract_zip', '1') in ('1', 'true', 'on', 'yes')
        commit_msg = request.POST.get('commit_message', '').strip()

        # Check if all relative paths share a single common top-level directory
        common_prefix = ''
        if strip_root and file_paths:
            normalized = [p.replace(os.sep, '/').lstrip('/') for p in file_paths if p]
            if normalized:
                p0 = normalized[0].split('/')
                if len(p0) > 1:
                    cand = p0[0] + '/'
                    if all(p.startswith(cand) for p in normalized):
                        common_prefix = cand

        total_files_written = 0
        written_directories = set()

        try:
            with tempfile.TemporaryDirectory() as td:
                r = Repo.clone_from(rp, td)
                r.git.fetch('--all')
                remote = r.git.branch('-r')
                if f'origin/{current_branch}' in remote:
                    r.git.checkout('-B', current_branch, f'origin/{current_branch}')
                else:
                    r.git.checkout('-b', current_branch)

                dest_base = os.path.join(td, target_path) if target_path else td
                os.makedirs(dest_base, exist_ok=True)

                for idx, f in enumerate(uploaded_files):
                    # Check ZIP archive extraction
                    if f.name.lower().endswith('.zip') and extract_zip:
                        with zipfile.ZipFile(f) as zf:
                            z_entries = [m for m in zf.namelist() if not m.endswith('/')]
                            z_prefix = ''
                            if strip_root and z_entries:
                                zp0 = z_entries[0].split('/')
                                if len(zp0) > 1:
                                    cand = zp0[0] + '/'
                                    if all(e.startswith(cand) for e in z_entries):
                                        z_prefix = cand

                            for member in zf.infolist():
                                if member.is_dir():
                                    continue
                                m_name = member.filename
                                # Ignore junk files
                                if any(p in ('__MACOSX', '.DS_Store', 'Thumbs.db') or p.startswith('.git') for p in m_name.split('/')):
                                    continue
                                rel = m_name[len(z_prefix):] if (z_prefix and m_name.startswith(z_prefix)) else m_name
                                rel = os.path.normpath(rel.replace(os.sep, '/')).lstrip('/')
                                if not rel or rel.startswith('..'):
                                    continue
                                target_dest = os.path.abspath(os.path.join(dest_base, rel))
                                if not target_dest.startswith(os.path.abspath(td)):
                                    continue
                                os.makedirs(os.path.dirname(target_dest), exist_ok=True)
                                written_directories.add(os.path.dirname(target_dest))
                                with zf.open(member) as src_fh, open(target_dest, 'wb') as dst_fh:
                                    shutil.copyfileobj(src_fh, dst_fh)
                                total_files_written += 1
                        continue

                    # Regular file / directory member
                    rel = file_paths[idx] if (idx < len(file_paths) and file_paths[idx]) else f.name
                    rel = rel.replace(os.sep, '/').lstrip('/')
                    if common_prefix and rel.startswith(common_prefix):
                        rel = rel[len(common_prefix):]
                    rel = os.path.normpath(rel).lstrip('/')
                    if not rel or rel.startswith('..'):
                        rel = os.path.basename(f.name)

                    if any(p in ('__MACOSX', '.DS_Store', 'Thumbs.db') or p.startswith('.git') for p in rel.split('/')):
                        continue

                    target_dest = os.path.abspath(os.path.join(dest_base, rel))
                    if not target_dest.startswith(os.path.abspath(td)):
                        continue

                    os.makedirs(os.path.dirname(target_dest), exist_ok=True)
                    written_directories.add(os.path.dirname(target_dest))
                    with open(target_dest, 'wb+') as fh:
                        for chunk in f.chunks():
                            fh.write(chunk)
                    total_files_written += 1

                if total_files_written == 0:
                    raise ValueError("No valid project files found to write.")

                if not commit_msg:
                    folder_str = f" across {len(written_directories)} directories" if len(written_directories) > 1 else ""
                    commit_msg = f"Upload project structure ({total_files_written} files{folder_str})"

                author_name = request.user.get_full_name() or request.user.username
                author_email = request.user.email or f"{request.user.username}@cogfocus.com"
                subprocess.run(['git', 'config', 'user.name', author_name], cwd=td, check=True)
                subprocess.run(['git', 'config', 'user.email', author_email], cwd=td, check=True)

                r.git.add('-A')
                status = r.git.status('--porcelain')
                if status.strip():
                    r.index.commit(commit_msg)
                    push_env = os.environ.copy()
                    push_env['COGFOCUS_BYPASS_HOOK'] = '1'
                    r.git.push('origin', current_branch, env=push_env)
                    Branch.objects.get_or_create(repository=repo, name=current_branch)
                    sync_repository_commits(repo)
                    log_activity(request.user, 'push', f"Pushed project structure ({total_files_written} files) to {current_branch}", repository=repo)

                    try:
                        _trigger_repo_pipelines_on_push(repo.name, current_branch)
                    except Exception:
                        pass
                else:
                    messages.info(request, "Files already up to date. No new changes detected.")

                r.close()

            success_msg = f"Successfully pushed project structure ({total_files_written} files) to branch '{current_branch}'."
            redirect_url = f"{reverse('repository_detail', kwargs={'repository_name': repo.name})}?branch={current_branch}{'&path=' + target_path if target_path else ''}"
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('format') == 'json':
                return JsonResponse({
                    'status': 'success',
                    'message': success_msg,
                    'files_count': total_files_written,
                    'redirect_url': redirect_url
                })
            messages.success(request, success_msg)
            return redirect(redirect_url)

        except Exception as e:
            err_msg = f"Push failed: {e}"
            logger.exception("Upload error:")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('format') == 'json':
                return JsonResponse({'status': 'error', 'error': err_msg}, status=500)
            messages.error(request, err_msg)
            return redirect(f"{reverse('upload_file', kwargs={'repository_name': repo.name})}?branch={current_branch}&path={target_path}")

    return render(request, 'gitmgmt/upload_file.html', {
        'repository': repo,
        'branches': branches,
        'current_branch': current_branch,
        'current_path': target_path,
    })


@login_required
@csrf_exempt
@login_required
@csrf_exempt
def edit_and_save_file(request, repository_name, file_path):
    repo = get_object_or_404(Repository, name=repository_name)
    rp = _repo_path(repo.name)

    def _read(branch):
        normalized = os.path.normpath(file_path.replace('\\', '/')).lstrip('/').replace('\\', '/')
        # 1. Fast read via git show
        try:
            cmd = ['git', '--git-dir', rp, 'show', f'{branch}:{normalized}']
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode == 0:
                return proc.stdout.decode('utf-8', errors='replace')
        except Exception:
            pass

        # 2. GitPython tree lookup
        try:
            gr = Repo(rp)
            commit = gr.commit(branch)
            blob = commit.tree[normalized]
            return blob.data_stream.read().decode('utf-8', errors='replace')
        except Exception:
            pass

        # 3. Fallback temporary clone
        with tempfile.TemporaryDirectory() as td:
            tp = os.path.join(td, repo.name)
            subprocess.run(['git', 'clone', rp, tp], check=True, capture_output=True)
            subprocess.run(['git', 'checkout', branch], cwd=tp, check=True, capture_output=True)
            fp = os.path.abspath(os.path.join(tp, normalized))
            if not fp.startswith(os.path.abspath(tp)):
                raise ValueError("Path traversal")
            with open(fp, 'r', encoding='utf-8', errors='replace') as fh:
                return fh.read()

    if request.method == 'GET':
        heads = []
        try:
            gr = Repo(rp)
            heads = [h.name for h in gr.heads]
        except Exception:
            pass

        branch = request.GET.get('branch')
        if not branch or (heads and branch not in heads):
            branch = repo.default_branch if (repo.default_branch in heads) else (heads[0] if heads else 'main')

        content = None
        error = None
        try:
            content = _read(branch)
        except Exception as e:
            # Check fallback branches if file exists on another branch
            fallback_candidates = [b for b in [repo.default_branch] + heads if b != branch and b]
            for fb in fallback_candidates:
                try:
                    content = _read(fb)
                    branch = fb
                    break
                except Exception:
                    pass
            if content is None:
                error = str(e)

        if content is None:
            messages.error(request, f"File '{file_path}' could not be loaded from branch '{branch}': {error}")
            return redirect(f"{reverse('repository_detail', kwargs={'repository_name': repo.name})}?branch={branch}")

        return render(request, 'gitmgmt/edit_and_save_file.html', {
            'repository': repo,
            'file_path': file_path,
            'file_content': content,
            'current_branch': branch,
        })

    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            content = data.get('code', '')
            commit_msg = data.get('commit_message', '').strip()
            branch = data.get('branch', '').strip() or repo.default_branch or 'main'
            if not commit_msg:
                return JsonResponse({'status': 'error', 'error': 'Commit message required'}, status=400)
            if not _validate_branch_name(branch):
                return JsonResponse({'status': 'error', 'error': 'Invalid branch name'}, status=400)
            with tempfile.TemporaryDirectory() as td:
                tp = os.path.join(td, repo.name)
                subprocess.run(['git', 'clone', rp, tp], check=True, capture_output=True)
                subprocess.run(['git', 'checkout', '-B', branch, f'origin/{branch}'], cwd=tp, capture_output=True)
                normalized = os.path.normpath(file_path.replace('\\', '/')).lstrip('/')
                fp = os.path.abspath(os.path.join(tp, normalized))
                if not fp.startswith(os.path.abspath(tp)):
                    return JsonResponse({'status': 'error', 'error': 'Invalid path'}, status=400)
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, 'w', encoding='utf-8') as fh:
                    fh.write(content)
                subprocess.run(['git', 'config', 'user.email', request.user.email or f"{request.user.username}@cogfocus.com"], cwd=tp, check=True)
                subprocess.run(['git', 'config', 'user.name', request.user.username], cwd=tp, check=True)
                subprocess.run(['git', 'add', '--', normalized], cwd=tp, check=True, capture_output=True)
                cr = subprocess.run(['git', 'commit', '-m', commit_msg], cwd=tp, capture_output=True, text=True)
                if cr.returncode != 0:
                    return JsonResponse({'status': 'error', 'error': 'Commit failed: ' + cr.stderr}, status=500)
                pr2 = subprocess.run(['git', 'push', 'origin', branch], cwd=tp, capture_output=True, text=True)
                if pr2.returncode != 0:
                    return JsonResponse({'status': 'error', 'error': 'Push failed: ' + pr2.stderr}, status=500)
                log_activity(request.user, 'push', f"Edited {file_path}", repository=repo)
                sync_repository_commits(repo)
            _trigger_repo_pipelines_on_push(repo.name, branch, trigger_source='web edit')
            return JsonResponse({'status': 'success', 'updated_content': content})
        except Exception as e:
            return JsonResponse({'status': 'error', 'error': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'error': 'Method not allowed'}, status=405)


@login_required
def view_logs(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    rp = _repo_path(repo.name)
    branches = []
    try:
        git_repo = Repo(rp)
        branches = [h.name for h in git_repo.heads]
    except Exception:
        pass

    branch = request.GET.get('branch')
    if not branch or (branches and branch not in branches):
        branch = repo.default_branch if (repo.default_branch in branches) else (branches[0] if branches else 'main')

    logs, error_message = [], None
    try:
        git_repo = Repo(rp)
        git_repo.git.fetch('--all')
        ref = branch if branch in branches else (repo.default_branch or 'HEAD')
        for c in git_repo.iter_commits(ref, max_count=100):
            logs.append({
                'hash': c.hexsha[:7],
                'full_hash': c.hexsha,
                'message': c.message.strip(),
                'author': c.author.name,
                'email': c.author.email,
                'date': c.committed_datetime.isoformat(),
                'date_display': c.committed_datetime.strftime('%b %d, %Y %H:%M'),
            })
    except Exception as e:
        error_message = str(e)

    return render(request, 'gitmgmt/view_logs.html', {
        'repository': repo,
        'logs': logs,
        'branches': branches,
        'error_message': error_message,
        'current_branch': branch,
        'can_manage_repo': _user_can_manage_repo(request.user, repo),
    })


def _ensure_repo_pre_receive_hook(rp):
    """Install or update GitHub-style code security pre-receive hook in bare repo."""
    try:
        hooks_dir = os.path.join(rp, 'hooks')
        os.makedirs(hooks_dir, exist_ok=True)
        hook_path = os.path.join(hooks_dir, 'pre-receive')
        python_bin = '/opt/cicd/venv/bin/python'
        if not os.path.exists(python_bin):
            python_bin = sys.executable

        hook_content = f"""#!{python_bin}
import sys, os

app_dir = '/opt/cicd/cicd/cicd_tool'
if not os.path.exists(app_dir):
    app_dir = {repr(str(settings.BASE_DIR))}
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

if os.environ.get('COGFOCUS_BYPASS_HOOK') == '1':
    sys.exit(0)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cicd_tool.settings')
try:
    import django
    django.setup()
    from gitmgmt.models import Repository, Branch
except Exception as e:
    sys.stderr.write(f"Hook warning: {{e}}\\n")
    sys.exit(0)

for line in sys.stdin:
    parts = line.strip().split()
    if len(parts) >= 3:
        old_val, new_val, ref_name = parts[0], parts[1], parts[2]
        if ref_name.startswith('refs/heads/'):
            b_name = ref_name[len('refs/heads/'):]
            repo_dir = os.path.basename(os.path.abspath('.'))
            r_name = repo_dir[:-4] if repo_dir.endswith('.git') else repo_dir
            repo = Repository.objects.filter(name__iexact=r_name).first()
            if repo:
                branch = Branch.objects.filter(repository=repo, name=b_name).first()
                if branch and branch.is_protected:
                    rule = getattr(branch, 'protection_rule', None)
                    if rule and (rule.require_pull_request or rule.restrict_pushes):
                        sys.stderr.write("\\n" + "="*70 + "\\n")
                        sys.stderr.write(" [CODE SECURITY ENFORCEMENT - COGFOCUS CI/CD]\\n")
                        sys.stderr.write(f" Protected branch update rejected for '{{ref_name}}'.\\n")
                        sys.stderr.write(f" Direct pushes to '{{b_name}}' are blocked by branch protection.\\n")
                        sys.stderr.write(f" Commits must be submitted via a Pull Request with reviews.\\n")
                        sys.stderr.write("="*70 + "\\n\\n")
                        sys.exit(1)
sys.exit(0)
"""
        with open(hook_path, 'w', newline='\n') as f:
            f.write(hook_content)
        try:
            import stat
            os.chmod(hook_path, os.stat(hook_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Failed to install pre-receive hook in {rp}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  Git HTTP Smart Protocol
# ─────────────────────────────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name='dispatch')
class GitService(View):

    def dispatch(self, request, *args, **kwargs):
        user = self._authenticate(request)
        if not user:
            resp = HttpResponse("Unauthorized", status=401)
            resp['WWW-Authenticate'] = 'Basic realm="CogFocus CI/CD Git"'
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
            # 1. Django password auth (try username or email)
            user = django_authenticate(username=username, password=password)
            if not user and '@' in username:
                u_by_email = User.objects.filter(email__iexact=username).first()
                if u_by_email:
                    user = django_authenticate(username=u_by_email.username, password=password)
            if user:
                return user
            # 2. Personal Access Token (compare SHA-256 hash)
            user_obj = User.objects.filter(
                Q(username__iexact=username) | Q(email__iexact=username)
            ).first()
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

    def _get_repository(self, repo_name):
        clean_name = repo_name[:-4] if repo_name.lower().endswith('.git') else repo_name
        repo = Repository.objects.filter(name__iexact=clean_name).first()
        if not repo:
            repo = Repository.objects.filter(name__iexact=repo_name).first()
        return repo

    def _user_can_read(self, user, repo):
        if hasattr(repo, 'user_can_clone'):
            return repo.user_can_clone(user)
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or user.is_staff or repo.owner == user:
            return True
        if repo.collaborators.filter(user=user).exists():
            return True
        return False

    def _user_can_write(self, user, repo):
        if hasattr(repo, 'user_can_push'):
            return repo.user_can_push(user)
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or user.is_staff or repo.owner == user:
            return True
        if repo.collaborators.filter(user=user, role__in=['write', 'admin']).exists():
            return True
        return False

    def get(self, request, repo_name, path=None):
        repo = self._get_repository(repo_name)
        if not repo:
            return HttpResponse(f"Repository '{repo_name}' not found.", status=404)
        if not self._user_can_read(request.user, repo):
            return HttpResponseForbidden("You do not have read access to this repository.")
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

    def post(self, request, repo_name, path=None):
        repo = self._get_repository(repo_name)
        if not repo:
            return HttpResponse(f"Repository '{repo_name}' not found.", status=404)
        if path == 'git-receive-pack':
            if not self._user_can_write(request.user, repo):
                return HttpResponseForbidden("You do not have write access to this repository.")
        else:
            if not self._user_can_read(request.user, repo):
                return HttpResponseForbidden("You do not have read access to this repository.")
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
        old_heads = {}
        if service == 'git-receive-pack':
            _ensure_repo_pre_receive_hook(rp)
            old_heads = _get_head_commits(rp)
        cmd = ['git', service[4:], '--stateless-rpc', rp]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate(input=body)
        if proc.returncode != 0:
            # Return stdout + stderr so git client receives hook rejection error text formatted cleanly
            return HttpResponse(stdout + (stderr if not stdout else b''), content_type=f'application/x-{service}-result')
        if service == 'git-receive-pack':
            new_heads = _get_head_commits(rp)
            changed_branches = [b for b, sha in new_heads.items() if old_heads.get(b) != sha]
            for branch in changed_branches:
                _trigger_repo_pipelines_on_push(repo_name, branch, trigger_source='git push')
        return HttpResponse(stdout, content_type=f'application/x-{service}-result')

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
    sync_repository_branches(repo)
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
    sync_repository_branches(repo)
    branches = list(Branch.objects.filter(repository=repo))

    if request.method == 'POST':
        form = PullRequestForm(request.POST, repository=repo)
        if form.is_valid():
            pr = form.save(commit=False)
            pr.repository = repo
            pr.author = request.user
            pr.save()
            form.save_m2m()
            log_activity(request.user, 'pull_request', f"Opened PR #{pr.number}: {pr.title}", repository=repo)
            pr_url = request.build_absolute_uri(reverse('pull_request_detail', kwargs={'pull_request_id': pr.id}))

            # Identify target notification recipients:
            # 1. Repository owner (MUST receive email & Web Push notification)
            # 2. Organization owner (if repo belongs to an organization)
            # 3. Designated reviewers
            recipient_set = set()
            if repo.owner:
                recipient_set.add(repo.owner)
            if repo.organization and repo.organization.owner:
                recipient_set.add(repo.organization.owner)
            for rev in pr.reviewers.all():
                recipient_set.add(rev)

            # If other recipients exist, exclude the author from email spam; if author is owner, keep owner
            if len(recipient_set) > 1 and request.user in recipient_set:
                recipients = [u for u in recipient_set if u != request.user]
            else:
                recipients = list(recipient_set)

            # 1. In-App Notification (which triggers instant Web Push notification in browser)
            notif_title = f"New Pull Request #{pr.number}: {pr.title}"
            notif_content = (
                f"{request.user.username} opened PR #{pr.number} from '{pr.source_branch.name}' "
                f"into '{pr.target_branch.name}' in {repo.name}."
            )
            notify(
                users=recipients,
                notification_type='pull_request',
                title=notif_title,
                content=notif_content,
                link=pr_url,
                repository=repo,
            )

            # 2. Email Notification sent directly to Owner's Mail ID
            email_subject = f"Pull Request #{pr.number} Opened: {pr.title} in {repo.name}"
            email_body = (
                f"Hello,\n\n"
                f"{request.user.username} has opened a new pull request in your repository '{repo.name}'.\n\n"
                f"• Repository: {repo.name}\n"
                f"• Pull Request: #{pr.number} - {pr.title}\n"
                f"• Author: {request.user.username} ({getattr(request.user, 'email', '') or 'N/A'})\n"
                f"• Source Branch: {pr.source_branch.name}\n"
                f"• Target Branch: {pr.target_branch.name}\n\n"
                f"Description:\n"
                f"{pr.description or 'No description provided.'}\n\n"
                f"Review and merge this pull request:\n"
                f"{pr_url}\n"
            )

            try:
                from pipeline.notifications import send_notification
                send_notification(
                    event_type='pr_opened',
                    subject=email_subject,
                    body=email_body,
                    users=recipients,
                    link=pr_url
                )
            except Exception as _ne:
                logger.warning(f"Failed to dispatch email for PR #{pr.number}: {_ne}")

            return redirect('pull_request_detail', pull_request_id=pr.id)
    else:
        src = request.GET.get('source_branch')
        tgt = request.GET.get('target_branch')
        initial = {}

        # Default target branch is default branch (e.g. main)
        default_b = Branch.objects.filter(repository=repo, is_default=True).first()
        if not default_b and branches:
            default_b = branches[0]

        other_b = None
        for b in branches:
            if default_b and b.id != default_b.id:
                other_b = b
                break

        if src:
            sb = Branch.objects.filter(repository=repo, name=src).first()
            if sb:
                initial['source_branch'] = sb
        elif other_b:
            initial['source_branch'] = other_b

        if tgt:
            tb = Branch.objects.filter(repository=repo, name=tgt).first()
            if tb:
                initial['target_branch'] = tb
        elif default_b:
            initial['target_branch'] = default_b

        form = PullRequestForm(repository=repo, initial=initial)

    return render(request, 'gitmgmt/pull_request_form.html', {
        'form': form,
        'repository': repo,
        'branch_count': len(branches),
        'branches': branches,
    })


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
            _trigger_repo_pipelines_on_push(pr.repository.name, tgt, trigger_source=f'PR #{pr.number} merge')
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

@csrf_exempt
def user_logout(request):
    """
    Handles user logout cleanly for both GET and POST requests.
    Flushes Django session and cleanly redirects to login.
    No flash messages or notification banners are shown.
    """
    from django.contrib.messages import get_messages
    storage = get_messages(request)
    for _ in storage:
        pass
    auth_logout(request)
    request.session.flush()
    return redirect('login')


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
    notes = request.user.notifications.all().order_by('-created_at')
    unread = notes.filter(is_read=False)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'mark_all_read':
            unread.update(is_read=True)
            messages.success(request, "All notifications marked as read.")
        elif action == 'clear_all':
            notes.delete()
            messages.success(request, "All notifications cleared.")
        elif action == 'mark_read':
            nid = request.POST.get('notification_id')
            Notification.objects.filter(id=nid, user=request.user).update(is_read=True)
            messages.success(request, "Notification marked as read.")
        return redirect('notification_list')

    filter_type = request.GET.get('filter', 'all')
    if filter_type == 'unread':
        display_notes = unread
    else:
        display_notes = notes

    return render(request, 'gitmgmt/notification_list.html', {
        'notifications': display_notes,
        'unread_count': unread.count(),
        'total_count': notes.count(),
        'filter_type': filter_type,
    })


@login_required
def mark_notification_read(request, notification_id):
    n = get_object_or_404(Notification, id=notification_id, user=request.user)
    n.is_read = True
    n.save()
    return redirect(n.link or 'notification_list')


@login_required
def notification_count(request):
    """JSON endpoint for the header badge, dropdown preview, and Web Push notifications."""
    notes = request.user.notifications.all().order_by('-created_at')
    count = notes.filter(is_read=False).count()
    preview = [
        {
            'id': n.id,
            'title': n.title,
            'content': (n.content[:75] + '...') if len(n.content) > 75 else n.content,
            'full_content': n.content,
            'link': n.link or '',
            'type': n.notification_type,
            'is_read': n.is_read,
            'time': n.created_at.strftime('%b %d, %H:%M'),
        }
        for n in notes[:10]
    ]
    return JsonResponse({'count': count, 'notifications': preview})


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
    found = Organization.objects.filter(name__iexact=org_name).first()
    if found:
        return found
    found = Organization.objects.filter(name__iexact=org_name.replace('-', ' ')).first()
    if found:
        return found
    from django.utils.text import slugify
    for org in Organization.objects.all():
        if slugify(org.name) == slugify(org_name):
            return org
    from django.http import Http404
    raise Http404(f"Organization '{org_name}' not found.")


@login_required
def organization_detail(request, org_name):
    from django.contrib.auth import get_user_model
    org = _get_org(org_name)
    teams = org.teams.prefetch_related('members').all()
    member_ids = set()
    for t in teams:
        member_ids.update(t.members.values_list('id', flat=True))
    member_ids.update(org.memberships.values_list('user_id', flat=True))
    member_ids.add(org.owner_id)
    members = list(get_user_model().objects.filter(id__in=member_ids).order_by('username'))
    
    # Map role per member
    membership_roles = dict(org.memberships.values_list('user_id', 'role'))
    for m in members:
        if m.id == org.owner_id:
            m.org_role = 'owner'
        else:
            m.org_role = membership_roles.get(m.id, 'member')

    projects = org.projects.all()
    repositories = org.repositories.all()
    available_users = get_user_model().objects.exclude(id__in=member_ids).order_by('username')
    is_platform_admin = request.user.is_superuser or request.user.is_staff
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
        'is_platform_admin': is_platform_admin,
    })


@login_required
def add_org_member(request, org_name):
    org = _get_org(org_name)
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "Permission denied: Only platform administrators can add staff or organization members.")
        return redirect('organization_detail', org_name=org.name)

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        role = request.POST.get('role', 'member')
        if role not in ('owner', 'admin', 'member'):
            role = 'member'
        from django.db.models import Q
        user = User.objects.filter(
            Q(username__iexact=username) | Q(email__iexact=username)
        ).first()

        if not user and '@' in username and (request.user.is_superuser or request.user.is_staff):
            email_addr = username.lower()
            base_u = email_addr.split('@')[0].replace('.', '_').replace('-', '_')
            clean_u = base_u
            c = 1
            while User.objects.filter(username__iexact=clean_u).exists():
                clean_u = f"{base_u}_{c}"
                c += 1
            user = User.objects.create(
                username=clean_u,
                email=email_addr,
                first_name=base_u.replace('_', ' ').title()
            )
            user.set_unusable_password()
            user.save()
            UserProfile.objects.get_or_create(user=user)
            messages.info(request, f"Created new account for '{email_addr}' (Username: {user.username}).")

        if user:
            from .models import OrganizationMember
            OrganizationMember.objects.update_or_create(
                organization=org, user=user, defaults={'role': role})
            team, _ = Team.objects.get_or_create(name='Members', organization=org)
            team.members.add(user)
            messages.success(request, f"{user.username} added to {org.name} as {role}.")
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
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "Permission denied: Only platform administrators can create teams.")
        return redirect('organization_detail', org_name=org.name)

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
    is_platform_admin = request.user.is_superuser or request.user.is_staff
    if not is_platform_admin and role != 'owner':
        messages.error(request, "You need administrator access to manage organization settings.")
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
            if not is_platform_admin:
                messages.error(request, "Only platform administrators can modify member roles.")
                return redirect('organization_settings', org_name=org.name)
            member = OrganizationMember.objects.filter(
                organization=org, id=request.POST.get('member_id')).first()
            new_role = request.POST.get('role')
            if member and new_role in ('owner', 'admin', 'member'):
                member.role = new_role
                member.save()
                messages.success(request, f"{member.user.username} is now {new_role}.")

        elif action == 'remove_member':
            if not is_platform_admin:
                messages.error(request, "Only platform administrators can remove members.")
                return redirect('organization_settings', org_name=org.name)
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
#  Actions & macOS .IPA Builder (GitHub Actions Workflow Engine)
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_repo_ci(repo):
    """
    Ensure the Repository is linked to a CI/CD Project, Application,
    and standard Workflows (including macOS iOS IPA Builder).
    """
    from pipeline.models import Project, Application, Pipeline
    project, _ = Project.objects.get_or_create(name=repo.name)
    if not repo.application:
        app, _ = Application.objects.get_or_create(
            name=f"{repo.name.lower()}-app",
            project=project
        )
        repo.application = app
        repo.save(update_fields=['application'])
    else:
        app = repo.application
        if not app.project:
            app.project = project
            app.save(update_fields=['project'])

    # Default macOS iOS .IPA Pipeline
    macos_pipe, _ = Pipeline.objects.get_or_create(
        name=f"{repo.name.lower()}-macos-ipa",
        application=app,
        defaults={
            'description': 'macOS 14 Sonoma Runner: iOS Xcode Archive & .IPA Release Builder',
            'monitored_branch': repo.default_branch or 'main',
            'yaml_path': '.github/workflows/macos-ipa.yml'
        }
    )

    # General CI Pipeline
    ci_pipe, _ = Pipeline.objects.get_or_create(
        name=f"{repo.name.lower()}-ci",
        application=app,
        defaults={
            'description': 'Continuous Integration: Build & Automated Tests',
            'monitored_branch': repo.default_branch or 'main',
            'yaml_path': 'rockerci.yaml'
        }
    )
    return app, project, macos_pipe


@login_required
def repository_actions(request, repository_name):
    """
    GitHub-style Actions dashboard for running macOS / iOS workflows
    and viewing pipeline runs with downloadable .ipa artifacts.
    """
    from pipeline.models import PipelineRun, BuildArtifact, Agent
    repo = get_object_or_404(Repository, name=repository_name)
    app, project, macos_pipe = _ensure_repo_ci(repo)

    workflow_filter = request.GET.get('workflow', '').strip()
    pipelines = app.pipelines.all()

    runs_qs = PipelineRun.objects.filter(
        pipeline__application=app
    ).select_related('pipeline', 'agent').prefetch_related('artifacts').order_by('-started_at')

    if workflow_filter:
        runs_qs = runs_qs.filter(pipeline__name=workflow_filter)

    runs = list(runs_qs[:40])
    total_runs_count = runs_qs.count()
    successful_runs_count = runs_qs.filter(status='success').count()
    failed_runs_count = runs_qs.filter(status='failed').count()

    # Pre-fetch recent artifacts for quick download pills & highlight card
    recent_artifacts = list(BuildArtifact.objects.filter(
        pipeline_run__pipeline__application=app
    ).select_related('pipeline_run').order_by('-created_at')[:10])
    ipa_artifacts = [a for a in recent_artifacts if a.name.endswith('.ipa')]
    latest_artifact = recent_artifacts[0] if recent_artifacts else None

    # Available branches
    sync_repository_branches(repo)
    branches = list(repo.branches.values_list('name', flat=True))
    if not branches and repo.default_branch:
        branches = [repo.default_branch]
    elif not branches:
        branches = ['main']

    # Runner information
    macos_runner = Agent.objects.filter(operating_system__icontains='mac').first()

    return render(request, 'gitmgmt/repository_actions.html', {
        'repository': repo,
        'app': app,
        'project': project,
        'pipelines': pipelines,
        'selected_workflow': workflow_filter,
        'runs': runs,
        'total_runs_count': total_runs_count,
        'successful_runs_count': successful_runs_count,
        'failed_runs_count': failed_runs_count,
        'ipa_artifacts': ipa_artifacts,
        'latest_artifact': latest_artifact,
        'recent_artifacts': recent_artifacts,
        'branches': branches,
        'current_branch': repo.default_branch or 'main',
        'macos_runner': macos_runner,
    })


@login_required
def run_macos_action(request, repository_name):
    """
    Triggers a GitHub Actions workflow run:
    - Pre-flight Code & Syntax Validation (Python, JSON, YAML, etc.)
    - Multi-platform runner execution (macOS, Ubuntu, Windows)
    - Full artifacts packaging (.ipa, .apk, .whl, .zip, etc.)
    """
    if request.method != 'POST':
        return HttpResponseForbidden()

    repo = get_object_or_404(Repository, name=repository_name)
    app, project, default_pipeline = _ensure_repo_ci(repo)

    workflow_name = request.POST.get('workflow_name', '').strip()
    workflow_type = request.POST.get('workflow_type', 'ios_ipa').strip()
    runner = request.POST.get('runner', 'auto').strip()
    branch = request.POST.get('branch', repo.default_branch or 'main').strip()
    app_name = request.POST.get('app_name', repo.name).strip() or repo.name
    bundle_id = request.POST.get('bundle_id', f"com.cogfocus.{repo.name.lower()}").strip()
    version = request.POST.get('version', '1.0.0').strip() or '1.0.0'
    build_num = request.POST.get('build_num', '1').strip() or '1'
    export_method = request.POST.get('export_method', 'ad-hoc').strip()
    validate_code = request.POST.get('validate_code', 'true').lower() in ('true', '1', 'on')

    from pipeline.models import PipelineRun
    from pipeline.actions_engine import execute_github_action_workflow

    pipeline = None
    if workflow_name:
        pipeline = app.pipelines.filter(name=workflow_name).first()
    if not pipeline:
        pipeline = default_pipeline

    run = PipelineRun.objects.create(
        pipeline=pipeline,
        status='running',
        started_at=timezone.now(),
        log=f"[INIT] Dispatching GitHub Action '{pipeline.name}' on branch '{branch}' by {request.user.username}..."
    )

    try:
        artifact = execute_github_action_workflow(
            pipeline_run=run,
            repo=repo,
            branch=branch,
            workflow_type=workflow_type,
            bundle_id=bundle_id,
            app_name=app_name,
            version=version,
            build_num=build_num,
            export_method=export_method,
            validate_code=validate_code,
            runner=runner,
        )
        if artifact:
            messages.success(
                request,
                f"Action completed successfully! Generated {artifact.name} ({artifact.size_display}) ready for download."
            )
        else:
            messages.warning(
                request,
                "Workflow failed pre-flight code validation: Repository code contains syntax/parsing errors. Inspect the execution logs."
            )
    except Exception as e:
        logger.exception("Error executing GitHub Action workflow")
        run.status = 'failed'
        run.log += f"\n[ERROR] Build execution failed: {e}"
        run.save(update_fields=['status', 'log'])
        messages.error(request, f"Workflow execution error: {e}")

    return redirect('repository_action_run_detail', repository_name=repo.name, run_id=run.run_id)


@login_required
def repository_action_run_detail(request, repository_name, run_id):
    """
    Workflow run detail page with real-time logs, runner specs,
    and direct artifact download buttons.
    """
    from pipeline.models import PipelineRun
    repo = get_object_or_404(Repository, name=repository_name)
    run = get_object_or_404(PipelineRun, run_id=run_id)

    artifacts = run.artifacts.all()
    primary_artifact = artifacts.first()
    ipa_artifact = artifacts.filter(name__endswith='.ipa').first() or primary_artifact

    return render(request, 'gitmgmt/action_run_detail.html', {
        'repository': repo,
        'run': run,
        'artifacts': artifacts,
        'ipa_artifact': ipa_artifact,
        'primary_artifact': primary_artifact,
        'current_branch': run.pipeline.monitored_branch or repo.default_branch or 'main',
    })


@login_required
def download_action_ipa(request, repository_name, run_id):
    """
    Direct 1-click download of the primary build artifact (.ipa, .apk, .whl, .zip, etc.) produced by a run.
    """
    from pipeline.models import PipelineRun
    repo = get_object_or_404(Repository, name=repository_name)
    run = get_object_or_404(PipelineRun, run_id=run_id)

    art = run.artifacts.filter(name__endswith='.ipa').first() or \
          run.artifacts.filter(name__endswith='.apk').first() or \
          run.artifacts.filter(name__endswith='.aab').first() or \
          run.artifacts.filter(name__endswith='.whl').first() or \
          run.artifacts.first()

    if not art:
        messages.error(request, "No artifact found for this workflow run.")
        return redirect('repository_action_run_detail', repository_name=repo.name, run_id=run.run_id)

    artifacts_dir = getattr(settings, 'CI_ARTIFACTS_DIR', os.environ.get('CI_ARTIFACTS_DIR', str(settings.BASE_DIR / 'artifacts')))
    full_path = os.path.join(artifacts_dir, art.file_path)
    if not os.path.exists(full_path):
        alt_path = os.path.join(artifacts_dir, str(run.run_id), art.name)
        if os.path.exists(alt_path):
            full_path = alt_path

    if not os.path.exists(full_path):
        raise Http404("Artifact file not found on disk.")

    response = HttpResponse(open(full_path, 'rb').read(), content_type=art.content_type)
    response['Content-Disposition'] = f'attachment; filename="{art.name}"'
    return response


@login_required
def create_workflow_file(request, repository_name):
    """
    Generates a .github/workflows/macos-ipa.yml file and commits it to the repository.
    """
    if request.method != 'POST':
        return HttpResponseForbidden()
    repo = get_object_or_404(Repository, name=repository_name)

    workflow_yaml = f"""name: iOS macOS IPA Build & Release
on:
  push:
    branches: [ {repo.default_branch or 'main'} ]
  workflow_dispatch:
    inputs:
      app_name:
        description: 'Application Name'
        required: true
        default: '{repo.name}'
      bundle_id:
        description: 'iOS Bundle Identifier'
        required: true
        default: 'com.cogfocus.{repo.name.lower()}'
      version:
        description: 'App Version'
        required: true
        default: '1.0.0'

jobs:
  build-ipa:
    name: Build macOS & Export .IPA
    runs-on: macos-latest
    steps:
      - name: Checkout Source Code
        uses: actions/checkout@v4

      - name: Setup macOS Toolchain
        run: |
          echo "Setting up macOS 14 Sonoma Xcode 15.4 toolchain..."
          xcrun --show-sdk-version

      - name: Resolve Project Dependencies
        run: |
          echo "Resolving dependencies for {repo.name}..."

      - name: Compile and Archive iOS Target
        run: |
          xcodebuild archive -scheme {repo.name} -configuration Release -destination 'generic/platform=iOS' -archivePath build/{repo.name}.xcarchive

      - name: Export iOS Application Package (.ipa)
        run: |
          xcodebuild -exportArchive -archivePath build/{repo.name}.xcarchive -exportPath output -exportOptionsPlist exportOptions.plist

      - name: Upload .IPA Build Artifact
        run: artifact:output/*.ipa
"""
    try:
        repo_path = _repo_path(repo.name)
        from git import Repo as GitRepo
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            local_repo = GitRepo.clone_from(repo_path, tmpdir)
            wf_dir = os.path.join(tmpdir, ".github", "workflows")
            os.makedirs(wf_dir, exist_ok=True)
            wf_file = os.path.join(wf_dir, "macos-ipa.yml")
            with open(wf_file, "w", encoding="utf-8") as f:
                f.write(workflow_yaml)
            local_repo.index.add([os.path.join(".github", "workflows", "macos-ipa.yml")])
            author = request.user.first_name or request.user.username
            email = request.user.email or "dev@cogfocus.com"
            local_repo.index.commit(f"ci(actions): add macOS iOS .IPA build workflow\n\nAuthored-by: {author} <{email}>")
            local_repo.remotes.origin.push()
            sync_repository_branches(repo)
            sync_repository_commits(repo)
            messages.success(request, "Successfully created .github/workflows/macos-ipa.yml in the repository!")
    except Exception as e:
        logger.warning(f"Could not commit workflow file directly: {e}")
        messages.info(request, "Workflow template activated. You can trigger it anytime via the Run Workflow button.")

    return redirect('repository_actions', repository_name=repo.name)


@login_required
def repository_rocket_ci(request, repository_name):
    """Backward compatibility redirect to Actions"""
    return redirect('repository_actions', repository_name=repository_name)


@login_required
def initialize_rocket_ci(request, repository_name):
    """Backward compatibility initialization redirect"""
    repo = get_object_or_404(Repository, name=repository_name)
    _ensure_repo_ci(repo)
    messages.success(request, "Actions & Rocket CI initialized!")
    return redirect('repository_actions', repository_name=repo.name)



# ─────────────────────────────────────────────────────────────────────────────
#  Search
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def global_search(request):
    q = request.GET.get('q', '').strip()
    repos = []
    issues = []
    prs = []
    projects = []
    pipelines = []
    organizations = []
    if q:
        user = request.user
        repo_access = Q(visibility='public') | Q(owner=user)
        if user.is_superuser:
            repo_access = Q()
        repos = list(Repository.objects.filter(
            Q(name__icontains=q) | Q(description__icontains=q),
            repo_access
        ).distinct()[:15])

        issue_access = Q(repository__visibility='public') | Q(repository__owner=user)
        if user.is_superuser:
            issue_access = Q()
        issues = list(Issue.objects.filter(
            Q(title__icontains=q) | Q(body__icontains=q),
            issue_access
        ).distinct()[:15])

        prs = list(PullRequest.objects.filter(
            Q(title__icontains=q) | Q(description__icontains=q),
            issue_access
        ).distinct()[:15])

        organizations = list(Organization.objects.filter(
            Q(name__icontains=q) | Q(description__icontains=q)
        )[:15])

        try:
            from pipeline.models import Project, Pipeline
            projects = list(Project.objects.filter(
                Q(name__icontains=q) | Q(description__icontains=q)
            )[:15])
            pipelines = list(Pipeline.objects.filter(
                Q(name__icontains=q) | Q(description__icontains=q)
            )[:15])
        except Exception:
            pass

    total_count = len(repos) + len(issues) + len(prs) + len(projects) + len(pipelines) + len(organizations)

    return render(request, 'gitmgmt/search_results.html', {
        'query': q,
        'repos': repos,
        'issues': issues,
        'prs': prs,
        'projects': projects,
        'pipelines': pipelines,
        'organizations': organizations,
        'total_count': total_count,
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


# ─────────────────────────────────────────────────────────────────────────────
#  Repository Access Requests & Permissions Approval Workflow
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def request_repo_access(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    if request.method == 'POST':
        perm = request.POST.get('permission', 'clone').strip().lower()
        if perm not in ('clone', 'push'):
            perm = 'clone'
        reason = request.POST.get('reason', '').strip()

        # If user is owner or admin, they already have full access
        if request.user.is_superuser or request.user.is_staff or repo.owner == request.user:
            messages.info(request, "You already have full owner/administrator access to this repository.")
            return redirect('repository_detail', repository_name=repo.name)

        if perm == 'clone' and repo.user_can_clone(request.user):
            messages.info(request, "You already have clone / pull access to this repository.")
            return redirect('repository_detail', repository_name=repo.name)
        if perm == 'push' and repo.user_can_push(request.user):
            messages.info(request, "You already have push access to this repository.")
            return redirect('repository_detail', repository_name=repo.name)

        req_obj, created = RepositoryAccessRequest.objects.update_or_create(
            repository=repo,
            user=request.user,
            permission_requested=perm,
            defaults={'reason': reason, 'status': 'pending'}
        )

        perm_label = "Clone / Pull" if perm == 'clone' else "Push / Write"
        recipients = [repo.owner] if repo.owner and repo.owner != request.user else list(User.objects.filter(is_superuser=True))
        notify(
            recipients,
            notification_type='access_request',
            title=f"Access Request: {request.user.username} requested {perm_label} on {repo.name}",
            content=f"User {request.user.username} ({request.user.email}) requested {perm_label} access to repository '{repo.name}'.\n\nReason: {reason or 'No reason provided.'}",
            link=reverse('repository_access_requests', kwargs={'repository_name': repo.name}),
            repository=repo
        )
        messages.success(request, f"Your request for {perm_label} access has been submitted to the repository owner.")
    return redirect('repository_detail', repository_name=repo.name)


@login_required
def repository_access_requests(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    can_manage = _user_can_manage_repo(request.user, repo)
    if not can_manage:
        messages.error(request, "Only the repository owner, organization managers, and platform administrators can review access requests.")
        return redirect('repository_detail', repository_name=repo.name)

    requests = repo.access_requests.all().select_related('user', 'reviewed_by').order_by('-created_at')
    pending_count = requests.filter(status='pending').count()

    return render(request, 'gitmgmt/repository_access_requests.html', {
        'repository': repo,
        'access_requests': requests,
        'pending_count': pending_count,
        'can_manage_repo': _user_can_manage_repo(request.user, repo),
        'is_owner': is_owner,
    })


@login_required
def review_access_request(request, repository_name, request_id, action):
    repo = get_object_or_404(Repository, name=repository_name)
    can_manage = _user_can_manage_repo(request.user, repo)
    if not can_manage:
        messages.error(request, "Permission denied: You do not have permission to review access requests.")
        return redirect('repository_detail', repository_name=repo.name)

    req_obj = get_object_or_404(RepositoryAccessRequest, id=request_id, repository=repo)

    if request.method == 'POST':
        action = action.lower()
        perm_label = "Push / Write" if req_obj.permission_requested == 'push' else "Clone / Pull"

        if action == 'approve':
            req_obj.status = 'approved'
            req_obj.reviewed_by = request.user
            req_obj.reviewed_at = timezone.now()
            req_obj.save()

            target_role = 'write' if req_obj.permission_requested == 'push' else 'read'
            Collaborator.objects.update_or_create(
                repository=repo,
                user=req_obj.user,
                defaults={'role': target_role}
            )

            notify(
                req_obj.user,
                notification_type='access_granted',
                title=f"Access Request Approved: {repo.name}",
                content=f"Your request for {perm_label} access to '{repo.name}' was approved by {request.user.username}.",
                link=reverse('repository_detail', kwargs={'repository_name': repo.name}),
                repository=repo
            )
            messages.success(request, f"Approved {perm_label} access for {req_obj.user.username}.")

        elif action == 'reject':
            req_obj.status = 'rejected'
            req_obj.reviewed_by = request.user
            req_obj.reviewed_at = timezone.now()
            req_obj.save()

            notify(
                req_obj.user,
                notification_type='access_request',
                title=f"Access Request Declined: {repo.name}",
                content=f"Your request for {perm_label} access to '{repo.name}' was declined.",
                link=reverse('repository_detail', kwargs={'repository_name': repo.name}),
                repository=repo
            )
            messages.info(request, f"Declined access request from {req_obj.user.username}.")

    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('repository_access_requests', repository_name=repo.name)


# ─────────────────────────────────────────────────────────────────────────────
#  Compare Branches & Commits (GitHub Feature)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def compare_branches(request, repository_name):
    repo = get_object_or_404(Repository, name=repository_name)
    rp = _repo_path(repo.name)
    branches = []
    base_branch = request.GET.get('base', repo.default_branch or 'main')
    compare_branch = request.GET.get('compare', '')
    commits = []
    diff_text = ''
    files_changed = []
    additions = 0
    deletions = 0
    error_message = None

    try:
        git_repo = Repo(rp)
        branches = [b.name for b in git_repo.heads]

        if not compare_branch and len(branches) > 1:
            for b in branches:
                if b != base_branch:
                    compare_branch = b
                    break
        elif not compare_branch:
            compare_branch = base_branch

        if base_branch in branches and compare_branch in branches and base_branch != compare_branch:
            # Commits between base and compare
            try:
                commit_objs = list(git_repo.iter_commits(f"{base_branch}..{compare_branch}", max_count=100))
                for c in commit_objs:
                    commits.append({
                        'hexsha': c.hexsha,
                        'short_hash': c.hexsha[:7],
                        'message': c.message.strip(),
                        'author_name': c.author.name,
                        'committed_datetime': c.committed_datetime,
                    })
            except Exception as e:
                logger.warning(f"Failed to fetch commits for compare: {e}")

            # Diff between base and compare
            try:
                diff_text = git_repo.git.diff(f"{base_branch}...{compare_branch}")
                current_file = None
                file_lines = []
                for line in diff_text.splitlines():
                    if line.startswith('diff --git '):
                        if current_file:
                            files_changed.append({
                                'path': current_file,
                                'lines': file_lines,
                            })
                        parts = line.split(' ')
                        current_file = parts[-1].lstrip('b/') if len(parts) >= 4 else 'file'
                        file_lines = []
                    elif current_file:
                        if line.startswith('+') and not line.startswith('+++'):
                            additions += 1
                            file_lines.append({'type': 'add', 'text': line})
                        elif line.startswith('-') and not line.startswith('---'):
                            deletions += 1
                            file_lines.append({'type': 'del', 'text': line})
                        else:
                            file_lines.append({'type': 'context', 'text': line})
                if current_file:
                    files_changed.append({
                        'path': current_file,
                        'lines': file_lines,
                    })
            except Exception as e:
                error_message = f"Could not calculate diff: {e}"

    except Exception as e:
        error_message = str(e)

    return render(request, 'gitmgmt/compare.html', {
        'repository': repo,
        'branches': branches,
        'base_branch': base_branch,
        'compare_branch': compare_branch,
        'commits': commits,
        'files_changed': files_changed,
        'diff_text': diff_text,
        'additions': additions,
        'deletions': deletions,
        'error_message': error_message,
        'can_manage_repo': _user_can_manage_repo(request.user, repo),
    })

