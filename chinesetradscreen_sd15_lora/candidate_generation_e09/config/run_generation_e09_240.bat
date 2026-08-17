@echo off
chcp 65001 >nul
cd /d D:\AI\experiments\chinesetradscreen_sd15_lora_v1\candidate_generation_e09
"D:\app_down\anaconda\envs\sd15_lora\python.exe" "D:\AI\experiments\chinesetradscreen_sd15_lora_v1\candidate_generation_e09\config\run_generation_e09_240.py"
exit /b %ERRORLEVEL%
