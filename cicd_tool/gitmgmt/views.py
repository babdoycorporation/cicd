from django.shortcuts import render, redirect, get_object_or_404
from .models import Repository, PullRequest
from .forms import RepositoryForm, PullRequestForm
import os
from git import Repo
from django.http import HttpResponse
import logging
from django.contrib import messages
import tempfile
from git import Repo, GitCommandError

logger = logging.getLogger(__name__)

REPO_BASE_PATH = 'D:/repos'

from django.shortcuts import render, get_object_or_404, redirect
from .models import Repository

from django.contrib.auth.decorators import login_required

@login_required
def repository_list(request):
    query = request.GET.get('q')
    if query:
        repositories = Repository.objects.filter(name__icontains=query)
    else:
        repositories = Repository.objects.all()
    
    favorites = repositories.filter(is_favorite=True)
    
    return render(request, 'gitmgmt/repository_list.html', {
        'repositories': repositories,
        'favorites': favorites
    })

def toggle_favorite(request, repository_id):
    repository = get_object_or_404(Repository, id=repository_id)
    if request.method == 'POST':
        repository.is_favorite = not repository.is_favorite
        repository.save()
    return redirect('repository_list')
import os
from git import Repo
import subprocess

def initialize_repository(name):
    repo_path = os.path.join(REPO_BASE_PATH, f"{name}.git")
    
    if not os.path.exists(repo_path):
        os.makedirs(repo_path)
    
    # Initialize bare repository
    repo = Repo.init(repo_path, bare=True)
    
    # Set up environment variables for the commit
    env = os.environ.copy()
    env['GIT_AUTHOR_NAME'] = 'System'
    env['GIT_AUTHOR_EMAIL'] = 'system@example.com'
    env['GIT_COMMITTER_NAME'] = 'System'
    env['GIT_COMMITTER_EMAIL'] = 'system@example.com'

    # Create README file content
    readme_content = f"# {name}\n\nThis is a new repository."
    
    try:
        # Create blob object for README
        blob_hash = subprocess.check_output(['git', 'hash-object', '-w', '--stdin'], 
                                            input=readme_content.encode(), 
                                            cwd=repo_path, 
                                            env=env).decode().strip()

        # Create tree object
        tree_content = f"100644 blob {blob_hash}\tREADME.md"
        tree_hash = subprocess.check_output(['git', 'mktree'], 
                                            input=tree_content.encode(), 
                                            cwd=repo_path, 
                                            env=env).decode().strip()

        # Create commit object
        commit_msg = "Initial commit"
        commit_hash = subprocess.check_output(['git', 'commit-tree', tree_hash, '-m', commit_msg], 
                                              cwd=repo_path, 
                                              env=env).decode().strip()

        # Update main branch to point to the new commit
        subprocess.run(['git', 'update-ref', 'refs/heads/main', commit_hash], 
                       check=True, 
                       cwd=repo_path, 
                       env=env)

        # Set HEAD to point to main branch
        subprocess.run(['git', 'symbolic-ref', 'HEAD', 'refs/heads/main'], 
                       check=True, 
                       cwd=repo_path, 
                       env=env)

    except subprocess.CalledProcessError as e:
        print(f"Error executing Git command: {e}")
        # You might want to delete the partially created repository here
        raise

    return repo

def create_repository(request):
    if request.method == 'POST':
        form = RepositoryForm(request.POST)
        if form.is_valid():
            repository = form.save(commit=False)
            try:
                initialize_repository(repository.name)
                repository.save()
                return redirect('repository_detail', repository_id=repository.id)
            except Exception as e:
                form.add_error(None, f"Failed to initialize repository: {str(e)}")
    else:
        form = RepositoryForm()
    return render(request, 'gitmgmt/repository_form.html', {'form': form})

from git import Repo, GitCommandError

def repository_detail(request, repository_id):
    repository = get_object_or_404(Repository, id=repository_id)
    repo_path = os.path.join(REPO_BASE_PATH, f"{repository.name}.git")
    
    branches = []
    files = []
    current_branch = None
    last_commit_hash = None
    last_commit_message = None
    error_message = None

    try:
        repo = Repo(repo_path)
        branches = [branch.name for branch in repo.branches]
        current_branch = request.GET.get('branch', repo.active_branch.name)
        
        # Get file tree
        tree = repo.heads[current_branch].commit.tree
        for blob in tree.traverse():
            if blob.type == 'blob':
                files.append(blob.path)

        # Get last commit
        last_commit = repo.head.commit
        last_commit_hash = last_commit.hexsha
        last_commit_message = last_commit.message

    except Exception as e:
        error_message = f"Error accessing repository: {str(e)}"
        print(error_message)  # For server logs

    return render(request, 'gitmgmt/repository_detail.html', {
        'repository': repository,
        'branches': branches,
        'current_branch': current_branch,
        'files': files,
        'last_commit_hash': last_commit_hash,
        'last_commit_message': last_commit_message,
        'error_message': error_message,
    })


