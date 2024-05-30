from django.shortcuts import render, redirect, get_object_or_404
from .models import Repository, PullRequest
from .forms import RepositoryForm, PullRequestForm
import os
from git import Repo

REPO_BASE_PATH = 'D:/repos'

from django.shortcuts import render, get_object_or_404, redirect
from .models import Repository

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
from django.shortcuts import render, redirect, HttpResponse
from .forms import RepositoryForm

REPO_BASE_PATH = 'D:/repos'  # Update this to your repositories' base path

def initialize_repository(name):
    repo_path = os.path.join(REPO_BASE_PATH, f"{name}.git")
    
    # Create the repository directory if it doesn't exist
    if not os.path.exists(repo_path):
        os.makedirs(repo_path)
    
    # Initialize the repository as bare
    repo = Repo.init(repo_path, bare=True)
    
    return repo

def create_repository(request):
    if request.method == 'POST':
        form = RepositoryForm(request.POST)
        if form.is_valid():
            repository = form.save(commit=False)
            repository.save()
            
            # Initialize the repository
            initialize_repository(repository.name)
            
            # Construct the clone URL
            clone_url = request.build_absolute_uri(f'/repos/{repository.name}.git')
            
            return HttpResponse(f"Repository created. Clone it using: git clone {clone_url}")
    else:
        form = RepositoryForm()
    return render(request, 'gitmgmt/repository_form.html', {'form': form})

import os
import subprocess
from django.http import StreamingHttpResponse, Http404
from git import Repo

REPO_BASE_PATH = 'D:/repos'  # Update this to your repositories' base path

def serve_repo(request, repo_name):
    repo_path = os.path.join(REPO_BASE_PATH, f"{repo_name}.git")
    if not os.path.isdir(repo_path):
        raise Http404("Repository not found")

    service = request.GET.get('service')
    if not service:
        raise Http404("Service not specified")

    repo = Repo(repo_path)

    if service == 'git-upload-pack':
        # Handle git-upload-pack service request
        return handle_git_service(repo, 'git-upload-pack')
    elif service == 'git-receive-pack':
        # Handle git-receive-pack service request
        return handle_git_service(repo, 'git-receive-pack')
    else:
        raise Http404("Service not supported")

