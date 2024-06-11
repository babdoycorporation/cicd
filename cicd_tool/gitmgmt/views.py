from django.shortcuts import render, redirect, get_object_or_404
from .models import Repository, PullRequest
from .forms import RepositoryForm, PullRequestForm
import os
from git import Repo
from django.http import HttpResponse

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
from git import Repo, GitCommandError
from django.http import HttpResponse
from .forms import RepositoryForm
from django.shortcuts import render, redirect
import os
from git import Repo, GitCommandError

REPO_BASE_PATH = 'D:/Repos'  # Update this to your repositories' base path

def initialize_repository(name):
    repo_path = os.path.join(REPO_BASE_PATH, f"{name}.git")
    
    try:
        # Create the repository directory if it doesn't exist
        if not os.path.exists(repo_path):
            os.makedirs(repo_path)
        
        # Initialize the repository as bare
        repo = Repo.init(repo_path, bare=True)
        
        # No need to create an initial commit or default branch for a bare repository
        
        return repo
    
    except GitCommandError as e:
        print(f"Error occurred: {e}")
        return None


def create_repository(request):
    if request.method == 'POST':
        form = RepositoryForm(request.POST)
        if form.is_valid():
            repository = form.save(commit=False)
            repository.save()
            
            # Initialize the repository
            initialize_repository(repository.name)
            
            # Construct the clone URL
            clone_url = request.build_absolute_uri(f'{repository.name}.git')
            
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


from django.shortcuts import render, get_object_or_404
from .models import Repository
from git import Repo
import os

IGNORE_FILES = ['.git']

def repository_detail(request, repository_id):
    repository = get_object_or_404(Repository, id=repository_id)
    repo_path = os.path.join(REPO_BASE_PATH, repository.name)
    
    try:
        repo = Repo(repo_path)
        branches = [branch.name for branch in repo.branches]
        current_branch = request.GET.get('branch', 'main')
        
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

        # Get the last commit
        last_commit = repo.head.commit
        last_commit_hash = last_commit.hexsha
        last_commit_message = last_commit.message

    except Exception as e:
        print(f"Error accessing repository: {e}")
        branches = []
        files = []
        current_branch = None
        last_commit_hash = None
        last_commit_message = None

    return render(request, 'gitmgmt/repository_detail.html', {
        'repository': repository,
        'branches': branches,
        'current_branch': current_branch,
        'files': files,
        'last_commit_hash': last_commit_hash,
        'last_commit_message': last_commit_message,
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
            print(f"Error adding and committing file: {e}")

        return redirect('repository_detail', repository_id=repository.id)

    return render(request, 'gitmgmt/upload_file.html', {'repository': repository})


from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from git import Repo, NoSuchPathError
import os

def create_branch(request, repository_id):
    if request.method == 'POST':
        branch_name = request.POST.get('branch_name')
        if branch_name:
            repository = get_object_or_404(Repository, id=repository_id)
            repo_path = os.path.join(REPO_BASE_PATH, f"{repository.name}")
            
            # Debugging output
            print("Repository path:", repo_path)
            
            try:
                # Check if the repository exists
                if not os.path.exists(repo_path):
                    return HttpResponseBadRequest("Repository does not exist.")

                # Initialize the repository
                repo = Repo(repo_path)
                
                # Create new branch
                repo.git.checkout(b=branch_name)
                return redirect('repository_detail', repository_id=repository.id)
            except NoSuchPathError:
                return HttpResponseBadRequest("Invalid repository path.")
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

from django.views import View
from django.http import StreamingHttpResponse, HttpResponseNotFound, HttpResponseServerError
import os
import subprocess
import logging

logger = logging.getLogger(__name__)

class GitService(View):
    def get(self, request, repo_name, path=None):
        repo_path = os.path.join(REPO_BASE_PATH, f"{repo_name}.git")
        if not os.path.exists(repo_path):
            logger.error(f"Repository not found: {repo_name}")
            return HttpResponseNotFound(f"Repository '{repo_name}' not found.")
        
        service = request.GET.get('service')
        if service not in ['git-upload-pack', 'git-receive-pack']:
            logger.error(f"Service not specified or not supported: {service}")
            return HttpResponseNotFound("Service not specified or not supported.")

        git_receive_pack = 'C:/Program Files/Git/mingw64/libexec/git-core/git-receive-pack.exe'
        git_upload_pack = 'C:/Program Files/Git/mingw64/libexec/git-core/git-upload-pack.exe'

        git_cmd = [git_receive_pack if service == 'git-receive-pack' else git_upload_pack]
        env = os.environ.copy()
        env['GIT_PROJECT_ROOT'] = REPO_BASE_PATH
        env['GIT_HTTP_EXPORT_ALL'] = '1'
        env['REMOTE_USER'] = request.user.username if request.user.is_authenticated else 'anonymous'
        env['PATH_INFO'] = f"/{repo_name}.git/{path or ''}"
        env['QUERY_STRING'] = request.META.get('QUERY_STRING', '')
        env['CONTENT_TYPE'] = request.META.get('CONTENT_TYPE', '')

        try:
            process = subprocess.Popen(git_cmd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            def generate():
                while True:
                    output = process.stdout.read(8192)
                    if not output:
                        break
                    yield output

            content_type = 'application/x-git-upload-pack-advertisement' if service == 'git-upload-pack' else 'application/x-git-receive-pack-result'
            return StreamingHttpResponse(generate(), content_type=content_type)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error executing Git command: {e}")
            return HttpResponseServerError(f"Error executing Git command: {e}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return HttpResponseServerError(f"Unexpected error: {e}")

    def post(self, request, repo_name, path=None):
        return self.get(request, repo_name, path)

