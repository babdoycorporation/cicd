import os

app_detail = r"D:\cicd\cicd_tool\pipeline\templates\pipeline\application_detail.html"
app_list = r"D:\cicd\cicd_tool\pipeline\templates\pipeline\application_list.html"
cred_detail = r"D:\cicd\cicd_tool\pipeline\templates\pipeline\global_credential_detail.html"
cred_form = r"D:\cicd\cicd_tool\pipeline\templates\pipeline\global_credential_form.html"
cred_list = r"D:\cicd\cicd_tool\pipeline\templates\pipeline\global_credential_list.html"

APP_DETAIL_HTML = """{% extends 'pipeline/base.html' %}

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
    .detail-card {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        padding: 2rem;
        margin-bottom: 2rem;
    }
    .detail-item {
        margin-bottom: 1rem;
        font-size: 1rem;
        display: flex;
        align-items: center;
    }
    .detail-item strong {
        color: var(--text-secondary);
        display: inline-block;
        width: 150px;
    }
    .pipeline-list {
        list-style: none;
        padding: 0;
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 1rem;
    }
    .pipeline-card {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        padding: 1.25rem;
        display: flex;
        align-items: center;
        gap: 1rem;
        transition: var(--transition);
        text-decoration: none;
        color: var(--text-primary);
    }
    .pipeline-card:hover {
        border-color: var(--accent-color);
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    .pipeline-card i {
        color: var(--accent-color);
        font-size: 1.5rem;
    }
    .btn-secondary {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.5rem 1rem;
        border-radius: 6px;
        font-weight: 500;
        text-decoration: none;
        background-color: transparent;
        border: 1px solid var(--border-color);
        color: var(--text-primary);
        transition: var(--transition);
        cursor: pointer;
    }
    .btn-secondary:hover {
        background-color: var(--card-bg);
        border-color: var(--text-secondary);
    }
</style>

<div>
    <div class="page-header">
        <h1 class="page-title">
            <i class="ph ph-cube"></i> {{ application.name }}
        </h1>
        <a href="{% url 'application_list' %}" class="btn-secondary">
            <i class="ph ph-arrow-left"></i> Back to Applications
        </a>
    </div>

    <div class="detail-card">
        <div class="detail-item">
            <strong>Project:</strong> 
            <i class="ph ph-projector-screen" style="color: var(--text-secondary); margin-right: 0.5rem;"></i> {{ application.project }}
        </div>
    </div>

    <h2 style="font-size: 1.25rem; margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem;">
        <i class="ph ph-git-merge"></i> Attached Pipelines
    </h2>
    
    {% if pipelines %}
    <ul class="pipeline-list">
        {% for pipeline in pipelines %}
        <li>
            <a href="{% url 'pipeline_detail' pipeline.id %}" class="pipeline-card">
                <i class="ph ph-git-merge"></i>
                <span style="font-weight: 500;">{{ pipeline.name }}</span>
            </a>
        </li>
        {% endfor %}
    </ul>
    {% else %}
    <div style="padding: 2rem; text-align: center; color: var(--text-secondary); background: var(--card-bg); border: 1px dashed var(--border-color); border-radius: 8px;">
        <i class="ph ph-git-merge" style="font-size: 2rem; margin-bottom: 0.5rem; opacity: 0.5;"></i>
        <p style="margin: 0;">No pipelines attached to this application.</p>
    </div>
    {% endif %}
</div>
{% endblock %}
"""

