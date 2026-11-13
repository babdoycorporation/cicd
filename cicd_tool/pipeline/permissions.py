from functools import wraps
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from .models import Project

def get_user_project_role(user, project):
    """
    Determine user role in project.
    Returns: 'maintainer', 'developer', 'viewer', or None.
    Superusers and org owners/admins inherit 'maintainer' access.
    If project has no direct members and no org, default to 'maintainer' for logged-in user.
    """
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return 'maintainer'
    
    role = project.get_member_role(user)
    if role:
        return role
    
    # Open project fallback (no members and no organization assigned)
    if project.members.count() == 0 and project.organization is None:
        return 'maintainer'
        
    return 'viewer'


def require_project_role(allowed_roles):
    """
    Decorator for project views requiring specific role access.
    Usage: @require_project_role(['maintainer', 'developer'])
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            project_name = kwargs.get('project_name')
            if not project_name and args:
                project_name = args[0]
                
            if not project_name:
                raise ValueError("require_project_role requires a 'project_name' keyword or positional argument.")
                
            project = get_object_or_404(Project, name=project_name)
            user_role = get_user_project_role(request.user, project)
            
            if user_role not in allowed_roles:
                messages.error(
                    request,
                    f"Access Denied: You have '{user_role or 'no'}' access to {project.name}. "
                    f"Required role: {', '.join(allowed_roles).title()}."
                )
                return redirect('project_detail', project_name=project.name)
                
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
