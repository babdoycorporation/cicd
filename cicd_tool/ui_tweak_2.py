import os

other_files = [
    r"D:\cicd\cicd_tool\pipeline\templates\pipeline\global_pipeline_list.html",
    r"D:\cicd\cicd_tool\pipeline\templates\pipeline\pipeline_list.html",
    r"D:\cicd\cicd_tool\pipeline\templates\pipeline\pipeline_detail.html"
]

icon_replacements = {
    "fas fa-rocket": "ph ph-rocket",
    "fas fa-tachometer-alt": "ph ph-gauge",
    "fas fa-project-diagram": "ph ph-tree-structure",
    "fas fa-users": "ph ph-users",
    "fas fa-key": "ph ph-key",
    "fas fa-cube": "ph ph-cube",
    "fas fa-stream": "ph ph-list-dashes",
    "fas fa-play-circle": "ph ph-play-circle",
    "fas fa-server": "ph ph-server",
    "fas fa-check-circle": "ph ph-check-circle",
    "fas fa-times-circle": "ph ph-x-circle",
    "fas fa-code-branch": "ph ph-git-branch",
    "fas fa-tasks": "ph ph-list-checks",
    "fas fa-check": "ph ph-check",
    "fas fa-times": "ph ph-x",
    "fas fa-spinner fa-spin": "ph ph-spinner-gap fa-spin",
    "fas fa-clock": "ph ph-clock",
    "fas fa-history": "ph ph-clock-counter-clockwise",
    "fas fa-bars": "ph ph-list",
    "fas fa-file-code": "ph ph-file-code",
    "fas fa-plus": "ph ph-plus",
    "fas fa-route": "ph ph-git-merge",
    "fas fa-edit": "ph ph-pencil-simple",
    "fas fa-trash": "ph ph-trash",
    "fas fa-play": "ph ph-play",
    "fas fa-info-circle": "ph ph-info",
    "fas fa-triangle-exclamation": "ph ph-warning",
}

for file_path in other_files:
    if not os.path.exists(file_path):
        continue
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    for old, new in icon_replacements.items():
        content = content.replace(old, new)
        
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

print("Icons tweaked in other files.")
