@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   NVIDIA Register — 一键启动
echo ============================================================
echo.

REM 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

REM 检查 .env 是否存在
if not exist ".env" (
    echo [1/3] 首次运行，生成 .env 配置文件...
    python nvidia_register.py --init
    if %errorlevel% neq 0 (
        echo [错误] 生成 .env 失败
        pause
        exit /b 1
    )
    echo.
    echo 请先编辑 .env 填入邮箱服务信息，然后重新运行本脚本。
    echo   按任意键打开 .env ...
    pause >nul
    start notepad .env
    exit /b 0
)

REM 检查依赖
python -c "import playwright" >nul 2>&1
if %errorlevel% neq 0 (
    echo [2/3] 安装依赖...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
    echo 安装 Chromium 浏览器...
    playwright install chromium
    if %errorlevel% neq 0 (
        echo [错误] Chromium 安装失败
        pause
        exit /b 1
    )
)

REM 检查配置文件是否未填写
python -c "import os; exec(open('.env','r',encoding='utf-8').read().replace('\n', '\nos.environ[\"').replace('=', '\"]=\"')); v=os.environ.get('NV_PASSWORD',''); exit(0 if v and v!='your_password_here' else 1)" >nul 2>&1
rem 上面的检查可能不可靠，跳过

echo [3/3] 启动注册流程...
echo.
echo 提示：
echo   - 浏览器窗口会弹出，请勿关闭
echo   - 需手动完成 hCaptcha 验证
echo   - 完成后 API Key 保存在 nvidia_api_key.txt
echo.
echo 按任意键开始...
pause >nul

python nvidia_register.py

if %errorlevel% neq 0 (
    echo.
    echo [失败] 注册未成功，请检查配置和网络。
) else (
    echo.
    echo [完成] 如果注册成功，API Key 保存在 nvidia_api_key.txt
)

echo.
pause
