import re
import ast

with open('D:/cicd/cicd_tool/gitmgmt/views.py', 'r') as f:
    lines = f.readlines()

def replace_function(lines, func_name, new_code):
    class FunctionVisitor(ast.NodeVisitor):
        def __init__(self):
            self.start = None
            self.end = None
        def visit_FunctionDef(self, node):
            if node.name == func_name:
                self.start = node.lineno
                self.end = node.end_lineno

    tree = ast.parse("".join(lines))
    visitor = FunctionVisitor()
    visitor.visit(tree)
    
    if visitor.start and visitor.end:
        return lines[:visitor.start-1] + [new_code + "\n"] + lines[visitor.end:]
    return lines

merge_branch_code = """
def merge_branch(request, repository_name):
    repository = get_object_or_404(Repository, name=repository_name)
    repo_path = os.path.join(REPO_BASE_PATH, f"{repository.name}.git")

    if request.method == 'POST':
        target_branch_name = request.POST.get('merge_target')
        current_branch_name = request.GET.get('branch', 'main')

        if not target_branch_name:
            messages.error(request, "No target branch selected for merging.")
            return redirect('repository_detail', repository_name=repository.name)
            
        import re
        if not re.match(r'^[A-Za-z0-9_.-]+$', target_branch_name) or not re.match(r'^[A-Za-z0-9_.-]+$', current_branch_name):
            messages.error(request, "Invalid branch name format.")
            return redirect('repository_detail', repository_name=repository.name)

        # Branch Protection Check
        from .models import Branch
        target_branch_obj = Branch.objects.filter(repository=repository, name=target_branch_name).first()
        if target_branch_obj and target_branch_obj.is_protected and not (repository.owner == request.user or request.user.is_staff):
             messages.error(request, f"Branch '{target_branch_name}' is protected. Only owners or admins can merge into it.")
             return redirect('repository_detail', repository_name=repository.name)

        if target_branch_name == current_branch_name:
            messages.error(request, "Cannot merge a branch into itself.")
            return redirect('repository_detail', repository_name=repository.name)

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                repo = Repo.clone_from(repo_path, temp_dir)
                
                # Verify branches exist both locally and remotely
                remote_branches = [ref.name.split('/')[-1] for ref in repo.remotes.origin.refs]
                if target_branch_name not in remote_branches or current_branch_name not in remote_branches:
                    messages.error(request, "One or both branches don't exist remotely.")
                    return redirect('repository_detail', repository_name=repository.name)

                # Fetch all latest changes
                repo.git.fetch('--all')

                # Checkout current branch safely
                repo.git.checkout('--', current_branch_name)
                repo.git.pull('origin', current_branch_name)

                # Verify if merge is needed safely
                if repo.git.diff('--', f'origin/{current_branch_name}..origin/{target_branch_name}') == "":
                    messages.info(request, "No changes to merge. Branches are already in sync.")
                    return redirect('repository_detail', repository_name=repository.name)

                # Attempt merge safely
                try:
                    repo.git.merge(f'origin/{target_branch_name}')
                    repo.git.push('origin', current_branch_name)
                    messages.success(request, f"Successfully merged {target_branch_name} into {current_branch_name}.")
                except GitCommandError as e:
                    repo.git.merge('--abort')
                    if 'CONFLICT' in str(e):
                        messages.error(request, "Merge conflict detected. Please resolve conflicts manually.")
                    else:
                        logger.error(f"Merge failed: {str(e)}")
                        messages.error(request, "Merge failed due to a git error.")
                    return redirect('repository_detail', repository_name=repository.name)

            except Exception as e:
                logger.error(f"Unexpected error during merge: {str(e)}")
                messages.error(request, "Unexpected error during merge.")
                return redirect('repository_detail', repository_name=repository.name)

    return redirect('repository_detail', repository_name=repository.name)
"""

