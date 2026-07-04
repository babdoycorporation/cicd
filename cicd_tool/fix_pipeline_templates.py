import os
import re

template_dir = 'D:/cicd/cicd_tool/pipeline/templates/pipeline'

for filename in os.listdir(template_dir):
    if not filename.endswith('.html'):
        continue
    filepath = os.path.join(template_dir, filename)
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Replace project.id -> project.name
    content = content.replace('project.id', 'project.name')
    # Replace pipeline.id -> pipeline.name
    content = content.replace('pipeline.id', 'pipeline.name')
    # Replace application.id -> application.name
    content = content.replace('application.id', 'application.name')

    # Note: Some links might look like `project_id=project.id`. The regex replace might be safer?
    # No, python's .replace handles everything identically. 
    # But what about `<int:project_id>` inside templates if any? Not applicable.

    with open(filepath, 'w') as f:
        f.write(content)

print("Templates updated.")
