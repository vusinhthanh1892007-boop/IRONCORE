---
name: ironcore-github-local
description: Search GitHub repos, issues, PRs, and read code files using the GitHub CLI (gh). Requires gh auth login.
metadata: {"openclaw": {"emoji": "🐙", "requires": {"bins": ["gh", "python3"]}}}
---

# IronCore GitHub Search

Search GitHub repositories, read code files, list issues/PRs, and get repo stats using the `gh` CLI.

## When to use
- User asks to find GitHub repos on a topic
- User wants to read a specific file from a GitHub repo
- User wants to list open issues or PRs in a repo
- User wants repo stats (stars, forks, license)
- User asks to search code on GitHub

## Prerequisites
```bash
gh --version || echo "Install: curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && echo 'deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main' | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null && sudo apt update && sudo apt install gh"
gh auth status || gh auth login
```

## Search repos by keyword
```bash
QUERY="SEARCH_TERMS_HERE"
gh search repos "$QUERY" --limit 10 --json fullName,description,stargazersCount,language,updatedAt | python3 -c "
import json, sys
results = json.load(sys.stdin)
for r in results:
    print(f'{r[\"fullName\"]:<45} ⭐{r[\"stargazersCount\"]:>6}  [{r.get(\"language\",\"?\")}]  {r.get(\"description\",\"\")[:60]}')
"
```

## Get repo info
```bash
REPO="owner/repo"
gh repo view "$REPO" --json name,description,stargazersCount,forksCount,license,updatedAt,topics | python3 -c "
import json, sys
r = json.load(sys.stdin)
print(f'Repo   : {r[\"name\"]}')
print(f'Desc   : {r.get(\"description\",\"\")}')
print(f'Stars  : {r.get(\"stargazersCount\",0):,}')
print(f'Forks  : {r.get(\"forksCount\",0):,}')
print(f'License: {r.get(\"license\",{}).get(\"name\",\"N/A\")}')
print(f'Topics : {r.get(\"topics\",[])}')
"
```

## List open issues
```bash
REPO="owner/repo"
gh issue list --repo "$REPO" --state open --limit 15 --json number,title,createdAt,labels | python3 -c "
import json, sys
issues = json.load(sys.stdin)
for i in issues:
    labels = ','.join(l['name'] for l in i.get('labels',[]))
    print(f'#{i[\"number\"]:<5} {i[\"title\"][:65]:<65} [{labels}]')
"
```

## Read a file from a repo
```bash
REPO="owner/repo"
FILE_PATH="path/to/file.py"
gh api repos/$REPO/contents/$FILE_PATH | python3 -c "
import json, base64, sys
d = json.load(sys.stdin)
print(base64.b64decode(d['content']).decode())
"
```

## Steps
1. Determine what the user wants: search, view repo, list issues, or read a file
2. Extract the relevant parameters (query, repo name, file path)
3. Run the appropriate command above
4. Parse and present the results cleanly

## Error handling
If `gh auth status` fails, ask user to run `gh auth login` first. GitHub CLI must be authenticated to access private repos.
