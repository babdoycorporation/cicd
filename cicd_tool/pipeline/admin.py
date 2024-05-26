from django.contrib import admin
from .models import *
# Register your models here.
admin.site.register(PipelineRun)
admin.site.register(Agent)
admin.site.register(YamlFileVersion)
admin.site.register(Application)