---
name: ironcore-dlp-scan
description: Scan any text for sensitive data — API keys, passwords, credit cards, phone numbers, emails, and PII. Uses IronCore DLP engine patterns.
metadata: {"openclaw": {"emoji": "🔐", "requires": {"bins": ["python3"]}}}
---

# IronCore DLP Scanner

Scan text for sensitive information patterns. Detects leaks before they happen — useful before sharing files, pasting to public, or sending messages.

## When to use
- User asks to check if a file or text contains sensitive data
- User wants to verify a document before sharing it publicly
- User wants to audit code/config files for hardcoded secrets
- User asks "does this contain any API keys / passwords / personal info?"

## How to run

Save the scanner script and run it:

```python
python3 << 'EOF'
import re, sys

TEXT = """PASTE_TEXT_HERE"""

# DLP patterns from IronCore engine
PATTERNS = {
    "API Key (generic)":    r'(?i)(api[_-]?key|api[_-]?secret|access[_-]?token)\s*[=:]\s*["\']?([A-Za-z0-9_\-]{20,})["\']?',
    "OpenAI Key":           r'sk-[A-Za-z0-9]{20,}',
    "Anthropic Key":        r'sk-ant-[A-Za-z0-9\-]{20,}',
    "AWS Access Key":       r'AKIA[0-9A-Z]{16}',
    "AWS Secret Key":       r'(?i)aws.{0,20}secret.{0,20}["\']([A-Za-z0-9/+=]{40})["\']',
    "GitHub Token":         r'ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82}',
    "Private Key (PEM)":    r'-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----',
    "Password (hardcoded)": r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']([^"\']{6,})["\']',
    "Credit Card":          r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12})\b',
    "Email Address":        r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b',
    "Phone (VN)":           r'\b(0[3-9]\d{8}|\+84[3-9]\d{8})\b',
    "IP Address (private)": r'\b(10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2[0-9]|3[01])\.\d+\.\d+)\b',
    "JWT Token":            r'eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+',
    "Connection String":    r'(?i)(mongodb|postgres|mysql|redis):\/\/[^\s"\'<>]+',
    "Slack Token":          r'xoxb-[0-9]+-[A-Za-z0-9]+|xoxp-[0-9]+-[A-Za-z0-9]+',
}

found = []
for label, pattern in PATTERNS.items():
    for m in re.finditer(pattern, TEXT):
        snippet = m.group(0)[:60].replace('\n', ' ')
        found.append((label, snippet, m.start()))

if found:
    print(f"⚠️  SENSITIVE DATA DETECTED — {len(found)} findings:\n")
    for label, snippet, pos in sorted(found, key=lambda x: x[2]):
        masked = snippet[:8] + "****" + snippet[-4:] if len(snippet) > 14 else "****"
        print(f"  [{label}]  pos:{pos}  →  {masked}")
else:
    print("✅ No sensitive data patterns detected.")
EOF
```

## Steps
1. Ask the user to provide the text they want to scan (or a file path)
2. If it's a file, read it first: `content = open('FILEPATH').read()`
3. Replace `PASTE_TEXT_HERE` with the actual content
4. Run the scanner and report findings
5. IMPORTANT: Never log or repeat the actual sensitive values — only show masked versions

## For scanning a file
```bash
python3 -c "
import re, pathlib
# Replace FILEPATH with actual path
text = pathlib.Path('FILEPATH').read_text(errors='replace')
print(f'Scanning {len(text)} chars...')
" 
```

## Security note
This scanner runs entirely locally. No data is sent to any external service.
