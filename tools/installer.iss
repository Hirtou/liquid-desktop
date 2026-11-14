; Установщик Liquid Desktop (Inno Setup 6). Собирается из tools\make_portable.ps1, руками не нужно.
; Ставится в папку пользователя без прав администратора; обновление поверх сохраняет config.json.
#ifndef Src
  #define Src "..\build\LiquidDesktop"
#endif
#ifndef Build
  #define Build "0"
#endif

[Setup]
AppId={{8F3B2C61-4E0A-4B7D-9A55-6C1E2D7F4A10}
AppName=Liquid Desktop
AppVersion=0.3.4 alpha ({#Build})
AppVerName=Liquid Desktop 0.3.4 alpha
AppPublisher=Hirtou
AppPublisherURL=https://github.com/Hirtou/liquid-desktop
AppSupportURL=https://github.com/Hirtou/liquid-desktop/issues
AppUpdatesURL=https://github.com/Hirtou/liquid-desktop/releases
DefaultDirName={localappdata}\Programs\LiquidDesktop
DefaultGroupName=Liquid Desktop
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\build
OutputBaseFilename=LiquidDesktop-setup
SetupIconFile={#Src}\liquid.ico
UninstallDisplayIcon={app}\liquid.ico
UninstallDisplayName=Liquid Desktop
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
ShowLanguageDialog=no
CloseApplications=yes
RestartApplications=no
LicenseFile={#Src}\LICENSE

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
en.Widgets=Desktop widgets
en.Island=Dynamic Island
en.DesktopIcons=Desktop shortcuts
en.Startup=Start with Windows:
en.StartWidgets=Desktop widgets
en.StartIsland=Dynamic Island

[Tasks]
; запуск вместе с Windows — галочки уже стоят; запись та же, что ставит сама программа (её переключатель её видит)
Name: "startwidgets"; Description: "{cm:StartWidgets}"; GroupDescription: "{cm:Startup}"
Name: "startisland"; Description: "{cm:StartIsland}"; GroupDescription: "{cm:Startup}"
Name: "desktopicons"; Description: "{cm:DesktopIcons}"; Flags: unchecked

[InstallDelete]
; старый код без пары: убрать удалённые в новой версии файлы, но не настройки
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\desktop-widgets\widgets"
Type: files; Name: "{app}\desktop-widgets\*.py"
Type: files; Name: "{app}\dynamic-island\*.py"

[Files]
Source: "{#Src}\*"; DestDir: "{app}"; Excludes: "*.bat,config.json,*.log,__pycache__"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Liquid Desktop\{cm:Widgets}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\desktop-widgets\main.py"""; WorkingDir: "{app}\desktop-widgets"; IconFilename: "{app}\liquid.ico"
Name: "{userprograms}\Liquid Desktop\{cm:Island}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\dynamic-island\main.py"""; WorkingDir: "{app}\dynamic-island"; IconFilename: "{app}\liquid.ico"
Name: "{userdesktop}\{cm:Widgets}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\desktop-widgets\main.py"""; WorkingDir: "{app}\desktop-widgets"; IconFilename: "{app}\liquid.ico"; Tasks: desktopicons
Name: "{userdesktop}\{cm:Island}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\dynamic-island\main.py"""; WorkingDir: "{app}\dynamic-island"; IconFilename: "{app}\liquid.ico"; Tasks: desktopicons

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "DesktopWidgets"; ValueData: """{app}\python\pythonw.exe"" ""{app}\desktop-widgets\main.py"" --tray"; Tasks: startwidgets
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "DynamicIsland"; ValueData: """{app}\python\pythonw.exe"" ""{app}\dynamic-island\main.py"""; Tasks: startisland

[Run]
; сразу после установки (и после обновления) — без галочек и вопросов: виджеты с открытым каталогом и остров
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\desktop-widgets\main.py"""; WorkingDir: "{app}\desktop-widgets"; Flags: nowait
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\dynamic-island\main.py"""; WorkingDir: "{app}\dynamic-island"; Flags: nowait

[UninstallRun]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\desktop-widgets\claude_connect.py"" --disconnect"; Flags: runhidden waituntilterminated; RunOnceId: "ClaudeHooks"
Filename: "powershell.exe"; Parameters: "-NoProfile -Command ""Get-Process pythonw,python -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -like '{app}\*' } | Stop-Process -Force"""; Flags: runhidden; RunOnceId: "StopApps"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\desktop-widgets\__pycache__"
Type: filesandordirs; Name: "{app}\desktop-widgets\widgets\__pycache__"
Type: filesandordirs; Name: "{app}\dynamic-island\__pycache__"
Type: files; Name: "{app}\desktop-widgets\*.log"
Type: files; Name: "{app}\dynamic-island\*.log"

[Code]
// перед установкой поверх закрыть запущенные из этой папки виджеты и остров (обновление из трея)
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Exec('powershell.exe', '-NoProfile -Command "Get-Process pythonw,python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like ''' +
       ExpandConstant('{app}') + '\*'' } | Stop-Process -Force"', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(500);
  Result := '';
end;

// автозапуск, если его включали в программах, убрать — но только свой (запись ведёт в папку установки):
// у копии, запущенной из исходников, имена записей те же
procedure DropRun(Name: String);
var
  Value: String;
begin
  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', Name, Value) and
     (Pos(Lowercase(ExpandConstant('{app}\')), Lowercase(Value)) > 0) then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', Name);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    DropRun('DesktopWidgets');
    DropRun('DynamicIsland');
  end;
end;
