; Compile with /DAppVersion=... /DBundleDir=... /DOutputDir=...
#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef BundleDir
  #error BundleDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif

[Setup]
AppId={{D15872BC-54EB-46DB-9979-6CD21AE40446}
AppName=RendaPerene
AppVersion={#AppVersion}
AppPublisher=RendaPerene
AppPublisherURL=https://github.com/R-Mascarenhas/RendaPerene
DefaultDirName={localappdata}\Programs\RendaPerene
DisableDirPage=no
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=RendaPerene-v{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\RendaPerene.exe
AppMutex={code:ApplicationMutex}
CloseApplications=no
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Excludes: "runtime-manifest.txt"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#BundleDir}\runtime-manifest.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\RendaPerene"; Filename: "{app}\RendaPerene.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\RendaPerene"; Filename: "{app}\RendaPerene.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Code]
const
  DirectoryAttribute = $10;
  ReparsePointAttribute = $400;

var
  PreviousRuntime: TArrayOfString;

function ApplicationMutex(Param: String): String;
begin
  Result := 'Global\RendaPerene.' +
    GetSHA256OfUnicodeString(Lowercase(ExpandConstant('{localappdata}')));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  LoadStringsFromFile(ExpandConstant('{app}\runtime-manifest.txt'), PreviousRuntime);
end;

procedure RemoveEmptyRuntimeDirectories(Directory: String);
var
  Entry: TFindRec;
  ChildDirectory: String;
begin
  if not FindFirst(AddBackslash(Directory) + '*', Entry) then
    Exit;
  try
    repeat
      if (Entry.Name <> '.') and (Entry.Name <> '..') and
         ((Entry.Attributes and DirectoryAttribute) <> 0) and
         ((Entry.Attributes and ReparsePointAttribute) = 0) then begin
        ChildDirectory := AddBackslash(Directory) + Entry.Name;
        RemoveEmptyRuntimeDirectories(ChildDirectory);
        // RemoveDir only succeeds for empty directories; never follow junctions.
        if RemoveDir(ChildDirectory) then
          Log('Removed empty runtime directory: ' + ChildDirectory);
      end;
    until not FindNext(Entry);
  finally
    FindClose(Entry);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  CurrentRuntime: TStringList;
  I: Integer;
  RelativePath: String;
begin
  if CurStep <> ssPostInstall then
    Exit;
  CurrentRuntime := TStringList.Create;
  try
    CurrentRuntime.LoadFromFile(ExpandConstant('{app}\runtime-manifest.txt'));
    CurrentRuntime.Sorted := True;
    for I := 0 to GetArrayLength(PreviousRuntime) - 1 do begin
      RelativePath := PreviousRuntime[I];
      // Only remove previously shipped private resources, after successful extraction.
      if (Pos('_internal\', RelativePath) = 1) and
         (Pos('..', RelativePath) = 0) and (Pos(':', RelativePath) = 0) and
         (CurrentRuntime.IndexOf(RelativePath) < 0) then
        DeleteFile(ExpandConstant('{app}\') + RelativePath);
    end;
    // Also repair empty metadata directories left by older installer versions.
    RemoveEmptyRuntimeDirectories(ExpandConstant('{app}\_internal'));
  finally
    CurrentRuntime.Free;
  end;
end;
