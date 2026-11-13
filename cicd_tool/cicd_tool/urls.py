from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect
from django.views.generic import TemplateView
from gitmgmt import views as git_views

urlpatterns = [
    path('sw.js', TemplateView.as_view(template_name='sw.js', content_type='application/javascript'), name='service_worker'),
    path('admin/', admin.site.urls),
    path('logout/', git_views.user_logout, name='root_logout'),
    path('dashboard/', lambda r: redirect('dashboard'), name='root_dashboard'),
    path('ci/', include('pipeline.urls')),
    path('', include('gitmgmt.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
