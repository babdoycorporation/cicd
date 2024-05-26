from django.urls import path
from . import views

urlpatterns = [
    path('repositories/', views.repository_list, name='repository_list'),
    path('repositories/create/', views.create_repository, name='create_repository'),
    path('repositories/<int:repository_id>/', views.repository_detail, name='repository_detail'),
    path('repositories/<int:repository_id>/pull_request/create/', views.create_pull_request, name='create_pull_request'),
    path('pull_requests/<int:pull_request_id>/', views.pull_request_detail, name='pull_request_detail'),
    path('repositories/<int:repository_id>/add_file/', views.add_file, name='add_file'),
    # Add more paths for branch and commit management as needed
]
