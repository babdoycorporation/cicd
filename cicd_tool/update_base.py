import os

def update():
    with open('D:/cicd/cicd_tool/pipeline/templates/pipeline/base.html', 'r') as f:
        content = f.read()

    css_injection = '''        .sidebar {
            height: 100vh;
            width: var(--sidebar-width);
            position: fixed;
            top: 0;
            left: 0;
            background-color: var(--darker-bg);
            border-right: 1px solid var(--border-color);
            padding-top: 1rem;
            overflow-x: hidden;
            transition: width 0.3s;
            z-index: 1000;
            display: flex;
            flex-direction: column;
        }

        .sidebar-footer {
            margin-top: auto;
            padding: 1rem;
            border-top: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .user-avatar {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background: linear-gradient(135deg, var(--accent-color), #b892ff);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            color: white;
            flex-shrink: 0;
            text-transform: uppercase;
        }

        .user-info {
            display: flex;
            flex-direction: column;
            overflow: hidden;
            flex-grow: 1;
        }

        .user-name {
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--text-primary);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .user-role {
            font-size: 0.75rem;
            color: var(--text-secondary);
        }

        .logout-btn {
            color: var(--text-secondary);
            background: none;
            border: none;
            cursor: pointer;
            padding: 0.25rem;
            display: flex;
            transition: var(--transition);
        }

        .logout-btn:hover {
            color: var(--danger-color);
        }

        .sidebar.collapsed .sidebar-footer {
            flex-direction: column;
            padding: 1rem 0;
        }
        
        .sidebar.collapsed .user-info, .sidebar.collapsed .logout-btn {
            display: none;
        }'''

    content = content.replace('''        .sidebar {
            height: 100vh;
            width: var(--sidebar-width);
            position: fixed;
            top: 0;
            left: 0;
            background-color: var(--darker-bg);
            border-right: 1px solid var(--border-color);
            padding-top: 1rem;
            overflow-x: hidden;
            transition: width 0.3s;
            z-index: 1000;
        }''', css_injection)

    settings_link = '''            <a href="{% url 'global_settings' %}">
                <i class="ph ph-gear icon"></i>
                <span class="text">Global Settings</span>
            </a>
        </div>'''
    
    content = content.replace('        </div>\n    </div>\n\n    <!-- Main Wrapper -->', settings_link + '\n    </div>\n\n    <!-- Main Wrapper -->')

    footer_html = '''        <div class="sidebar-footer">
            <div class="user-avatar">
                {{ request.user.username|make_list|first|default:"U" }}
            </div>
            <div class="user-info">
                <span class="user-name">{{ request.user.username|default:"Guest" }}</span>
                <span class="user-role">{% if request.user.is_superuser %}Admin{% else %}Developer{% endif %}</span>
            </div>
            <a href="{% url 'logout' %}" class="logout-btn" title="Logout">
                <i class="ph ph-sign-out" style="font-size: 1.2rem;"></i>
            </a>
        </div>
    </div>

    <!-- Main Wrapper -->'''

    content = content.replace('    </div>\n\n    <!-- Main Wrapper -->', footer_html)

    with open('D:/cicd/cicd_tool/pipeline/templates/pipeline/base.html', 'w') as f:
        f.write(content)
    
    print("Base.html updated successfully!")

if __name__ == '__main__':
    update()