merge_pull_request_code = """
def merge_pull_request(request, pull_request_id):
    pull_request = get_object_or_404(PullRequest, id=pull_request_id)
    repo_path = os.path.join(REPO_BASE_PATH, f"{pull_request.repository.name}.git")

    if request.method == 'POST':
        # Branch Protection Check
        from .models import Branch
        target_branch_obj = Branch.objects.filter(repository=pull_request.repository, name=pull_request.target_branch.name).first()
        if target_branch_obj and target_branch_obj.is_protected and not (pull_request.repository.owner == request.user or request.user.is_staff):
             messages.error(request, f"Target branch '{pull_request.target_branch.name}' is protected. Only owners or admins can merge into it.")
             return redirect('pull_request_detail', pull_request_id=pull_request.id)

        # Validate PR can be merged
        if pull_request.status != 'open':
            messages.error(request, "Only open pull requests can be merged.")
            return redirect('pull_request_detail', pull_request_id=pull_request.id)

        source_branch = pull_request.source_branch.name
        target_branch = pull_request.target_branch.name
        
        import re
        if not re.match(r'^[A-Za-z0-9_.-]+$', source_branch) or not re.match(r'^[A-Za-z0-9_.-]+$', target_branch):
            messages.error(request, "Invalid branch name format in PR.")
            return redirect('pull_request_detail', pull_request_id=pull_request.id)

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

                # Checkout target branch safely
                repo.git.checkout('--', target_branch)
                repo.git.pull('origin', target_branch)

                # Verify merge is needed safely
                if repo.git.diff('--', f'origin/{target_branch}..origin/{source_branch}') == "":
                    messages.info(request, "No changes to merge. Branches are already in sync.")
                    pull_request.status = 'merged'
                    pull_request.save()
                    return redirect('pull_request_detail', pull_request_id=pull_request.id)

                # Attempt merge safely
                try:
                    repo.git.merge(f'origin/{source_branch}')
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
                        logger.error(f"Merge failed: {str(e)}")
                        messages.error(request, "Merge failed due to a git error.")
                    return redirect('pull_request_detail', pull_request_id=pull_request.id)

            except Exception as e:
                logger.error(f"Unexpected error during merge PR: {str(e)}")
                messages.error(request, "Unexpected error during merge.")
                return redirect('pull_request_detail', pull_request_id=pull_request.id)

    return redirect('pull_request_detail', pull_request_id=pull_request.id)
"""

upload_file_code = """
def upload_file(request, repository_name):
    repository = get_object_or_404(Repository, name=repository_name)
    repo_path = os.path.join(REPO_BASE_PATH, f"{repository.name}.git")
    current_branch = request.GET.get('branch', 'main')  # Default to main

    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        
        # Path Traversal Prevention
        safe_file_name = os.path.basename(file.name)
        if not safe_file_name:
            messages.error(request, "Invalid file name.")
            return redirect(reverse('repository_detail', kwargs={'repository_name': repository.name}) + f"?branch={current_branch}")
            
        import re
        if not re.match(r'^[A-Za-z0-9_.-]+$', current_branch):
            messages.error(request, "Invalid branch name format.")
            return redirect(reverse('repository_detail', kwargs={'repository_name': repository.name}) + "?branch=main")

        commit_message = request.POST.get('commit_message', f"Added {safe_file_name}")

        try:
            # Clone the repo into a temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_repo = Repo.clone_from(repo_path, temp_dir)
                git = temp_repo.git
                
                # Fetch latest changes
                git.fetch('--all')
                
                # Check if the branch exists remotely
                remote_branches = git.branch('-r')  # List remote branches
                
                if f'origin/{current_branch}' in remote_branches:
                    git.checkout('-B', current_branch, f'origin/{current_branch}')  # Ensure it's linked to remote
                else:
                    git.checkout('-b', current_branch)

                # Save file in the repo
                temp_file_path = os.path.join(temp_dir, safe_file_name)
                # Verify path traversal (redundant due to basename, but good practice)
                if not os.path.abspath(temp_file_path).startswith(os.path.abspath(temp_dir)):
                    messages.error(request, "Invalid file path.")
                    return redirect(reverse('repository_detail', kwargs={'repository_name': repository.name}) + f"?branch={current_branch}")
                    
                with open(temp_file_path, 'wb+') as destination:
                    for chunk in file.chunks():
                        destination.write(chunk)

                # Add file, commit, and push changes safely
                git.add('--', safe_file_name)
                status_output = git.status()

                if "nothing to commit" in status_output.lower():
                    messages.error(request, "No changes detected. File may not have been saved.")
                    return redirect(reverse('repository_detail', kwargs={'repository_name': repository.name}) + f"?branch={current_branch}")

                # Commit the file
                temp_repo.index.commit(commit_message)

                # Push changes explicitly to the correct branch
                git.push('origin', current_branch)

                messages.success(request, f"File '{safe_file_name}' uploaded successfully to branch '{current_branch}'.")
        except GitCommandError as e:
            logger.error(f"Git error while uploading file: {str(e)}")
            messages.error(request, "Git error while uploading file.")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            messages.error(request, "Unexpected error occurred during upload.")

        return redirect(reverse('repository_detail', kwargs={'repository_name': repository.name}) + f"?branch={current_branch}")

    return render(request, 'gitmgmt/upload_file.html', {'repository': repository, 'current_branch': current_branch})
"""

