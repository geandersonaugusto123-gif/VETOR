@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "VETOR_PYTHON=.venv\Scripts\python.exe"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "VETOR_CHECAR_PYTHON=import struct, sys; sys.exit(sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8)"

if not exist "requirements.txt" (
    echo requirements.txt ausente. Extraia todo o arquivo ZIP antes de executar.
    goto falha
)
if not exist "%VETOR_PYTHON%" (
    call :criar_ambiente
    if errorlevel 1 goto falha
)
"%VETOR_PYTHON%" -c "%VETOR_CHECAR_PYTHON%" >nul 2>&1
if errorlevel 1 (
    echo O ambiente .venv precisa de um Python 3.12 de 64 bits funcional.
    echo Renomeie a pasta .venv e execute iniciar.bat novamente para recria-la.
    goto falha
)
"%VETOR_PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo Preparando pip no ambiente local.
    "%VETOR_PYTHON%" -m ensurepip --upgrade
    if errorlevel 1 goto falha
)

call :verificar_dependencias
if errorlevel 1 (
    echo Instalando ou ajustando as dependencias indicadas em requirements.txt.
    "%VETOR_PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Nao foi possivel instalar as dependencias. Para esta etapa, use uma conexao com internet.
        goto falha
    )
    call :verificar_dependencias
    if errorlevel 1 goto falha
)
"%VETOR_PYTHON%" -m streamlit run app.py
if errorlevel 1 goto falha
popd
exit /b 0

:verificar_dependencias
rem O arquivo requirements.txt usa versoes exatas no formato pacote==versao.
set "VETOR_PENDENCIAS="
for /f "usebackq eol=# tokens=1,2 delims== " %%A in ("requirements.txt") do (
    "%VETOR_PYTHON%" -c "from importlib.metadata import version; import sys; sys.exit(version(sys.argv[1]) != sys.argv[2])" "%%A" "%%B" >nul 2>&1
    if errorlevel 1 (
        echo Dependencia ausente ou incompativel - %%A==%%B.
        set "VETOR_PENDENCIAS=1"
    )
)
if defined VETOR_PENDENCIAS exit /b 1
"%VETOR_PYTHON%" -m pip check
exit /b

:criar_ambiente
py -3.12 -c "%VETOR_CHECAR_PYTHON%" >nul 2>&1
if not errorlevel 1 (
    py -3.12 -m venv .venv
    exit /b
)
python -c "%VETOR_CHECAR_PYTHON%" >nul 2>&1
if not errorlevel 1 (
    python -m venv .venv
    exit /b
)
set "VETOR_ORANGE_PYTHON=%LOCALAPPDATA%\Programs\Orange\python.exe"
if exist "%VETOR_ORANGE_PYTHON%" (
    "%VETOR_ORANGE_PYTHON%" -c "%VETOR_CHECAR_PYTHON%" >nul 2>&1
    if not errorlevel 1 (
        "%VETOR_ORANGE_PYTHON%" -m venv .venv
        exit /b
    )
)
echo Python 3.12 de 64 bits nao encontrado. Instale-o e tente novamente.
exit /b 1

:falha
echo VETOR nao iniciou. Consulte a mensagem acima e o README.md.
popd
pause
exit /b 1
