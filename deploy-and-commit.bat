@echo off
REM All-in-one: copy to Windows repo + git commit + scp to server
copy "E:\Dev\opencode\ContextCut-PRO\qdrant_proxy_final.py" "E:\Dev\ContextCut-PRO\qdrant_proxy_final.py"
cd /d "E:\Dev\ContextCut-PRO"
git add qdrant_proxy_final.py
git commit -m "fix: move _instance_id before _license_state to fix NameError at startup"
git push
scp "E:\Dev\ContextCut-PRO\qdrant_proxy_final.py" steve@192.168.137.252:~/contextcut/
echo Done. SSH to server and restart proxy.
