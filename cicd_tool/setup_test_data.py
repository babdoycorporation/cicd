import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cicd_tool.settings')
django.setup()

from django.contrib.auth.models import User
from gitmgmt.models import Organization, UserProfile
from pipeline.models import Project, Application, Environment

def run():
    # 1. Create Users
    print("Creating users...")
    admin, created = User.objects.get_or_create(username='admin', defaults={'is_superuser': True, 'is_staff': True})
    if created:
        admin.set_password('admin123')
        admin.save()
        UserProfile.objects.create(user=admin, bio="Release Rocket Admin")
        print("Created superuser 'admin' with password 'admin123'")

    dev1, created = User.objects.get_or_create(username='dev1', defaults={'is_staff': False})
    if created:
        dev1.set_password('dev123')
        dev1.save()
        UserProfile.objects.create(user=dev1, bio="Frontend Developer")
        print("Created standard user 'dev1' with password 'dev123'")

    dev2, created = User.objects.get_or_create(username='dev2', defaults={'is_staff': False})
    if created:
        dev2.set_password('dev123')
        dev2.save()
        UserProfile.objects.create(user=dev2, bio="Backend Developer")
        print("Created standard user 'dev2' with password 'dev123'")

    # 2. Create Environments
    print("Creating environments...")
    env_dev, _ = Environment.objects.get_or_create(name='dev', description='Development Environment')
    env_qa, _ = Environment.objects.get_or_create(name='qa', description='QA Environment')
    env_prod, _ = Environment.objects.get_or_create(name='prod', description='Production Environment')

    # 3. Create Organization
    print("Creating default organization...")
    org, _ = Organization.objects.get_or_create(name='Acme Corp', defaults={'owner': admin, 'description': 'The default testing organization'})

    # 4. Create Project
    print("Creating test project...")
    project, _ = Project.objects.get_or_create(name='Acme Core', defaults={'organization': org})

    # 5. Create Application
    print("Creating test application...")
    app, _ = Application.objects.get_or_create(name='auth-service', defaults={'project': project})

    print("Test data initialization complete!")

if __name__ == '__main__':
    run()
