@echo off
cd /d "D:\Desktop\Project\job-alert-bot"
python daily_health_check.py --verbose >> health_check_history.log 2>&1
echo. >> health_check_history.log
