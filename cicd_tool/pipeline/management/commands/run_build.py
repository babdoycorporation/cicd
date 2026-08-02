import os
import subprocess
from django.core.management.base import BaseCommand
from pipeline.models import Build
import git

BASE_REPO_DIR = 'D:/cicd/'  # Set this to a suitable directory

class Command(BaseCommand):
    help = 'Run a build'

    def handle(self, *args, **kwargs):
        # Cleanup stale 'running' builds
        from django.utils import timezone
        from datetime import timedelta
        
        stale_threshold = timezone.now() - timedelta(minutes=30)
        stale_builds = Build.objects.filter(status='running', updated_at__lt=stale_threshold)
        for stale_build in stale_builds:
            stale_build.status = 'failed'
            stale_build.log += '\n[System] Build timed out or process aborted unexpectedly.\n'
            stale_build.save(update_fields=['status', 'log'])
            self.stdout.write(f"Cleaned up stale build #{stale_build.id}")

        builds = Build.objects.filter(status='pending')
        for build in builds:
            build.status = 'running'
            build.save(update_fields=['status'])
            self.stdout.write(f"Running build for project {build.project.name}")

            repo_url = build.project.repository_url
            repo_dir = os.path.join(BASE_REPO_DIR, build.project.name)

            try:
                if not os.path.exists(repo_dir):
                    os.makedirs(repo_dir)
                    self.stdout.write(f"Cloning repository {repo_url} into {repo_dir}")
                    repo = git.Repo.clone_from(repo_url, repo_dir)
                    build.log = 'Repository cloned.\n'
                else:
                    self.stdout.write(f"Fetching latest changes for repository {repo_url}")
                    repo = git.Repo(repo_dir)
                    repo.remote().fetch()
                    repo.git.checkout('main')  # or the appropriate branch
                    repo.git.pull()
                    build.log = 'Repository updated.\n'

                build.log += 'Building project...\n'

                # Step 1: Find requirements.txt file in the repository directory
                requirements_file = self.find_requirements_file(repo_dir)
                if requirements_file:
                    build.log += 'Installing dependencies...\n'
                    result = subprocess.run(['pip', 'install', '-r', requirements_file], capture_output=True, text=True)
                    build.log += result.stdout + result.stderr
                    if result.returncode != 0:
                        raise Exception("Failed to install dependencies")
                else:
                    raise Exception("requirements.txt file not found in the repository")

                # Steps 2 and 3: Run tests and deploy (optional) remain unchanged

                build.status = 'success'
                build.log += 'Build succeeded.\n'
                self.stdout.write("Build succeeded")
            except git.exc.GitError as git_error:
                build.status = 'failed'
                build.log += f'Git error: {git_error}\n'
                self.stdout.write(f"Git error: {git_error}")
            except Exception as e:
                build.status = 'failed'
                build.log += f'Build failed: {e}\n'
                self.stdout.write(f"Build failed: {e}")

            build.save(update_fields=['status', 'log'])

    def find_requirements_file(self, directory):
        """Recursively search for requirements.txt file within the directory."""
        for root, dirs, files in os.walk(directory):
            if 'requirements.txt' in files:
                return os.path.join(root, 'requirements.txt')
        return None
