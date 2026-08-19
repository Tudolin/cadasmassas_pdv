@echo off
rmdir /S /Q build dist 2>nul
pyinstaller --clean --noconfirm --onefile --windowed --icon "logo_casa_das_massas.ico" --add-data "logo_casa_das_massas.ico;." --add-data "logo_casa_das_massas.png;." --add-data "pdv_database.db;." --add-binary "C:\Users\Rafael\AppData\Local\Programs\Python\Python314\python314.dll;." --hidden-import "pandas" --hidden-import "numpy" --hidden-import "win32print" --hidden-import "win32ui" "app.py"
pause