from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import Repository, Branch, PullRequest, PullRequestComment
from .forms import PullRequestForm, PullRequestCommentForm
from git import Repo, GitCommandError
import tempfile
import os
import subprocess

def create_pull_request(request, repository_id):
    repository = get_object_or_404(Repository, id=repository_id)
    if request.method == 'POST':
        form = PullRequestForm(request.POST)
        if form.is_valid():
            pull_request = form.save(commit=False)
            pull_request.repository = repository
            pull_request.created_by = request.user
            pull_request.save()
            return redirect('pull_request_detail', pull_request_id=pull_request.id)
    else:
        form = PullRequestForm()
    return render(request, 'gitmgmt/pull_request_form.html', {'form': form, 'repository': repository})


def pull_request_detail(request, pull_request_id):
    pull_request = get_object_or_404(PullRequest, id=pull_request_id)
    comments = pull_request.comments.all().order_by('created_at')
    
    if request.method == 'POST':
        comment_form = PullRequestCommentForm(request.POST)
        if comment_form.is_valid():
            comment = comment_form.save(commit=False)
            comment.pull_request = pull_request
            comment.user = request.user
            comment.save()
            return redirect('pull_request_detail', pull_request_id=pull_request.id)
    else:
        comment_form = PullRequestCommentForm()
    
    # Get diff between source and target branches
    repo_path = os.path.join(REPO_BASE_PATH, f"{pull_request.repository.name}.git")
    with tempfile.TemporaryDirectory() as temp_dir:
        repo = Repo.clone_from(repo_path, temp_dir)
        diff = repo.git.diff(f'{pull_request.target_branch.name}...{pull_request.source_branch.name}')
    
    context = {
        'pull_request': pull_request,
        'comments': comments,
        'comment_form': comment_form,
        'diff': diff,
    }
    return render(request, 'gitmgmt/pull_request_detail.html', context)


from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Repository
import os
import tempfile
from git import Repo, GitCommandError

REPO_BASE_PATH = "D:/repos"

def merge_branch(request, repository_id):
    repository = get_object_or_404(Repository, id=repository_id)
    repo_path = os.path.join(REPO_BASE_PATH, f"{repository.name}.git")

    if request.method == 'POST':
        target_branch = request.POST.get('merge_target')
        current_branch = request.GET.get('branch', 'main')

        if not target_branch:
            messages.error(request, "No target branch selected for merging.")
            return redirect('repository_detail', repository_id=repository.id)

        if target_branch == current_branch:
            messages.error(request, "Cannot merge a branch into itself.")
            return redirect('repository_detail', repository_id=repository.id)

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                repo = Repo.clone_from(repo_path, temp_dir)
                
                # Verify branches exist both locally and remotely
                remote_branches = [ref.name.split('/')[-1] for ref in repo.remotes.origin.refs]
                if target_branch not in remote_branches or current_branch not in remote_branches:
                    messages.error(request, "One or both branches don't exist remotely.")
                    return redirect('repository_detail', repository_id=repository.id)

                # Fetch all latest changes
                repo.git.fetch('--all')

                # Checkout current branch
                repo.git.checkout(current_branch)
                repo.git.pull('origin', current_branch)

                # Verify if merge is needed
                if repo.git.diff(f'origin/{current_branch}..origin/{target_branch}') == "":
                    messages.info(request, "No changes to merge. Branches are already in sync.")
                    return redirect('repository_detail', repository_id=repository.id)

                # Attempt merge
                try:
                    merge_result = repo.git.merge(f'origin/{target_branch}')
                    repo.git.push('origin', current_branch)
                    messages.success(request, f"Successfully merged {target_branch} into {current_branch}.")
                except GitCommandError as e:
                    repo.git.merge('--abort')
                    if 'CONFLICT' in str(e):
                        messages.error(request, "Merge conflict detected. Please resolve conflicts manually.")
                    else:
                        messages.error(request, f"Merge failed: {str(e)}")
                    return redirect('repository_detail', repository_id=repository.id)

            except Exception as e:
                messages.error(request, f"Unexpected error during merge: {str(e)}")
                return redirect('repository_detail', repository_id=repository.id)

    return redirect('repository_detail', repository_id=repository.id)


