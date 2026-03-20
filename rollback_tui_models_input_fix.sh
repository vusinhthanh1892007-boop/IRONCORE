#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

echo "[rollback] Reverting files touched by TUI provider-key fix..."

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git restore --worktree --staged --source=HEAD -- ironcore/tui/screens/models.py || true
  git restore --worktree --staged --source=HEAD -- tests/test_tui_models_input_logic.py || true
fi

rm -f tests/test_tui_models_input_logic.py
rm -f tests/__pycache__/test_tui_models_input_logic*.pyc

echo "[rollback] Done. Current status (relevant files):"
git status --short -- ironcore/tui/screens/models.py tests/test_tui_models_input_logic.py || true
