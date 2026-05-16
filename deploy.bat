@echo off
copy /Y "E:\Dev\opencode\ContextCut-PRO\qdrant_proxy_final.py" "E:\Dev\ContextCut-PRO\qdrant_proxy_final.py"
cd /d "E:\Dev\ContextCut-PRO"
git add qdrant_proxy_final.py
git commit -m "fix: auto-open settings panel during tour when step is reached"
git push
scp qdrant_proxy_final.py steve@192.168.137.252:~/contextcut/
echo Done. SSH and restart proxy.
