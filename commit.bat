@echo off
REM Step 2: Git add, commit, and push from Windows repo
cd /d "E:\Dev\ContextCut-PRO"
git add qdrant_proxy_final.py
git commit -m "fix: move _instance_id before _license_state to fix NameError at startup"
git push
echo Done.
