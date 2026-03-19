import os, re, json

SCREEN_DIR = "/home/vusinhthanh/train ai/ironcore/tui/screens"
files = [f for f in os.listdir(SCREEN_DIR) if f.endswith(".py") and f != "language.py"]

subs = [
    (r'(Label\()("[^"]*")([,\)])', r'\1i18n.t(\2)\3'),
    (r'(Label\()("""[\s\S]*?""")([,\)])', r'\1i18n.t(\2)\3'),
    (r'(Button\()("[^"]*")([,\)])', r'\1i18n.t(\2)\3'),
    (r'(Selection\()("[^"]*")([,\)])', r'\1i18n.t(\2)\3'),
    (r'(RadioButton\()("[^"]*")([,\)])', r'\1i18n.t(\2)\3'),
    (r'(placeholder=)("[^"]*")([,\)])', r'\1i18n.t(\2)\3'),
    (r'(notify\()("[^"]*")([,\)])', r'\1i18n.t(\2)\3'),
]

extracted_strings = set()

def extract_repl(m):
    string_val = m.group(2)
    # remove quotes
    val = string_val.strip('"')
    if val:
        extracted_strings.add(val)
    return f"{m.group(1)}i18n.t({string_val}){m.group(3)}"

for f in files:
    path = os.path.join(SCREEN_DIR, f)
    with open(path, "r") as file:
        content = file.read()
    
    # avoid double wrapping if script runs twice
    if "i18n.t(" not in content:
        if "from ironcore.tui.i18n import i18n" not in content:
            # Insert at the very beginning
            content = "from ironcore.tui.i18n import i18n\n" + content
            
        for pattern, _ in subs:
            content = re.sub(pattern, extract_repl, content)
            
        with open(path, "w") as file:
            file.write(content)

# Dump to a temp json to see what needs translation
with open("/tmp/extracted_i18n.json", "w") as f:
    json.dump({k: k for k in extracted_strings}, f, indent=2)

print(f"Injected i18n wrapper into {len(files)} files. Extracted {len(extracted_strings)} strings.")
