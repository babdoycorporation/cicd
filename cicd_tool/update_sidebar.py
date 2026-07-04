import re

def update():
    with open('D:/cicd/cicd_tool/pipeline/templates/pipeline/base.html', 'r') as f:
        content = f.read()

    sidebar_html = '''        <div class="sidebar-menu">
            {% if project %}
                <a href="{% url 'project_list' %}" style="margin-bottom: 1rem; border-bottom: 1px solid var(--border-color); border-radius: 0;">
                    <i class="ph ph-arrow-left icon"></i>
                    <span class="text">Back to Hub</span>
                </a>
                <a href="{% url 'project_detail' project.name %}">
                    <i class="ph ph-presentation-chart icon"></i>
                    <span class="text">Overview</span>
                </a>
                <a href="#">
                    <i class="ph ph-code icon"></i>
                    <span class="text">Code (Repos)</span>
                </a>
                <a href="{% url 'pipeline_list' project.name %}">
                    <i class="ph ph-rocket-launch icon"></i>
                    <span class="text">Pipelines</span>
                </a>
                <a href="#">
                    <i class="ph ph-cloud-check icon"></i>
                    <span class="text">Environments</span>
                </a>
                <a href="{% url 'configure_project' project.name %}">
                    <i class="ph ph-gear-six icon"></i>
                    <span class="text">Project Settings</span>
                </a>
            {% else %}
                <a href="{% url 'project_list' %}">
                    <i class="ph ph-tree-structure icon"></i>
                    <span class="text">Projects</span>
                </a>
                <a href="{% url 'organization_list' %}">
                    <i class="ph ph-buildings icon"></i>
                    <span class="text">Organizations</span>
                </a>
                <a href="{% url 'agent_list' %}">
                    <i class="ph ph-users icon"></i>
                    <span class="text">Agents</span>
                </a>
                <a href="{% url 'global_credential_list' %}">
                    <i class="ph ph-key icon"></i>
                    <span class="text">Credentials</span>
                </a>
                <a href="{% url 'global_settings' %}">
                    <i class="ph ph-gear icon"></i>
                    <span class="text">Global Settings</span>
                </a>
            {% endif %}
        </div>'''

    content = re.sub(r'<div class="sidebar-menu">.*?</div>\s*<div class="sidebar-footer">', sidebar_html + '\n        <div class="sidebar-footer">', content, flags=re.DOTALL)

    with open('D:/cicd/cicd_tool/pipeline/templates/pipeline/base.html', 'w') as f:
        f.write(content)

if __name__ == '__main__':
    update()
