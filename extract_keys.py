import ast
from pathlib import Path

unique_strings = set()
tui_dir = Path("/home/vusinhthanh/train ai/ironcore/tui/screens")

class I18nVisitor(ast.NodeVisitor):
    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "t":
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "i18n":
                if node.args and isinstance(node.args[0], ast.Constant):
                    unique_strings.add(node.args[0].value)
        self.generic_visit(node)

# Scan files
for py_file in tui_dir.glob("*.py"):
    content = py_file.read_text()
    try:
        tree = ast.parse(content)
        v = I18nVisitor()
        v.visit(tree)
    except Exception as e:
        print(f"Error parsing {py_file}: {e}")

# Include i18n.py itself if it has any keys? No need.
print("Found", len(unique_strings), "unique strings with AST.")
with open("/tmp/unique_keys.json", "w") as f:
    import json
    json.dump(sorted(list(unique_strings)), f, indent=2)
print("Saved to /tmp/unique_keys.json")
