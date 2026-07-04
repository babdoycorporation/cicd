import os

base_html = r"D:\cicd\cicd_tool\pipeline\templates\pipeline\base.html"
dashboard_html = r"D:\cicd\cicd_tool\pipeline\templates\pipeline\dashboard.html"

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
    '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">': '<script src="https://unpkg.com/@phosphor-icons/web"></script>\n    <style>.fa-spin { animation: spin 2s linear infinite; } @keyframes spin { 100% { transform: rotate(360deg); } }</style>'
}

# Update base.html CSS
with open(base_html, 'r', encoding='utf-8') as f:
    content = f.read()

for old, new in icon_replacements.items():
    content = content.replace(old, new)

# Reduce sidebar width
content = content.replace("--sidebar-width: 250px;", "--sidebar-width: 210px;")
content = content.replace("--sidebar-collapsed-width: 80px;", "--sidebar-collapsed-width: 64px;")

# Reduce font size and add letter spacing
content = content.replace("font-size: 14px;", "font-size: 13px;\n            letter-spacing: 0.2px;")

# Adjust padding and font-size for sidebar links
content = content.replace("padding: 0.75rem 1rem;", "padding: 0.6rem 1rem;")
content = content.replace("font-size: 1.25rem;", "font-size: 1.15rem;") # sidebar brand

with open(base_html, 'w', encoding='utf-8') as f:
    f.write(content)


# Update dashboard.html CSS
with open(dashboard_html, 'r', encoding='utf-8') as f:
    content = f.read()

for old, new in icon_replacements.items():
    content = content.replace(old, new)

# Reduce metric grid layout
content = content.replace("minmax(240px, 1fr)", "minmax(200px, 1fr)")
content = content.replace("gap: 1.5rem;", "gap: 1rem;")

# Reduce metric card padding
content = content.replace("padding: 1.5rem;", "padding: 1.2rem;")

# Reduce metric icon size
content = content.replace("width: 48px;", "width: 40px;")
content = content.replace("height: 48px;", "height: 40px;")
content = content.replace("margin-right: 1.5rem;", "margin-right: 1rem;")

# Reduce metric values
content = content.replace("font-size: 1.75rem;", "font-size: 1.4rem;")
content = content.replace("font-size: 0.85rem;", "font-size: 0.75rem;")

# Reduce status badge size
content = content.replace("padding: 0.25rem 0.75rem;", "padding: 0.2rem 0.6rem;")
content = content.replace("font-size: 0.8rem;", "font-size: 0.75rem;")

with open(dashboard_html, 'w', encoding='utf-8') as f:
    f.write(content)

print("UI tweaks applied successfully.")
