from django import template

register = template.Library()

@register.filter
def can_clone(repo, user):
    if not repo or not user:
        return False
    if hasattr(repo, 'user_can_clone'):
        return repo.user_can_clone(user)
    return False

@register.filter
def can_push(repo, user):
    if not repo or not user:
        return False
    if hasattr(repo, 'user_can_push'):
        return repo.user_can_push(user)
    return False

@register.filter
def pending_request(repo, user):
    if not repo or not user or not user.is_authenticated:
        return None
    # If the user can already clone, no pending clone request should block them!
    if hasattr(repo, 'user_can_clone') and repo.user_can_clone(user):
        return None
    try:
        from django.db.models import Q
        q = Q(user=user)
        if user.email:
            q |= Q(user__email__iexact=user.email)
        return repo.access_requests.filter(q, status='pending').first()
    except Exception:
        return None

@register.filter
def is_admin_or_owner(repo, user):
    if not user or not user.is_authenticated or not repo:
        return False
    if user.is_superuser or user.is_staff or repo.owner == user:
        return True
    try:
        from gitmgmt.views import _user_can_manage_repo
        return _user_can_manage_repo(user, repo)
    except Exception:
        return False
