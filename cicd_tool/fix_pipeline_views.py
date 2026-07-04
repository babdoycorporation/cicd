import re

with open('D:/cicd/cicd_tool/pipeline/views.py', 'r') as f:
    content = f.read()

# Replace signatures
content = re.sub(r'def (\w+)\(request, project_id', r'def \1(request, project_name', content)
content = re.sub(r'def (\w+)\(request, pipeline_id', r'def \1(request, pipeline_name', content)
content = re.sub(r'def (\w+)\(request, application_id', r'def \1(request, application_name', content)

# Some views might have multiple args, e.g., project_name, pipeline_id
content = re.sub(r'(def \w+\(request,.*) pipeline_id', r'\1 pipeline_name', content)

# Replace get_object_or_404
content = re.sub(r'get_object_or_404\(Project, (id|pk)=project_id\)', r'get_object_or_404(Project, name=project_name)', content)
content = re.sub(r'get_object_or_404\(Pipeline, (id|pk)=pipeline_id', r'get_object_or_404(Pipeline, name=pipeline_name', content)
content = re.sub(r'get_object_or_404\(Application, (id|pk)=application_id\)', r'get_object_or_404(Application, name=application_name)', content)

# Replace keyword args for redirects or other function calls
content = re.sub(r'project_id=project\.id', r'project_name=project.name', content)
content = re.sub(r'pipeline_id=pipeline\.id', r'pipeline_name=pipeline.name', content)
content = re.sub(r'application_id=application\.id', r'application_name=application.name', content)
content = re.sub(r'project_id=project_id', r'project_name=project_name', content)
content = re.sub(r'pipeline_id=pipeline_id', r'pipeline_name=pipeline_name', content)

# Also handle kwargs={'project_id': project.id}
content = content.replace("'project_id': project.id", "'project_name': project.name")
content = content.replace("'pipeline_id': pipeline.id", "'pipeline_name': pipeline.name")
content = content.replace("'application_id': application.id", "'application_name': application.name")

with open('D:/cicd/cicd_tool/pipeline/views.py', 'w') as f:
    f.write(content)