def merge_pull_request(request, pull_request_id):
    pull_request = get_object_or_404(PullRequest, id=pull_request_id)
    repo_path = os.path.join(REPO_BASE_PATH, f"{pull_request.repository.name}.git")

    if request.method == 'POST':
        # Validate PR can be merged
        if pull_request.status != 'open':
            messages.error(request, "Only open pull requests can be merged.")
            return redirect('pull_request_detail', pull_request_id=pull_request.id)

        source_branch = pull_request.source_branch.name
        target_branch = pull_request.target_branch.name

        if source_branch == target_branch:
            messages.error(request, "Cannot merge identical branches.")
            return redirect('pull_request_detail', pull_request_id=pull_request.id)

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                repo = Repo.clone_from(repo_path, temp_dir)
                repo.git.fetch('--all')

                # Verify branches exist
                remote_branches = [ref.name.split('/')[-1] for ref in repo.remotes.origin.refs]
                if source_branch not in remote_branches or target_branch not in remote_branches:
                    messages.error(request, "One or both branches don't exist remotely.")
                    return redirect('pull_request_detail', pull_request_id=pull_request.id)

                # Checkout target branch
                repo.git.checkout(target_branch)
                repo.git.pull('origin', target_branch)

                # Verify merge is needed
                if repo.git.diff(f'origin/{target_branch}..origin/{source_branch}') == "":
                    messages.info(request, "No changes to merge. Branches are already in sync.")
                    pull_request.status = 'merged'
                    pull_request.save()
                    return redirect('pull_request_detail', pull_request_id=pull_request.id)

                # Attempt merge
                try:
                    merge_result = repo.git.merge(f'origin/{source_branch}')
                    repo.git.push('origin', target_branch)
                    
                    # Only mark as merged if push succeeded
                    pull_request.status = 'merged'
                    pull_request.merged_by = request.user
                    pull_request.merged_at = timezone.now()
                    pull_request.save()
                    
                    messages.success(request, f"Successfully merged {source_branch} into {target_branch}.")
                except GitCommandError as e:
                    repo.git.merge('--abort')
                    if 'CONFLICT' in str(e):
                        messages.error(request, "Merge conflict detected. Please resolve conflicts manually.")
                    else:
                        messages.error(request, f"Merge failed: {str(e)}")
                    return redirect('pull_request_detail', pull_request_id=pull_request.id)

            except Exception as e:
                messages.error(request, f"Unexpected error during merge: {str(e)}")
                return redirect('pull_request_detail', pull_request_id=pull_request.id)

    return redirect('pull_request_detail', pull_request_id=pull_request.id)




def close_pull_request(request, pull_request_id):
    pull_request = get_object_or_404(PullRequest, id=pull_request_id)
    if request.method == 'POST':
        pull_request.status = 'closed'
        pull_request.save()
    return redirect('pull_request_detail', pull_request_id=pull_request.id)
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from .models import Repository
import os
import tempfile
from git import Repo, GitCommandError

REPO_BASE_PATH = "D:/repos"  # Ensure this is the correct repository base path

