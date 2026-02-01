[Setup]
AppId={{0F44B5C1-8458-4B1E-9E6E-98D3B14F84A1}
AppName=OK-ZhuXian World
AppVersion=1.0
AppPublisher=OK-ZhuXian World
DefaultDirName={localappdata}\Programs\OK-ZhuXian World
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
SetupIconFile=toolbox_logo.ico
OutputDir=dist\installer
OutputBaseFilename=OK-ZhuXian-World-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\OK-ZhuXian-World\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\OK-ZhuXian World"; Filename: "{app}\OK-ZhuXian-World.exe"
Name: "{userdesktop}\OK-ZhuXian World"; Filename: "{app}\OK-ZhuXian-World.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OK-ZhuXian-World.exe"; Description: "{cm:LaunchProgram,OK-ZhuXian World}"; Flags: nowait postinstall skipifsilent