create_branch_code = """
def create_branch(request, repository_name):
    repository = get_object_or_404(Repository, name=repository_name)
    repo_path = os.path.join(REPO_BASE_PATH, f"{repository.name}.git")

    if request.method == 'POST':
        branch_name = request.POST.get('branch_name')
        source_branch_name = request.POST.get('source_branch', 'main')

        if not branch_name:
            messages.error(request, "Branch name is required.")
            return redirect('repository_detail', repository_name=repository.name)
            
        import re
        if not re.match(r'^[A-Za-z0-9_.-]+$', branch_name) or not re.match(r'^[A-Za-z0-9_.-]+$', source_branch_name):
            messages.error(request, "Invalid branch name format.")
            return redirect('repository_detail', repository_name=repository.name)

        try:
            repo = Repo(repo_path)

            # Check if branch exists
            if branch_name in repo.heads:
                messages.error(request, f"Branch '{branch_name}' already exists.")
                return redirect('repository_detail', repository_name=repository.name)

            # Validate source branch
            if source_branch_name not in repo.heads:
                messages.error(request, f"Source branch '{source_branch_name}' does not exist.")
                return redirect('repository_detail', repository_name=repository.name)

            # Create new branch from source branch
            source_branch = repo.heads[source_branch_name]
            new_branch = repo.create_head(branch_name, source_branch.commit)

            messages.success(request, f"Branch '{branch_name}' created successfully from '{source_branch_name}'.")
            return redirect('repository_detail', repository_name=repository.name)

        except GitCommandError as e:
            logger.error(f"Git error creating branch: {str(e)}")
            messages.error(request, "Git error occurred while creating branch.")
        except Exception as e:
            logger.error(f"Failed to create branch: {str(e)}")
            messages.error(request, "Failed to create branch.")

    return redirect('repository_detail', repository_name=repository.name)
"""