APP_LIST_HTML = """{% extends 'pipeline/base.html' %}

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
    .app-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
        gap: 1.5rem;
    }
    .app-card {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        padding: 2rem 1.5rem;
        transition: var(--transition);
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        text-decoration: none;
    }
    .app-card:hover {
        border-color: var(--accent-color);
        transform: translateY(-4px);
        box-shadow: 0 10px 20px rgba(0,0,0,0.2);
    }
    .app-icon {
        width: 56px;
        height: 56px;
        border-radius: 12px;
        background-color: rgba(47, 129, 247, 0.1);
        color: var(--accent-color);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.75rem;
        margin-bottom: 1rem;
    }
    .app-name {
        font-size: 1.1rem;
        font-weight: 600;
        color: var(--text-primary);
        margin-bottom: 0.5rem;
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
        <h1 class="page-title"><i class="ph ph-cube"></i> Applications</h1>
    </div>

    {% if applications %}
    <div class="app-grid">
        {% for application in applications %}
        <a href="{% url 'application_detail' application.id %}" class="app-card">
            <div class="app-icon"><i class="ph ph-layers"></i></div>
            <div class="app-name">{{ application.name }}</div>
            <div style="font-size: 0.85rem; color: var(--text-secondary);">
                <i class="ph ph-projector-screen"></i> {{ application.project.name }}
            </div>
        </a>
        {% endfor %}
    </div>
    {% else %}
    <div class="empty-state">
        <i class="ph ph-package" style="font-size: 3rem; opacity: 0.5; margin-bottom: 1rem;"></i>
        <h3>No applications found</h3>
        <p>There are no applications registered in this project.</p>
    </div>
    {% endif %}
</div>
{% endblock %}
"""

CRED_LIST_HTML = """{% extends 'pipeline/base.html' %}

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
    .cred-list {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        padding: 0;
        margin: 0;
        list-style: none;
        overflow: hidden;
    }
    .cred-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1.25rem 1.5rem;
        border-bottom: 1px solid var(--border-color);
        transition: var(--transition);
    }
    .cred-item:last-child { border-bottom: none; }
    .cred-item:hover { background-color: rgba(255, 255, 255, 0.02); }
    .cred-name {
        font-size: 1rem;
        font-weight: 600;
        color: var(--text-primary);
        text-decoration: none;
        display: flex;
        align-items: center;
        gap: 0.75rem;
    }
    .cred-name i {
        color: var(--text-secondary);
        font-size: 1.25rem;
    }
    .cred-name:hover {
        text-decoration: underline;
        color: var(--accent-color);
    }
    .badge {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        background-color: rgba(47, 129, 247, 0.1);
        color: var(--accent-color);
        border: 1px solid rgba(47, 129, 247, 0.2);
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
        <h1 class="page-title"><i class="ph ph-key"></i> Global Credentials</h1>
        <a href="{% url 'global_credential_create' %}" class="btn-primary">
            <i class="ph ph-plus"></i> New Credential
        </a>
    </div>

    {% if credentials %}
    <ul class="cred-list">
        {% for credential in credentials %}
        <li class="cred-item">
            <a href="{% url 'global_credential_detail' credential.pk %}" class="cred-name">
                <i class="ph ph-lock-key"></i>
                {{ credential.service_name }}
            </a>
            <span class="badge">
                <i class="ph ph-shield-check"></i> Secured
            </span>
        </li>
        {% endfor %}
    </ul>
    {% else %}
    <div class="empty-state">
        <i class="ph ph-key" style="font-size: 3rem; opacity: 0.5; margin-bottom: 1rem;"></i>
        <h3>No global credentials found</h3>
        <p>Add credentials to allow your pipelines to interact with external services securely.</p>
    </div>
    {% endif %}
</div>
{% endblock %}
"""

