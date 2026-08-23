@echo off
setlocal enabledelayedexpansion

echo =========================================================
echo  JWE3 - Copy US Loc OVL to All Language Folders
echo =========================================================

set "LOC_ROOT=%~dp0"

:: If run from mod root instead of Localised folder, append Localised
if not exist "%LOC_ROOT%English\UnitedStates" (
    if exist "%LOC_ROOT%Localised\English\UnitedStates" (
        set "LOC_ROOT=%LOC_ROOT%Localised\"
    )
)

set "US_DIR=%LOC_ROOT%English\UnitedStates"

if not exist "%US_DIR%" (
    echo [ERROR] Could not locate US Localization directory at:
    echo        "%US_DIR%"
    echo Please make sure this script is in the mod root or inside the Localised folder.
    echo.
    pause
    exit /b 1
)

:: Target Language Directories (Relative to LOC_ROOT)
set "TARGET_COUNT=13"
set "TARGET[1]=English\UnitedKingdom"
set "TARGET[2]=French\France"
set "TARGET[3]=German\Germany"
set "TARGET[4]=Italian\Italy"
set "TARGET[5]=Japanese\Japan"
set "TARGET[6]=Korean\Korea"
set "TARGET[7]=Polish\Poland"
set "TARGET[8]=Portuguese\Brazil"
set "TARGET[9]=Russian\Russia"
set "TARGET[10]=SimpleChinese\China"
set "TARGET[11]=Spanish\Mexico"
set "TARGET[12]=Spanish\Spain"
set "TARGET[13]=TraditionalChinese\Taiwan"

echo Copying US Loc .ovl files from:
echo   "%US_DIR%"
echo.

set "FOUND_OVL=0"
for %%F in ("%US_DIR%\*.ovl") do (
    set "FOUND_OVL=1"
)

if "%FOUND_OVL%"=="0" (
    echo [WARNING] No .ovl files found in "%US_DIR%".
    echo Please build your Loc .ovl in the US folder first!
    echo.
    pause
    exit /b 0
)

for /L %%i in (1,1,%TARGET_COUNT%) do (
    set "REL=!TARGET[%%i]!"
    set "DEST=%LOC_ROOT%!REL!"
    
    if not exist "!DEST!" mkdir "!DEST!"
    
    echo   [+] Copying .ovl to: !REL!...
    
    for %%F in ("%US_DIR%\*.ovl") do (
        copy /Y "%%F" "!DEST!\" >nul
    )
)

echo.
echo =========================================================
echo  SUCCESS! US Loc .ovl copied to all 13 target language folders.
echo =========================================================
echo.
pause
