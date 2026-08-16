; ---------------------------------------------------------------------------
; Inno Setup script for EPUB to MP3
;
; Builds Setup.exe from the PyInstaller one-folder output in dist\EpubToMP3.
; Compile with:  iscc build\installer.iss
; ---------------------------------------------------------------------------

#define AppName        "EPUB to MP3"
#define AppVersion     "1.0.0"
#define AppPublisher   "EPUB to MP3"
#define AppExeName     "EpubToMP3.exe"
#define SourceDir      "..\dist\EpubToMP3"

[Setup]
AppId={{7C2F3A61-9E4B-4C58-9D2E-0B1A6F5D3E92}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no
LicenseFile=..\LICENSE.txt
OutputDir=..\dist
OutputBaseFilename=EpubToMP3-{#AppVersion}-Setup
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExeName}
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
LZMANumBlockThreads=4

; Per-user install by default: no admin prompt, no SmartScreen elevation.
; Users who launch the installer as an administrator get a machine-wide install.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Deliberately no ArchitecturesAllowed / ArchitecturesInstallIn64BitMode here.
; The spelling of those values changed across Inno Setup 6.x ("x64" became
; "x64compatible"), and guessing wrong stops the build outright. Leaving them
; out costs nothing in practice: the default install is per-user, so the
; program lands in %LocalAppData%\Programs either way, and the bundled
; executable is 64-bit regardless of the installer's own mode.
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"
Name: "epubassoc"; Description: "Add ""Convert to MP3"" to the right-click menu for EPUB files"; \
    GroupDescription: "File associations:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; Optional "Convert to MP3" entry on the context menu of .epub files.
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.epub\shell\EpubToMP3"; \
    ValueType: string; ValueName: ""; ValueData: "Convert to MP3"; \
    Flags: uninsdeletekey; Tasks: epubassoc
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.epub\shell\EpubToMP3"; \
    ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExeName},0"; \
    Tasks: epubassoc
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.epub\shell\EpubToMP3\command"; \
    ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; \
    Flags: uninsdeletekey; Tasks: epubassoc

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Start {#AppName} now"; \
    Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var
  FreeMB: Cardinal;
  TotalMB: Cardinal;
begin
  Result := True;
  // The program needs room for itself plus a 330 MB voice model download.
  // Checked against LocalAppData because that is where the model lands, and
  // because it always resolves - unlike {autopf} before the mode is chosen.
  if GetSpaceOnDisk(ExpandConstant('{localappdata}'), True, FreeMB, TotalMB) then
  begin
    if FreeMB < 900 then
    begin
      if MsgBox('There is only ' + IntToStr(FreeMB) + ' MB free on this drive.'
                + #13#13
                + 'EPUB to MP3 needs about 250 MB, and downloads a further '
                + '330 MB of voice data the first time it runs.'
                + #13#13
                + 'Continue anyway?', mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ModelDir: String;
begin
  // The voice model is downloaded after install and lives outside the program
  // folder, so it has to be removed here rather than through UninstallDelete,
  // and only if the user actually wants it gone.
  if CurUninstallStep = usPostUninstall then
  begin
    ModelDir := ExpandConstant('{localappdata}\EpubToMP3');
    if DirExists(ModelDir + '\models') then
    begin
      if MsgBox('Also delete the downloaded voice model (about 330 MB)?'
                + #13#13
                + 'Choose No to keep it, so a future reinstall does not have '
                + 'to download it again.', mbConfirmation, MB_YESNO) = IDYES then
        DelTree(ModelDir, True, True, True);
    end;
  end;
end;
