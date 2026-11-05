@echo off
cd /d "%~dp0"
if not exist data mkdir data
python news.py --quiet >> data\news_log.txt 2>&1
