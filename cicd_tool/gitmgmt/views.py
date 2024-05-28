from django.shortcuts import render, redirect, get_object_or_404
from .models import Repository, PullRequest
from .forms import RepositoryForm, PullRequestForm
import os
from git import Repo

REPO_BASE_PATH = 'D:/repos'

def repository_list(request):
    query = request.GET.get('q')
    if query:
        repositories = Repository.objects.filter(name__icontains=query)
    else:
        repositories = Repository.objects.all()
    return render(request, 'gitmgmt/repository_list.html', {'repositories': repositories, 'query': query})

def initialize_repository(name):
    repo_path = os.path.join(REPO_BASE_PATH, name)
    if not os.path.exists(repo_path):
        os.makedirs(repo_path)
    repo = Repo.init(repo_path)
    # Create an initial commit if the repository is empty
    if not repo.head.is_valid():
        repo.index.commit("Initial commit")
    return repo


def create_repository(request):
    if request.method == 'POST':
        form = RepositoryForm(request.POST)
        if form.is_valid():
            repository = form.save(commit=False)
            repository.save()
            
            # Initialize the repository
            initialize_repository(repository.name)
            
            return redirect('repository_detail', repository_id=repository.id)
    else:
        form = RepositoryForm()
    return render(request, 'gitmgmt/repository_form.html', {'form': form})

from django.shortcuts import render, redirect, get_object_or_404
from .models import Repository, PullRequest
from .forms import RepositoryForm, PullRequestForm, UploadFileForm
import os
from git import Repo

IGNORE_FILES = ['.git']

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

        commits = []
        for commit in repo.iter_commits(current_branch):
            commits.append({
                'message': commit.message,
                'author': commit.author.name,
                'date': commit.committed_date,
            })

    except Exception as e:
        branches = []
        files = []
        current_branch = None
        commits = []
        print(f"Error accessing repository: {e}")

    if request.method == 'POST':
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            file = request.FILES['file']
            file_path = os.path.join(repo_path, file.name)
            with open(file_path, 'wb+') as destination:
                for chunk in file.chunks():
                    destination.write(chunk)
            relative_file_path = os.path.relpath(file_path, repo_path)
            repo.index.add([relative_file_path])
            repo.index.commit(f"Added {file.name}")
            return redirect('repository_detail', repository_id=repository.id)
    else:
        form = UploadFileForm()

    return render(request, 'gitmgmt/repository_detail.html', {
        'repository': repository,
        'branches': branches,
        'current_branch': current_branch,
        'files': files,
        'commits': commits,
        'form': form,
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

def add_file(request, repository_id):
    repository = get_object_or_404(Repository, id=repository_id)
    repo_path = os.path.join(REPO_BASE_PATH, repository.name)
    repo = Repo(repo_path)
    
    if request.method == 'POST':
        file = request.FILES['file']
        file_path = os.path.join(repo_path, file.name)
        
        with open(file_path, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)
        
        repo.index.add([file_path])
        repo.index.commit(f"Added {file.name}")
        
        return redirect('repository_detail', repository_id=repository.id)
    
    return render(request, 'gitmgmt/add_file.html', {'repository': repository})

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