def upload_file(request, repository_id):
    repository = get_object_or_404(Repository, id=repository_id)
    repo_path = os.path.join(REPO_BASE_PATH, f"{repository.name}.git")
    current_branch = request.GET.get('branch', 'main')  # Default to main

    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        commit_message = request.POST.get('commit_message', f"Added {file.name}")

        try:
            # Clone the repo into a temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_repo = Repo.clone_from(repo_path, temp_dir)
                git = temp_repo.git
                
                # Fetch latest changes
                git.fetch('--all')
                
                # Check if the branch exists remotely
                remote_branches = git.branch('-r')  # List remote branches
                
                print("Remote Branches:", remote_branches)
                
                if f'origin/{current_branch}' in remote_branches:
                    print(f"Checking out existing remote branch: {current_branch}")
                    git.checkout('-B', current_branch, f'origin/{current_branch}')  # Ensure it's linked to remote
                else:
                    print(f"Creating new branch {current_branch}")
                    git.checkout('-b', current_branch)

                # Save file in the repo
                temp_file_path = os.path.join(temp_dir, file.name)
                with open(temp_file_path, 'wb+') as destination:
                    for chunk in file.chunks():
                        destination.write(chunk)

                # Add file, commit, and push changes
                git.add(A=True)
                status_output = git.status()
                print(f"Git Status Before Commit:\n{status_output}")

                if "nothing to commit" in status_output.lower():
                    messages.error(request, "No changes detected. File may not have been saved.")
                    return redirect(reverse('repository_detail', kwargs={'repository_id': repository.id}) + f"?branch={current_branch}")

                # Commit the file
                temp_repo.index.commit(commit_message)
                print(f"Committed changes with message: {commit_message}")

                # Push changes explicitly to the correct branch
                push_result = git.push('origin', current_branch)
                print(f"Git Push Output:\n{push_result}")

                messages.success(request, f"File '{file.name}' uploaded successfully to branch '{current_branch}'.")
        except GitCommandError as e:
            messages.error(request, f"Git error while uploading file: {str(e)}")
        except Exception as e:
            messages.error(request, f"Unexpected error: {str(e)}")

        return redirect(reverse('repository_detail', kwargs={'repository_id': repository.id}) + f"?branch={current_branch}")

    return render(request, 'gitmgmt/upload_file.html', {'repository': repository, 'current_branch': current_branch})


from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from .models import Repository
from git import Repo, GitCommandError
import os

def create_branch(request, repository_id):
    repository = get_object_or_404(Repository, id=repository_id)
    repo_path = os.path.join(REPO_BASE_PATH, f"{repository.name}.git")

    if request.method == 'POST':
        branch_name = request.POST.get('branch_name')
        source_branch_name = request.POST.get('source_branch', 'main')  # Get source branch from form

        if not branch_name:
            messages.error(request, "Branch name is required.")
            return redirect('repository_detail', repository_id=repository.id)

        try:
            repo = Repo(repo_path)

            # Check if branch exists
            if branch_name in repo.heads:
                messages.error(request, f"Branch '{branch_name}' already exists.")
                return redirect('repository_detail', repository_id=repository.id)

            # Validate source branch
            if source_branch_name not in repo.heads:
                messages.error(request, f"Source branch '{source_branch_name}' does not exist.")
                return redirect('repository_detail', repository_id=repository.id)

            # Create new branch from source branch
            source_branch = repo.heads[source_branch_name]
            new_branch = repo.create_head(branch_name, source_branch.commit)

            messages.success(request, f"Branch '{branch_name}' created successfully from '{source_branch_name}'.")
            return redirect('repository_detail', repository_id=repository.id)

        except GitCommandError as e:
            messages.error(request, f"Git error: {str(e)}")
        except Exception as e:
            messages.error(request, f"Failed to create branch: {str(e)}")

    return redirect('repository_detail', repository_id=repository.id)

import logging
from git import Repo, GitCommandError
from django.shortcuts import render, get_object_or_404
import os

logger = logging.getLogger(__name__)

def view_logs(request, repository_id):
    repository = get_object_or_404(Repository, id=repository_id)
    repo_path = os.path.join(REPO_BASE_PATH, f"{repository.name}.git")
    current_branch = request.GET.get('branch', 'main')  # Default to main branch

    logs = []
    error_message = None

    try:
        repo = Repo(repo_path)

        # Ensure repo is updated before fetching logs
        repo.git.fetch('--all')

        # Check if branch exists before accessing commits
        if current_branch in repo.heads:
            commits = list(repo.iter_commits(current_branch, max_count=50))  # Fetch latest 50 commits
        else:
            commits = list(repo.iter_commits("HEAD", max_count=50))  # Default fallback to HEAD

        for commit in commits:
            logs.append({
                'hash': commit.hexsha[:7],  # Short hash
                'message': commit.message.strip(),
                'author': commit.author.name,
                'date': commit.committed_datetime.strftime('%Y-%m-%d %H:%M:%S'),
            })

        logger.info(f"Fetched {len(logs)} logs for repository {repository.name} on branch {current_branch}")

    except GitCommandError as e:
        error_message = f"Git error: {str(e)}"
    except Exception as e:
        error_message = f"Unexpected error: {str(e)}"

    return render(request, 'gitmgmt/view_logs.html', {
        'repository': repository,
        'logs': logs,
        'error_message': error_message,
        'current_branch': current_branch,
    })