CRED_DETAIL_HTML = """{% extends 'pipeline/base.html' %}

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
    .btn {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.5rem 1rem;
        border-radius: 6px;
        font-weight: 500;
        text-decoration: none;
        transition: var(--transition);
        cursor: pointer;
        border: 1px solid transparent;
        font-size: 0.9rem;
    }
    .btn-secondary {
        background-color: transparent;
        border-color: var(--border-color);
        color: var(--text-primary);
    }
    .btn-secondary:hover { background-color: var(--card-bg); border-color: var(--text-secondary); }
    .btn-primary { background-color: var(--success-color); color: white; }
    .btn-primary:hover { background-color: #2ea043; }
    .btn-danger { background-color: transparent; border-color: rgba(248, 81, 73, 0.3); color: var(--danger-color); }
    .btn-danger:hover { background-color: rgba(248, 81, 73, 0.1); border-color: var(--danger-color); }
    
    .detail-card {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        padding: 2rem;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    .detail-row {
        display: flex;
        align-items: center;
        padding: 1rem 0;
        border-bottom: 1px solid var(--border-color);
    }
    .detail-row:last-child {
        border-bottom: none;
    }
    .detail-label {
        width: 150px;
        color: var(--text-secondary);
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .detail-value {
        flex-grow: 1;
        color: var(--text-primary);
        font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, monospace;
    }
    .password-mask {
        color: var(--success-color);
        background-color: rgba(63, 185, 80, 0.1);
        padding: 0.25rem 0.5rem;
        border-radius: 4px;
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
    }
</style>

<div>
    <div class="page-header">
        <h1 class="page-title"><i class="ph ph-key"></i> Credential Details</h1>
        <div style="display: flex; gap: 0.5rem;">
            <a href="{% url 'global_credential_list' %}" class="btn btn-secondary">
                <i class="ph ph-arrow-left"></i> Back
            </a>
            <a href="{% url 'global_credential_update' credential.pk %}" class="btn btn-primary">
                <i class="ph ph-pencil-simple"></i> Edit
            </a>
            <a href="{% url 'global_credential_delete' credential.pk %}" class="btn btn-danger">
                <i class="ph ph-trash"></i> Delete
            </a>
        </div>
    </div>

    <div class="detail-card">
        <div class="detail-row">
            <div class="detail-label"><i class="ph ph-tag"></i> Service Name</div>
            <div class="detail-value">{{ credential.service_name }}</div>
        </div>
        <div class="detail-row">
            <div class="detail-label"><i class="ph ph-user"></i> Username</div>
            <div class="detail-value">{{ credential.username }}</div>
        </div>
        <div class="detail-row">
            <div class="detail-label"><i class="ph ph-lock-key"></i> Password</div>
            <div class="detail-value">
                <span class="password-mask"><i class="ph ph-shield-check"></i> ••••••••••••</span>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

CRED_FORM_HTML = """{% extends 'pipeline/base.html' %}

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
    
    .form-card {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        padding: 2rem;
        max-width: 600px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    
    .form-group {
        margin-bottom: 1.5rem;
    }
    
    .form-group label {
        display: block;
        margin-bottom: 0.5rem;
        color: var(--text-secondary);
        font-weight: 500;
    }
    
    .form-group input, .form-group select, .form-group textarea {
        width: 100%;
        padding: 0.75rem 1rem;
        background-color: var(--darker-bg);
        border: 1px solid var(--border-color);
        border-radius: 6px;
        color: var(--text-primary);
        font-family: 'Inter', sans-serif;
        font-size: 0.95rem;
        transition: var(--transition);
        box-sizing: border-box;
    }
    
    .form-group input:focus, .form-group select:focus, .form-group textarea:focus {
        outline: none;
        border-color: var(--accent-color);
        box-shadow: 0 0 0 3px rgba(47, 129, 247, 0.2);
    }
    
    .btn-primary {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.75rem 1.5rem;
        border-radius: 6px;
        font-weight: 500;
        background-color: var(--success-color);
        color: white;
        border: none;
        cursor: pointer;
        transition: var(--transition);
        font-size: 1rem;
    }
    .btn-primary:hover { background-color: #2ea043; }
</style>

<div>
    <div class="page-header">
        <h1 class="page-title">
            <i class="ph ph-key"></i> 
            {% if form.instance.pk %}Update{% else %}Create{% endif %} Global Credential
        </h1>
        <a href="{% url 'global_credential_list' %}" style="color: var(--text-secondary); text-decoration: none; display: flex; align-items: center; gap: 0.5rem;">
            <i class="ph ph-arrow-left"></i> Back to list
        </a>
    </div>

    <div class="form-card">
        <form method="post">
            {% csrf_token %}
            <div class="form-group">
                {{ form.service_name.label_tag }}
                {{ form.service_name }}
            </div>
            <div class="form-group">
                {{ form.username.label_tag }}
                {{ form.username }}
            </div>
            <div class="form-group">
                {{ form.password.label_tag }}
                {{ form.password }}
            </div>
            <div style="margin-top: 2rem;">
                <button type="submit" class="btn-primary">
                    <i class="ph ph-floppy-disk"></i> Save Credential
                </button>
            </div>
        </form>
    </div>
</div>
{% endblock %}
"""

files_map = {
    app_detail: APP_DETAIL_HTML,
    app_list: APP_LIST_HTML,
    cred_detail: CRED_DETAIL_HTML,
    cred_form: CRED_FORM_HTML,
    cred_list: CRED_LIST_HTML
}

for path, content in files_map.items():
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

print("Updated Applications and Credentials UI")
