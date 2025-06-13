@echo off
cd /d %~dp0
call venv\Scripts\activate
streamlit run streamlit_buff_scraper.py
pause
