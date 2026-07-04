import os
import re

template_dir = 'D:/cicd/cicd_tool/pipeline/templates/pipeline'

for filename in os.listdir(template_dir):
    if not filename.endswith('.html'):
        continue
    filepath = os.path.join(template_dir, filename)
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Replace agent.id -> agent.hostname
    content = content.replace('agent.id', 'agent.hostname')

    with open(filepath, 'w') as f:
        f.write(content)

print("Templates updated.")
