@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=python"
where %PY% >nul 2>nul
if errorlevel 1 (
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)

echo.
echo   VertexViewer  ·  模型浏览器
echo   ---------------------------------------------
echo   正在启动，请稍候（首次启动要读 pak 索引，约 5 秒）
echo.

"%PY%" -c "import PySide6, numpy, PIL, Crypto" 2>nul
if errorlevel 1 (
    echo   [!] 缺少依赖，正在安装 ...
    "%PY%" -m pip install --disable-pip-version-check -r requirements.txt ^
        -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
    if errorlevel 1 (
        echo   [!] 依赖安装失败，请检查网络或手动执行：
        echo       python -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

"%PY%" __main__.py %*
if errorlevel 1 (
    echo.
    echo   [!] 程序异常退出，错误信息见上方。
    pause
)
endlocal
