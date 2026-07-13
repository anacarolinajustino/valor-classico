@echo off
cd /d "c:\Users\v_rib\OneDrive\Documentos\Visual Studio Projects\valor-classico"

rem Carrega as variaveis do .env (o app.py nao usa python-dotenv, entao isso
rem precisa ser feito aqui antes de rodar, senao DATABASE_URL fica vazio).
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" set "%%A=%%B"
)

python app.py
pause
