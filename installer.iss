; Clip Ça installer (Inno Setup 6). Built by build.ps1.
#define AppName "Clip Ça"
#define AppVersion "1.0.2"
#define AppExe "ClipCa.exe"

[Setup]
AppId={{3F6C1D2E-9A47-4B8C-B5E0-7D2A61C4F8B3}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={localappdata}\Programs\ClipCa
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=ClipCa-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile=LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startup"; Description: "Démarrer avec Windows (recommandé, pour ne jamais rater un moment)"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "dist\ClipCa\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"" --background"; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#AppExe} /F"; Flags: runhidden; RunOnceId: "StopApp"

[Code]
// Clip Ça used to be called "Jarvis Clipper": remove that version first so the two never run side by side.
procedure CurStepChanged(CurStep: TSetupStep);
var
  Uninstaller: String;
  Code: Integer;
begin
  if (CurStep = ssInstall) and RegQueryStringValue(HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\{8E0B2B8C-5C51-4B7E-9C1B-1A7A3E2C9F10}_is1',
      'UninstallString', Uninstaller) then
    Exec(RemoveQuotes(Uninstaller), '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE,
         ewWaitUntilTerminated, Code);
end;
