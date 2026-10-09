#ifndef AppDir
  #error AppDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef AppVersion
  #define AppVersion "0.6.0"
#endif

[Setup]
AppId=Denghuo.PixelDungeon.Companion
AppName=灯火 · 地牢助手
AppVersion={#AppVersion}
AppPublisher=灯火
DefaultDirName={localappdata}\Programs\Denghuo
DefaultGroupName=灯火
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=灯火安装-{#AppVersion}
SetupIconFile=..\data\lamp.ico
UninstallDisplayIcon={app}\灯火.exe
LicenseFile=..\LICENSE.txt
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=no
RestartApplications=no
UninstallDisplayName=灯火 · 地牢助手

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\灯火"; Filename: "{app}\灯火.exe"; WorkingDir: "{app}"
Name: "{group}\灯火完整面板（键盘与读屏）"; Filename: "{app}\灯火.exe"; Parameters: "--web"; WorkingDir: "{app}"
Name: "{autodesktop}\灯火"; Filename: "{app}\灯火.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\灯火.exe"; Description: "启动灯火"; Flags: nowait postinstall skipifsilent

[Messages]
FinishedLabel=灯火已安装完成。关闭悬浮窗后仍会自动备份，可从系统托盘重新打开。设置和备份存放在用户数据目录，卸载程序会保留。