edit_and_save_file_code = """
@csrf_exempt
def edit_and_save_file(request, repository_name, file_path):
    repository = get_object_or_404(Repository, name=repository_name)
    repo_path = os.path.join(REPO_BASE_PATH, f"{repository.name}.git")

    def get_file_content(repo_path, file_path):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_repo_path = os.path.join(temp_dir, repository.name)
            clone_command = ['git', 'clone', repo_path, temp_repo_path]
            subprocess.run(clone_command, check=True, capture_output=True, text=True)

            branch_command = ['git', 'rev-parse', '--abbrev-ref', 'HEAD']
            branch_result = subprocess.run(branch_command, cwd=temp_repo_path, capture_output=True, text=True, check=True)
            current_branch = branch_result.stdout.strip()

            # Path Traversal Prevention
            normalized_path = os.path.normpath(file_path.replace('\\\\', '/')).lstrip('/')
            temp_file_path = os.path.abspath(os.path.join(temp_repo_path, normalized_path))
            if not temp_file_path.startswith(os.path.abspath(temp_repo_path)):
                raise ValueError("Invalid file path: path traversal detected.")

            with open(temp_file_path, 'r', encoding='utf-8') as file:
                return file.read(), current_branch

    if request.method == 'GET':
        try:
            file_content, current_branch = get_file_content(repo_path, file_path)
        except Exception as e:
            logger.error(f"Error reading file: {str(e)}")
            return JsonResponse({'status': 'error', 'error': "Error reading file"}, status=500)

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
                
            import re
            if not re.match(r'^[A-Za-z0-9_.-]+$', current_branch):
                return JsonResponse({'status': 'error', 'error': 'Invalid branch name'}, status=400)

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_repo_path = os.path.join(temp_dir, repository.name)
                
                # Clone the repository
                clone_command = ['git', 'clone', repo_path, temp_repo_path]
                subprocess.run(clone_command, check=True, capture_output=True, text=True)

                # Checkout the current branch safely
                checkout_command = ['git', 'checkout', '--', current_branch]
                subprocess.run(checkout_command, cwd=temp_repo_path, check=True, capture_output=True, text=True)

                # Write the new content to the file safely
                normalized_path = os.path.normpath(file_path.replace('\\\\', '/')).lstrip('/')
                temp_file_path = os.path.abspath(os.path.join(temp_repo_path, normalized_path))
                if not temp_file_path.startswith(os.path.abspath(temp_repo_path)):
                    return JsonResponse({'status': 'error', 'error': 'Invalid file path'}, status=400)
                    
                os.makedirs(os.path.dirname(temp_file_path), exist_ok=True)
                with open(temp_file_path, 'w', encoding='utf-8') as file:
                    file.write(file_content)

                # Configure Git
                subprocess.run(['git', 'config', 'user.email', "user@example.com"], cwd=temp_repo_path, check=True)
                subprocess.run(['git', 'config', 'user.name', "User"], cwd=temp_repo_path, check=True)

                # Stage the changes safely
                add_command = ['git', 'add', '--', normalized_path]
                subprocess.run(add_command, cwd=temp_repo_path, check=True, capture_output=True, text=True)

                # Commit the changes
                commit_command = ['git', 'commit', '-m', commit_message]
                commit_result = subprocess.run(commit_command, cwd=temp_repo_path, capture_output=True, text=True)
                
                if commit_result.returncode != 0:
                    logger.error(f"Commit failed: {commit_result.stderr}")
                    return JsonResponse({'status': 'error', 'error': "Commit failed. Please check your commit message."}, status=500)

                # Push the changes
                push_command = ['git', 'push', 'origin', f'{current_branch}:{current_branch}']
                push_result = subprocess.run(push_command, cwd=temp_repo_path, capture_output=True, text=True)
                
                if push_result.returncode != 0:
                    logger.error(f"Push failed: {push_result.stderr}")
                    return JsonResponse({'status': 'error', 'error': "Push failed. Remote may have rejected the commit."}, status=500)

                # Get the updated file content
                updated_file_content, _ = get_file_content(repo_path, file_path)

            return JsonResponse({'status': 'success', 'updated_content': updated_file_content})

        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return JsonResponse({'status': 'error', 'error': "An internal error occurred."}, status=500)

    return JsonResponse({'status': 'error', 'error': 'Invalid request method'}, status=405)
"""

# Apply modifications in reverse order to not mess up line numbers if multiple passes were used,
# but we do it one by one safely passing the modified lines down.
lines = replace_function(lines, 'edit_and_save_file', edit_and_save_file_code)
lines = replace_function(lines, 'create_branch', create_branch_code)
lines = replace_function(lines, 'upload_file', upload_file_code)
lines = replace_function(lines, 'merge_pull_request', merge_pull_request_code)
lines = replace_function(lines, 'merge_branch', merge_branch_code)

with open('D:/cicd/cicd_tool/gitmgmt/views.py', 'w') as f:
    f.writelines(lines)

print("Updated views.py successfully")
