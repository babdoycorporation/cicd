import os
import glob

directory = r"D:\cicd\cicd_tool\gitmgmt\templates\gitmgmt"

for filepath in glob.glob(os.path.join(directory, "*.html")):
    with open(filepath, 'r', encoding='utf-8') as file:
        content = file.read()
    
    if 'Code+' in content:
        # Replace Code+ Pro first, then Code+
        new_content = content.replace('Code+ Pro', 'Release Rocket').replace('Code+', 'Release Rocket')
        
        with open(filepath, 'w', encoding='utf-8') as file:
            file.write(new_content)
        print(f"Updated {os.path.basename(filepath)}")
print("Done rebranding.")
