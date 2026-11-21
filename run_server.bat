@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   智检 - 启动服务
echo   地址: http://127.0.0.1:8688
echo ============================================
echo.
echo [1/2] 检查 8688 端口是否被占用...
netstat -ano | findstr ":8688" | findstr "LISTENING" >nul
if not errorlevel 1 (
  echo     8688 端口已被占用。请先停止正在运行的服务。
  pause
  exit /b 1
)
echo [2/2] 启动服务（改代码会自动重载）...
echo.
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8688 --reload
pause