def handle_git_service(repo, service_name):
    repo_path = repo.working_tree_dir
    git_cmd = [service_name, '--stateless-rpc', repo_path]
    env = os.environ.copy()
    env['GIT_PROJECT_ROOT'] = REPO_BASE_PATH
    env['PATH_INFO'] = repo_path

    process = subprocess.Popen(git_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

    def generate():
        while True:
            output = process.stdout.read(8192)
            if not output:
                break
            yield output

    content_type = f'application/x-{service_name}-advertisement' if service_name == 'git-upload-pack' else f'application/x-{service_name}-result'
    return StreamingHttpResponse(generate(), content_type=content_type)



from django.shortcuts import render, redirect, get_object_or_404
from .models import Repository, PullRequest
from .forms import RepositoryForm, PullRequestForm, UploadFileForm
import os
from git import Repo

IGNORE_FILES = ['.git']

# views.py

def repository_detail(request, repository_id):
    repository = get_object_or_404(Repository, id=repository_id)
    repo_path = os.path.join(REPO_BASE_PATH, repository.name)
    
    try:
        repo = Repo(repo_path)
        branches = [branch.name for branch in repo.branches]
        current_branch = request.GET.get('branch', repo.active_branch.name)
        repo.git.checkout(current_branch)

        files = []
        for root, _, filenames in os.walk(repo_path):
            if any(ignore in root for ignore in IGNORE_FILES):
                continue
            for filename in filenames:
                if filename in IGNORE_FILES:
                    continue
                relative_path = os.path.relpath(os.path.join(root, filename), repo_path)
                files.append(relative_path)

        last_commit = next(repo.iter_commits(), None)
        last_commit_hash = last_commit.hexsha if last_commit else None

    except Exception as e:
        branches = []
        files = []
        current_branch = None
        last_commit_hash = None
        print(f"Error accessing repository: {e}")

    return render(request, 'gitmgmt/repository_detail.html', {
        'repository': repository,
        'branches': branches,
        'current_branch': current_branch,
        'files': files,
        'last_commit_hash': last_commit_hash,
    })


def create_pull_request(request, repository_id):
    repository = get_object_or_404(Repository, id=repository_id)
    if request.method == 'POST':
        form = PullRequestForm(request.POST)
        if form.is_valid():
            pull_request = form.save(commit=False)
            pull_request.repository = repository
            pull_request.save()
            return redirect('pull_request_detail', pull_request_id=pull_request.id)
    else:
        form = PullRequestForm()
    return render(request, 'gitmgmt/pull_request_form.html', {'form': form, 'repository': repository})

def pull_request_detail(request, pull_request_id):
    pull_request = get_object_or_404(PullRequest, id=pull_request_id)
    return render(request, 'gitmgmt/pull_request_detail.html', {'pull_request': pull_request})

from django.shortcuts import render, redirect, get_object_or_404
from .models import Repository
import os
from git import Repo

def upload_file(request, repository_id):
    repository = get_object_or_404(Repository, id=repository_id)
    repo_path = os.path.join(REPO_BASE_PATH, repository.name)
    repo = Repo(repo_path)

    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        file_path = os.path.join(repo_path, file.name)
        commit_message = request.POST.get('commit_message', f"Added {file.name}")

        # Write the uploaded file to the repository directory
        with open(file_path, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)

        # Add the file to the Git index and commit
        try:
            relative_file_path = os.path.relpath(file_path, repo_path)
            repo.index.add([relative_file_path])
            repo.index.commit(commit_message)
        except Exception as e:
            # Handle any errors that occur during adding and committing the file
            print(f"Error adding and committing file: {e}")
            # Optionally, you can return an error response here

        return redirect('repository_detail', repository_id=repository.id)

    return render(request, 'gitmgmt/upload_file.html', {'repository': repository})

from django.http import HttpResponseBadRequest

def create_branch(request, repository_id):
    if request.method == 'POST':
        branch_name = request.POST.get('branch_name')
        if branch_name:
            repository = get_object_or_404(Repository, id=repository_id)
            repo_path = os.path.join(REPO_BASE_PATH, repository.name)
            repo = Repo(repo_path)
            
            try:
                # Create new branch
                repo.git.checkout(b=branch_name)
                return redirect('repository_detail', repository_id=repository.id)
            except Exception as e:
                return HttpResponseBadRequest(f"Failed to create branch: {e}")
        else:
            return HttpResponseBadRequest("Branch name is required.")
    else:
        return HttpResponseBadRequest("Invalid request method.")


def view_logs(request, repository_id):
    repository = get_object_or_404(Repository, id=repository_id)
    repo_path = os.path.join(REPO_BASE_PATH, repository.name)
    
    try:
        repo = Repo(repo_path)
        logs = []
        for log in repo.iter_commits():
            logs.append({
                'hash': log.hexsha,
                'message': log.message,
                'author': log.author.name,
                'date': log.committed_datetime.strftime('%Y-%m-%d %H:%M:%S'),  # Better date formatting
            })
    except Exception as e:
        logs = []
        print(f"Error accessing logs: {e}")

    return render(request, 'gitmgmt/view_logs.html', {
        'repository': repository,
        'logs': logs,
    })

# views.py

from django.shortcuts import render, redirect, get_object_or_404
from .models import Repository
from git import Repo
import os

REPO_BASE_PATH = 'D:/repos'

def edit_and_save_file(request, repository_id, file_path):
    repository = get_object_or_404(Repository, id=repository_id)
    repo_path = os.path.join(REPO_BASE_PATH, repository.name)
    full_file_path = os.path.join(repo_path, file_path)

    if request.method == 'GET':
        # Read the content of the file
        try:
            with open(full_file_path, 'r') as file:
                file_content = file.read()
        except FileNotFoundError:
            # Handle the case where the file does not exist
            file_content = ""
        
        return render(request, 'gitmgmt/edit_and_save_file.html', {
            'repository': repository,
            'file_path': file_path,
            'file_content': file_content,
        })
    
    elif request.method == 'POST':
        # Get the updated file content and commit message from the form
        file_content = request.POST.get('code', '')
        commit_message = request.POST.get('commit_message', '')

        # Save the updated content to the file
        try:
            with open(full_file_path, 'w') as file:
                file.write(file_content)
        except FileNotFoundError:
            # Handle the case where the file does not exist
            pass

        # Add the changes to the Git index and commit with the provided message
        repo = Repo(repo_path)
        try:
            relative_file_path = os.path.relpath(full_file_path, repo_path)
            repo.index.add([relative_file_path])
            repo.index.commit(commit_message)
        except Exception as e:
            # Handle any errors that occur during adding and committing the file
            print(f"Error adding and committing file: {e}")
            # Optionally, you can return an error response here

        return redirect('repository_detail', repository_id=repository.id)

import os
import subprocess
from django.http import StreamingHttpResponse, Http404
from django.views import View
import logging

REPO_BASE_PATH = 'D:/repos'  # Update this to your repositories' base path

logger = logging.getLogger(__name__)

class GitService(View):
    def get(self, request, repo_name):
        repo_path = os.path.join(REPO_BASE_PATH, f"{repo_name}.git")
        logger.debug(f"Requested repository path: {repo_path}")
        
        if not os.path.isdir(repo_path):
            logger.error(f"Repository not found: {repo_name}")
            raise Http404("Repository not found")

        service = request.GET.get('service')
        logger.debug(f"Requested service: {service}")
        
        if not service:
            logger.error("Service not specified")
            raise Http404("Service not specified")

        if service == 'git-upload-pack':
            return self.handle_git_service(repo_path, 'git-upload-pack')
        elif service == 'git-receive-pack':
            return self.handle_git_service(repo_path, 'git-receive-pack')
        else:
            logger.error(f"Unsupported service: {service}")
            raise Http404("Service not supported")

    def handle_git_service(self, repo_path, service_name):
        git_cmd = [service_name, '--stateless-rpc', repo_path]
        logger.debug(f"Executing git command: {' '.join(git_cmd)}")
        
        process = subprocess.Popen(git_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def generate():
            while True:
                output = process.stdout.read(8192)
                if not output:
                    break
                yield output

        content_type = f'application/x-{service_name}-advertisement' if service_name == 'git-upload-pack' else f'application/x-{service_name}-result'
        return StreamingHttpResponse(generate(), content_type=content_type)
