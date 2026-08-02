from django.contrib import admin
from .models import (
    Agent, Application, Command, Credential, Environment,
    GlobalSettings, Heartbeat, Pipeline, PipelineRun, PipelineStep,
    Project, ProjectMember, ProjectPipeline, ProjectOrchestrationStep, ProjectPipelineRun, Stage, Step, Tag, YamlFileVersion,
)

admin.site.register(ProjectMember)


@admin.register(PipelineRun)
class PipelineRunAdmin(admin.ModelAdmin):
    list_display = ('run_id', 'pipeline', 'status', 'agent', 'started_at', 'finished_at')
    list_filter = ('status',)
    search_fields = ('pipeline__name',)
    readonly_fields = ('run_id', 'started_at')


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ('hostname', 'ip_address', 'operating_system', 'live', 'last_heartbeat')
    list_filter = ('live', 'scope_level')


@admin.register(Pipeline)
class PipelineAdmin(admin.ModelAdmin):
    list_display = ('name', 'application', 'yaml_path', 'monitored_branch')
    search_fields = ('name',)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'repository_url', 'notifications_enabled')
    search_fields = ('name',)


@admin.register(Credential)
class CredentialAdmin(admin.ModelAdmin):
    list_display = ('service_name', 'scope_level', 'username', 'project')
    list_filter = ('scope_level',)


admin.site.register(YamlFileVersion)
admin.site.register(Application)
admin.site.register(PipelineStep)
admin.site.register(Stage)
admin.site.register(Step)
admin.site.register(Environment)
admin.site.register(Tag)
admin.site.register(GlobalSettings)
admin.site.register(ProjectPipeline)
admin.site.register(ProjectOrchestrationStep)
admin.site.register(ProjectPipelineRun)
admin.site.register(Command)
admin.site.register(Heartbeat)
