[Setup]
AppName=Quick Compressor
AppVersion=2.0.0
AppPublisher=Raika
DefaultDirName={autopf}\Quick Compressor
DefaultGroupName=Quick Compressor
OutputBaseFilename=QuickCompressor_Setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Files]
; 本体と初期設定ファイル
Source: "dist\QuickCompressor.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\default_presets.json"; DestDir: "{app}"; Flags: ignoreversion
; FFmpeg関連ファイル (binフォルダ内)
Source: "dist\bin\*"; DestDir: "{app}\bin"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Quick Compressor"; Filename: "{app}\QuickCompressor.exe"
Name: "{group}\アンインストール"; Filename: "{uninstallexe}"

[Run]
; インストール完了時にバックグラウンドでレジストリ登録を実行
Filename: "{app}\QuickCompressor.exe"; Parameters: "--register"; Flags: runhidden

[UninstallRun]
; アンインストール前にバックグラウンドでレジストリ解除を実行
Filename: "{app}\QuickCompressor.exe"; Parameters: "--unregister"; Flags: runhidden
