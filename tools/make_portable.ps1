# Builds the portable release: Liquid Desktop + its own Python 3.12, nothing to install.
# Собирает портативную версию: Liquid Desktop + свой Python 3.12, ставить ничего не нужно.
#
#   powershell -ExecutionPolicy Bypass -File tools\make_portable.ps1
#
# Needs Python 3.12 on the build machine (only to run pip). Result: build\LiquidDesktop-portable-win64.zip
# Нужен Python 3.12 на машине сборки (только для pip). Итог: build\LiquidDesktop-portable-win64.zip
$ErrorActionPreference = "Stop"
$PyVersion = "3.12.10"
$QtVersion = "6.12.0"
$Repo = Split-Path $PSScriptRoot -Parent
$Build = Join-Path $Repo "build"
$Out = Join-Path $Build "LiquidDesktop"
$Py = Join-Path $Out "python"
$Zip = Join-Path $Build "LiquidDesktop-portable-win64.zip"

New-Item -ItemType Directory -Force $Build | Out-Null
if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
if (Test-Path $Zip) { Remove-Item -Force $Zip }

# 1. Official embeddable Python from python.org / Официальный встраиваемый Python с python.org
$Embed = Join-Path $Build "python-$PyVersion-embed-amd64.zip"
if (-not (Test-Path $Embed)) {
    Invoke-WebRequest "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip" -OutFile $Embed -UseBasicParsing
}
Expand-Archive $Embed $Py
# libraries live in python\Lib\site-packages; sitecustomize.py adds the script's folder to the path
# (embedded Python does not do that by itself) / библиотеки — в Lib\site-packages; папку скрипта добавляет sitecustomize.py
$Pth = Get-ChildItem $Py -Filter "python*._pth" | Select-Object -First 1
Set-Content $Pth.FullName -Encoding ascii -Value @("python312.zip", ".", "Lib\site-packages", "import site")
Set-Content (Join-Path $Py "sitecustomize.py") -Encoding ascii -Value @(
    "import os, sys",
    "if sys.argv and sys.argv[0].endswith('.py'):",
    "    sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))")

# 2. Libraries: wheels for Windows x64 + Python 3.12 / Библиотеки: колёса под Windows x64 и Python 3.12
#    PySide6_Essentials is enough (QtCore/Gui/Widgets/Network) and ~200 MB smaller than full PySide6
$Reqs = @(Get-Content (Join-Path $Repo "desktop-widgets\requirements.txt")) + @(Get-Content (Join-Path $Repo "dynamic-island\requirements.txt")) |
    ForEach-Object { $_.Trim() } | Where-Object { $_ } | Sort-Object -Unique |
    ForEach-Object { if ($_ -eq "PySide6") { "PySide6_Essentials==$QtVersion" } else { $_ } }
py -3.12 -m pip install --disable-pip-version-check --no-compile --target (Join-Path $Py "Lib\site-packages") `
    --only-binary ":all:" --platform win_amd64 --python-version 3.12 --implementation cp $Reqs
if ($LASTEXITCODE) { throw "pip failed" }
# pywin32-style .pth files are not used; drop pip caches and tests to save space / убрать лишнее
Get-ChildItem (Join-Path $Py "Lib\site-packages") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem (Join-Path $Py "Lib\site-packages") -Directory -Filter "bin" | Remove-Item -Recurse -Force
# QML is not used; its debug .obj files also have paths too long for some install folders
# QML не используется, а его отладочные .obj дают слишком длинные пути при установке
Remove-Item -Recurse -Force (Join-Path $Py "Lib\site-packages\PySide6\qml") -ErrorAction SilentlyContinue

# 3. The apps — only files tracked by git (no personal configs or logs)
#    Программы — только файлы из git (без личных настроек и журналов)
Push-Location $Repo
foreach ($f in (git ls-files desktop-widgets dynamic-island LICENSE README.md)) {
    $dst = Join-Path $Out $f
    New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
    Copy-Item (Join-Path $Repo $f) $dst
}
Pop-Location
Remove-Item (Join-Path $Out "desktop-widgets\run.bat"), (Join-Path $Out "dynamic-island\run.bat"), `
    (Join-Path $Out "desktop-widgets\requirements.txt"), (Join-Path $Out "dynamic-island\requirements.txt") -ErrorAction SilentlyContinue

# 4. Launchers / Ярлыки запуска
Set-Content (Join-Path $Out "Start widgets.bat") -Encoding ascii -Value @(
    "@echo off", "start `"`" `"%~dp0python\pythonw.exe`" `"%~dp0desktop-widgets\main.py`"")
Set-Content (Join-Path $Out "Start Dynamic Island.bat") -Encoding ascii -Value @(
    "@echo off", "start `"`" `"%~dp0python\pythonw.exe`" `"%~dp0dynamic-island\main.py`"")

# 5. Build number (the installed app compares it with the release to offer updates) and icon
#    Номер сборки (установленная версия сверяет его с релизом) и значок
$BuildId = Get-Date -Format "yyyyMMdd.HHmm"
$VersionJson = '{"build": "' + $BuildId + '"}'
Set-Content (Join-Path $Out "version.json") -Encoding ascii -Value $VersionJson
Set-Content (Join-Path $Build "version.json") -Encoding ascii -Value $VersionJson
py -3.12 (Join-Path $PSScriptRoot "make_ico.py") (Join-Path $Out "liquid.ico")
if ($LASTEXITCODE) { throw "icon failed" }

Compress-Archive $Out $Zip -CompressionLevel Optimal
"{0:N0} MB  {1}" -f ((Get-Item $Zip).Length / 1MB), $Zip

# 6. Installer (Inno Setup 6: winget install JRSoftware.InnoSetup) / Установщик
$Iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($Iscc) {
    & $Iscc /Q "/DSrc=$Out" "/DBuild=$BuildId" (Join-Path $PSScriptRoot "installer.iss")
    if ($LASTEXITCODE) { throw "Inno Setup failed" }
    $Setup = Join-Path $Build "LiquidDesktop-setup.exe"
    "{0:N0} MB  {1}" -f ((Get-Item $Setup).Length / 1MB), $Setup
} else {
    "Inno Setup not found - installer skipped / установщик не собран"
}

