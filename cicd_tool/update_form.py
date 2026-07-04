import re
def update():
    with open('D:/cicd/cicd_tool/pipeline/forms.py', 'r') as f:
        content = f.read()

    content = content.replace("    build_triggers = forms.CharField(widget=forms.Textarea(attrs={'rows': 5}), required=False)\n", "")
    content = re.sub(r'    def clean_build_triggers\(self\):.*?return data\n', '', content, flags=re.DOTALL)

    with open('D:/cicd/cicd_tool/pipeline/forms.py', 'w') as f:
        f.write(content)

if __name__ == '__main__':
    update()
