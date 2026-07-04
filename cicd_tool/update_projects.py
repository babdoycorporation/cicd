import os

project_list = r"D:\cicd\cicd_tool\pipeline\templates\pipeline\project_list.html"

PROJECT_LIST_HTML = """{% extends 'pipeline/base.html' %}

{% block content %}
<style>
    .page-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 2rem;
        padding-bottom: 1rem;
        border-bottom: 1px solid var(--border-color);
    }
    .page-title {
        font-size: 1.5rem;
        font-weight: 600;
        margin: 0;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .page-title i { color: var(--accent-color); }
    .btn-primary {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.5rem 1rem;
        border-radius: 6px;
        font-weight: 500;
        text-decoration: none;
        background-color: var(--success-color);
        color: white;
        transition: var(--transition);
        border: 1px solid transparent;
    }
    .btn-primary:hover { background-color: #2ea043; }
    
    .btn-secondary {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        border-radius: 6px;
        background-color: transparent;
        border: 1px solid var(--border-color);
        color: var(--text-primary);
        transition: var(--transition);
        text-decoration: none;
    }
    .btn-secondary:hover {
        background-color: var(--card-bg);
        border-color: var(--text-secondary);
    }
    
    .btn-danger {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        border-radius: 6px;
        background-color: transparent;
        border: 1px solid rgba(248, 81, 73, 0.3);
        color: var(--danger-color);
        transition: var(--transition);
        text-decoration: none;
    }
    .btn-danger:hover {
        background-color: rgba(248, 81, 73, 0.1);
        border-color: var(--danger-color);
    }

    .project-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
        gap: 1.5rem;
    }
    .project-card {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        padding: 1.5rem;
        transition: var(--transition);
        display: flex;
        flex-direction: column;
    }
    .project-card:hover {
        border-color: var(--accent-color);
        transform: translateY(-4px);
        box-shadow: 0 10px 20px rgba(0,0,0,0.2);
    }
    .project-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 1rem;
    }
    .project-name {
        font-size: 1.15rem;
        font-weight: 600;
        color: var(--accent-color);
        text-decoration: none;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .project-name i { color: var(--text-secondary); }
    .project-name:hover { text-decoration: underline; }
    .project-actions {
        display: flex;
        gap: 0.5rem;
    }
    .project-meta {
        color: var(--text-secondary);
        font-size: 0.85rem;
        margin-top: auto;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }
    .meta-item {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .empty-state {
        text-align: center;
        padding: 4rem;
        background-color: var(--card-bg);
        border: 1px dashed var(--border-color);
        border-radius: 8px;
        color: var(--text-secondary);
    }
</style>

<div>
    <div class="page-header">
        <h1 class="page-title"><i class="ph ph-projector-screen"></i> Projects</h1>
        <a href="{% url 'project_create' %}" class="btn-primary">
            <i class="ph ph-plus"></i> New Project
        </a>
    </div>

    {% if projects %}
    <div class="project-grid">
        {% for project in projects %}
        <div class="project-card">
            <div class="project-header">
                <a href="{% url 'project_detail' project.id %}" class="project-name">
                    <i class="ph ph-book-open"></i> {{ project.name }}
                </a>
                <div class="project-actions">
                    <a href="{% url 'project_edit' project.id %}" class="btn-secondary" title="Edit">
                        <i class="ph ph-pencil-simple"></i>
                    </a>
                    <a href="{% url 'project_delete' project.id %}" class="btn-danger" title="Delete">
                        <i class="ph ph-trash"></i>
                    </a>
                </div>
            </div>
            
            <div class="project-meta">
                {% if project.repository_url %}
                <div class="meta-item">
                    <i class="ph ph-git-branch"></i> 
                    <a href="{{ project.repository_url }}" target="_blank" style="color: var(--text-secondary); text-decoration: none;">
                        {{ project.repository_url|truncatechars:40 }}
                    </a>
                </div>
                {% endif %}
                <div class="meta-item">
                    <i class="ph ph-bell"></i> Notifications: 
                    {% if project.notifications_enabled %}
                        <span style="color: var(--success-color); font-weight: 500;">Enabled</span>
                    {% else %}
                        <span>Disabled</span>
                    {% endif %}
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <div class="empty-state">
        <i class="ph ph-folder-open" style="font-size: 3rem; margin-bottom: 1rem; opacity: 0.5;"></i>
        <h3>No projects found</h3>
        <p>Get started by creating your first CI/CD project.</p>
        <a href="{% url 'project_create' %}" class="btn-primary" style="margin-top: 1rem;">
            <i class="ph ph-plus"></i> Create Project
        </a>
    </div>
    {% endif %}
</div>
{% endblock %}
"""

with open(project_list, 'w', encoding='utf-8') as f:
    f.write(PROJECT_LIST_HTML)

print("Updated Projects UI")
