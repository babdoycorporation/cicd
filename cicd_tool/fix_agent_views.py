import re

with open('D:/cicd/cicd_tool/pipeline/views.py', 'r') as f:
    content = f.read()

# Replace signatures
content = re.sub(r'def agent_detail\(request, agent_id', r'def agent_detail(request, agent_hostname', content)

# Replace get_object_or_404
content = re.sub(r'get_object_or_404\(Agent, id=agent_id\)', r'get_object_or_404(Agent, hostname=agent_hostname)', content)

# Replace redirects
content = re.sub(r'agent_id=agent\.id', r'agent_hostname=agent.hostname', content)
content = re.sub(r'agent_id=agent_id', r'agent_hostname=agent_hostname', content)
content = content.replace("'agent_id': agent.id", "'agent_hostname': agent.hostname")

with open('D:/cicd/cicd_tool/pipeline/views.py', 'w') as f:
    f.write(content)
