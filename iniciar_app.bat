@echo off
cd /d "c:\Users\v_rib\OneDrive\Documentos\Visual Studio Projects\valor-classico"

rem Carrega as variaveis do .env. O Flask tambem carrega sozinho via
rem python-dotenv (instalado em 2026-07-14), mas manter o carregamento aqui
rem garante que o app sobe mesmo se a dependencia faltar.
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" set "%%A=%%B"
)

python app.py

if errorlevel 1 (
    echo.
    echo O app encerrou com erro - veja a mensagem acima.
    pause
)