# views.py

import json
import os
import tempfile
import subprocess
from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Repository
import logging

logger = logging.getLogger(__name__)

REPO_BASE_PATH = 'D:/repos'  # Update this to your repository base path

@csrf_exempt
def edit_and_save_file(request, repository_id, file_path):
    repository = get_object_or_404(Repository, id=repository_id)
    repo_path = os.path.join(REPO_BASE_PATH, f"{repository.name}.git")

    def get_file_content(repo_path, file_path):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_repo_path = os.path.join(temp_dir, repository.name)
            clone_command = ['git', 'clone', repo_path, temp_repo_path]
            subprocess.run(clone_command, check=True, capture_output=True, text=True)

            branch_command = ['git', 'rev-parse', '--abbrev-ref', 'HEAD']
            branch_result = subprocess.run(branch_command, cwd=temp_repo_path, capture_output=True, text=True, check=True)
            current_branch = branch_result.stdout.strip()

            temp_file_path = os.path.join(temp_repo_path, file_path.replace('\\', '/'))
            with open(temp_file_path, 'r', encoding='utf-8') as file:
                return file.read(), current_branch

    if request.method == 'GET':
        try:
            file_content, current_branch = get_file_content(repo_path, file_path)
        except Exception as e:
            logger.error(f"Error reading file: {str(e)}")
            return JsonResponse({'status': 'error', 'error': str(e)}, status=500)

        return render(request, 'gitmgmt/edit_and_save_file.html', {
            'repository': repository,
            'file_path': file_path,
            'file_content': file_content,
            'current_branch': current_branch,
        })

    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            file_content = data.get('code', '')
            commit_message = data.get('commit_message', '')
            current_branch = data.get('branch', '')

            if not commit_message:
                return JsonResponse({'status': 'error', 'error': 'Commit message is required'}, status=400)

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_repo_path = os.path.join(temp_dir, repository.name)
                
                # Clone the repository
                clone_command = ['git', 'clone', repo_path, temp_repo_path]
                subprocess.run(clone_command, check=True, capture_output=True, text=True)

                # Checkout the current branch
                checkout_command = ['git', 'checkout', current_branch]
                subprocess.run(checkout_command, cwd=temp_repo_path, check=True, capture_output=True, text=True)

                # Write the new content to the file
                temp_file_path = os.path.join(temp_repo_path, file_path.replace('\\', '/'))
                os.makedirs(os.path.dirname(temp_file_path), exist_ok=True)
                with open(temp_file_path, 'w', encoding='utf-8') as file:
                    file.write(file_content)

                # Configure Git
                subprocess.run(['git', 'config', 'user.email', "user@example.com"], cwd=temp_repo_path, check=True)
                subprocess.run(['git', 'config', 'user.name', "User"], cwd=temp_repo_path, check=True)

                # Stage the changes
                add_command = ['git', 'add', file_path.replace('\\', '/')]
                subprocess.run(add_command, cwd=temp_repo_path, check=True, capture_output=True, text=True)

                # Commit the changes
                commit_command = ['git', 'commit', '-m', commit_message]
                commit_result = subprocess.run(commit_command, cwd=temp_repo_path, capture_output=True, text=True)
                
                if commit_result.returncode != 0:
                    logger.error(f"Commit failed: {commit_result.stderr}")
                    return JsonResponse({'status': 'error', 'error': f"Commit failed: {commit_result.stderr}"}, status=500)

                # Push the changes
                push_command = ['git', 'push', 'origin', f'{current_branch}:{current_branch}']
                push_result = subprocess.run(push_command, cwd=temp_repo_path, capture_output=True, text=True)
                
                if push_result.returncode != 0:
                    logger.error(f"Push failed: {push_result.stderr}")
                    return JsonResponse({'status': 'error', 'error': f"Push failed: {push_result.stderr}"}, status=500)

                # Get the updated file content
                updated_file_content, _ = get_file_content(repo_path, file_path)

            return JsonResponse({'status': 'success', 'updated_content': updated_file_content})

        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return JsonResponse({'status': 'error', 'error': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'error': 'Invalid request method'}, status=405)
    
import logging
import os
import subprocess
from django.views import View
from django.http import HttpResponse, HttpResponseServerError, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

logger = logging.getLogger(__name__)

