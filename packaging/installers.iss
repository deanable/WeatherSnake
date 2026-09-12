; Inno Setup script for WeatherSnake (Windows installer).
; Built by CI with ISCC /DAppVersion=x.y.z

#define AppName "WeatherSnake"
#ifndef AppVersion
#define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B7A9E4F-2C1D-4A8E-9F3B-C5D8E1F2A3B4}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=WeatherSnake Contributors
AppPublisherURL=https://github.com/deanable/WeatherSnake
AppSupportURL=https://github.com/deanable/WeatherSnake/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user fallback when the user lacks admin rights
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer
OutputBaseFilename=WeatherSnake-{#AppVersion}-windows-setup
SetupIconFile=..\assets\logo.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\WeatherSnake.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\WeatherSnake.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\WeatherSnake-CLI.exe"; DestDir: "{app}"; Flags: ignoreversion
; Compiled help: also left as a standalone double-clickable file; the exes
; carry their own embedded copy for F1. Optional for local (non-CI) builds.
Source: "..\help\html\WeatherSnake.chm"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\WeatherSnake.exe"
Name: "{group}\{#AppName} CLI"; Filename: "{app}\WeatherSnake-CLI.exe"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\WeatherSnake.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\WeatherSnake.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove settings file left behind on uninstall
Type: files; Name: "{userappdata}\{#AppName}\ui_settings.json"
