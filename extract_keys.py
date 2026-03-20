import re
from pathlib import Path

txt_path = Path("/tmp/tui_strings.txt")
content = txt_path.read_text()

# Regex to catch i18n.t("string") or i18n.t('string')
matches = re.findall(r'i18n\.t\((["\'])(.*?)\1', content)

unique_strings = set()
for match in matches:
    unique_strings.add(match[1])

print("Found", len(unique_strings), "unique strings.")
with open("/tmp/unique_keys.json", "w") as f:
    import json
    json.dump(sorted(list(unique_strings)), f, indent=2)
print("Saved to /tmp/unique_keys.json")