@method_decorator(csrf_exempt, name='dispatch')
class GitService(View):
    def get(self, request, repo_name, path=None):
        logger.info(f"GET request received for repo: {repo_name}, path: {path}")
        try:
            repo_path = os.path.join(REPO_BASE_PATH, f"{repo_name}.git")
            if not os.path.exists(repo_path):
                logger.error(f"Repository not found: {repo_path}")
                return HttpResponse(f"Repository '{repo_name}' not found.", status=404)

            service = request.GET.get('service')
            if service in ['git-upload-pack', 'git-receive-pack']:
                return self.handle_service_advertisement(repo_path, service)
            elif path:
                return self.handle_static_file(repo_path, path)
            else:
                return self.handle_info_refs(repo_path)
        except Exception as e:
            logger.exception(f"Error in GET request: {str(e)}")
            return HttpResponseServerError(f"Internal server error: {str(e)}")

    def post(self, request, repo_name, path=None):
        logger.info(f"POST request received for repo: {repo_name}, path: {path}")
        try:
            repo_path = os.path.join(REPO_BASE_PATH, f"{repo_name}.git")
            if not os.path.exists(repo_path):
                logger.error(f"Repository not found: {repo_path}")
                return HttpResponse(f"Repository '{repo_name}' not found.", status=404)

            if path in ['git-upload-pack', 'git-receive-pack']:
                return self.handle_service(repo_path, path, request.body)
            else:
                logger.error(f"Invalid service requested: {path}")
                return HttpResponseServerError("Invalid service requested")
        except Exception as e:
            logger.exception(f"Error in POST request: {str(e)}")
            return HttpResponseServerError(f"Internal server error: {str(e)}")
    def handle_service_advertisement(self, repo_path, service):
        logger.info(f"Handling service advertisement: {service} for repo: {repo_path}")
        try:
            cmd = ['git', service[4:], '--advertise-refs', repo_path]
            logger.debug(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Error in git {service}: {result.stderr}")
                return HttpResponseServerError(f"Error in Git operation: {result.stderr}")

            response = HttpResponse(content_type=f'application/x-{service}-advertisement')
            packet = f"# service={service}\n"
            length = len(packet) + 4
            response.write(f"{length:04x}{packet}0000")
            response.write(result.stdout)
            return response
        except Exception as e:
            logger.exception(f"Error in handle_service_advertisement: {str(e)}")
            return HttpResponseServerError(f"Internal server error: {str(e)}")

    def handle_info_refs(self, repo_path):
        logger.info(f"Handling info/refs for repo: {repo_path}")
        try:
            cmd = ['git', 'update-server-info']
            logger.debug(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Error in git update-server-info: {result.stderr}")
                return HttpResponseServerError(f"Error in Git operation: {result.stderr}")

            refs_file = os.path.join(repo_path, 'info', 'refs')
            if not os.path.exists(refs_file):
                logger.error(f"info/refs file not found: {refs_file}")
                return HttpResponseServerError("info/refs file not found")

            with open(refs_file, 'rb') as f:
                content = f.read()

            return HttpResponse(content, content_type='text/plain')
        except Exception as e:
            logger.exception(f"Error in handle_info_refs: {str(e)}")
            return HttpResponseServerError(f"Internal server error: {str(e)}")

    def handle_service(self, repo_path, service, input_data):
        logger.info(f"Handling service: {service} for repo: {repo_path}")
        try:
            cmd = ['git', service[4:], '--stateless-rpc', repo_path]
            logger.debug(f"Running command: {' '.join(cmd)}")
            
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate(input=input_data)

            if process.returncode != 0:
                logger.error(f"Error in Git operation: {stderr.decode()}")
                return HttpResponseServerError(f"Error in Git operation: {stderr.decode()}")

            content_type = f'application/x-{service}-result'
            return HttpResponse(stdout, content_type=content_type)
        except Exception as e:
            logger.exception(f"Error in handle_service: {str(e)}")
            return HttpResponseServerError(f"Internal server error: {str(e)}")

    def handle_static_file(self, repo_path, path):
        logger.info(f"Handling static file: {path} for repo: {repo_path}")
        try:
            file_path = os.path.join(repo_path, path)
            if not os.path.exists(file_path):
                logger.error(f"File not found: {file_path}")
                return HttpResponse("File not found", status=404)

            return FileResponse(open(file_path, 'rb'))
        except Exception as e:
            logger.exception(f"Error in handle_static_file: {str(e)}")
            return HttpResponseServerError(f"Internal server error: {str(e)}")