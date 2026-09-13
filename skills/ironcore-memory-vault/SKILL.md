---
name: ironcore-memory-vault
description: Save, recall, search, and manage persistent memory entries locally. Store facts, preferences, notes, and context that survive across sessions.
metadata: {"openclaw": {"emoji": "🧠", "requires": {"bins": ["python3"]}}}
---

# IronCore Memory Vault

Save and recall information that persists across sessions. Store facts, user preferences, notes, and important context in a local JSON vault.

## When to use
- User says "remember that...", "save this...", "note that..."
- User asks "what did I tell you about X?", "do you remember my..."
- User wants to recall a previously stored fact or preference
- User wants to list all saved memories
- User wants to delete a specific memory

## Memory file location
```
~/.ironcore/memory_vault.json
```

## SAVE a memory
```python
python3 << 'EOF'
import json, pathlib, datetime, hashlib

VAULT = pathlib.Path.home() / ".ironcore" / "memory_vault.json"
VAULT.parent.mkdir(parents=True, exist_ok=True)

# REPLACE these values:
KEY = "MEMORY_KEY"       # short identifier, e.g. "user_name", "preferred_lang", "project_goal"
VALUE = "MEMORY_VALUE"   # what to remember
TAGS = ["personal"]      # optional tags: ["work","code","preference","fact", etc.]

vault = json.loads(VAULT.read_text()) if VAULT.exists() else {}
entry_id = hashlib.sha1(KEY.encode()).hexdigest()[:8]
vault[entry_id] = {
    "key": KEY,
    "value": VALUE,
    "tags": TAGS,
    "saved_at": datetime.datetime.now().isoformat(),
    "updated_at": datetime.datetime.now().isoformat(),
}
VAULT.write_text(json.dumps(vault, indent=2, ensure_ascii=False))
print(f"✅ Saved: [{KEY}] = {VALUE}")
EOF
```

## RECALL a memory by key or keyword
```python
python3 << 'EOF'
import json, pathlib

VAULT = pathlib.Path.home() / ".ironcore" / "memory_vault.json"
QUERY = "SEARCH_TERM"   # REPLACE with keyword to search

if not VAULT.exists():
    print("Memory vault is empty — nothing saved yet.")
else:
    vault = json.loads(VAULT.read_text())
    matches = [v for v in vault.values() if QUERY.lower() in v['key'].lower() or QUERY.lower() in str(v['value']).lower()]
    if matches:
        for m in matches:
            print(f"[{m['key']}]  {m['value']}  (saved: {m['saved_at'][:10]})")
    else:
        print(f"No memory found for '{QUERY}'")
EOF
```

## LIST all memories
```python
python3 << 'EOF'
import json, pathlib

VAULT = pathlib.Path.home() / ".ironcore" / "memory_vault.json"
if not VAULT.exists():
    print("Memory vault is empty.")
else:
    vault = json.loads(VAULT.read_text())
    print(f"=== Memory Vault ({len(vault)} entries) ===")
    for entry in sorted(vault.values(), key=lambda x: x.get('saved_at','')):
        tags = ','.join(entry.get('tags',[]))
        print(f"  [{entry['key']}] {str(entry['value'])[:80]}  tags:{tags}  date:{entry['saved_at'][:10]}")
EOF
```

## DELETE a memory
```python
python3 << 'EOF'
import json, pathlib, hashlib

VAULT = pathlib.Path.home() / ".ironcore" / "memory_vault.json"
KEY_TO_DELETE = "MEMORY_KEY"   # REPLACE

if VAULT.exists():
    vault = json.loads(VAULT.read_text())
    entry_id = hashlib.sha1(KEY_TO_DELETE.encode()).hexdigest()[:8]
    if entry_id in vault:
        del vault[entry_id]
        VAULT.write_text(json.dumps(vault, indent=2, ensure_ascii=False))
        print(f"🗑️ Deleted: {KEY_TO_DELETE}")
    else:
        print(f"Not found: {KEY_TO_DELETE}")
EOF
```

## Steps
1. Identify the intent: save, recall, list, or delete
2. Extract the key and value from the user's message
3. Run the appropriate command above
4. Confirm the action to the user
5. For recall: if found, present the value clearly; if not found, say so and suggest listing all memories

## Notes
- Memory is stored in `~/.ironcore/memory_vault.json` — local, private, never sent online
- Keys should be descriptive: `user_name`, `work_hours`, `github_username`, `preferred_ai_model`
- Values can be strings, lists, or dicts (stored as JSON)
