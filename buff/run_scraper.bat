@echo off
title BUFF CSGO 饰品数据抓取器
cd /d %~dp0
echo 正在运行爬虫，请在弹出浏览器中登录 BUFF...
python buff_scraper.py
pause
