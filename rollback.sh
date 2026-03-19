#!/bin/bash
# Rollback script to revert to the last stable commit
echo "[*] Rolling back to the last stable commit..."
git reset --hard HEAD
git clean -fd
echo "[+] Rollback complete."
