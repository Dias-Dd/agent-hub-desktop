#ifndef Payload
  #define Payload "installer-stage"
#endif
#ifndef ReleaseOutput
  #define ReleaseOutput "installer-dist"
#endif
[Setup]
AppId={{A577AF90-CDF9-492B-9B44-43C842058693}
AppName=Agent Hub
AppVersion=0.1.0
AppPublisher=Agent Hub
DefaultDirName={localappdata}\Programs\Agent Hub
DefaultGroupName=Agent Hub
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
WizardStyle=modern
SetupIconFile=app.ico
UninstallDisplayIcon={app}\AgentHubSetup.exe
OutputDir={#ReleaseOutput}
OutputBaseFilename=AgentHub-Setup-0.1.0
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
DisableWelcomePage=no
ShowLanguageDialog=yes
UninstallDisplayName=Agent Hub

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
chinesesimp.WelcomeLabel1=安装 Agent Hub
chinesesimp.WelcomeLabel2=安装工作台和独立的首次配置引导。安装后可添加 Agent、指定经理，并连接 Hyper-V 虚拟机。两个流程均可跳过。%n%n卸载应用会保留项目、适配器和账号配置。
chinesesimp.FinishedHeadingLabel=Agent Hub 安装完成
chinesesimp.FinishedLabel=现在可以打开配置引导。以后也可从开始菜单再次打开。
english.WelcomeLabel1=Install Agent Hub
english.WelcomeLabel2=Install the workspace and a separate first-run setup program. Add Agents, choose a manager and connect a Hyper-V virtual machine. Both setup flows can be skipped.%n%nUninstalling preserves projects, adapters and account settings.
english.FinishedHeadingLabel=Agent Hub is installed
english.FinishedLabel=Open setup now, or reopen it from the Start menu later.

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopShortcut}"; Flags: unchecked

[CustomMessages]
chinesesimp.DesktopShortcut=创建桌面快捷方式
english.DesktopShortcut=Create a desktop shortcut
chinesesimp.ConfigureName=Agent Hub 配置引导
english.ConfigureName=Agent Hub Setup
chinesesimp.OpenSetup=打开 Agent Hub 配置引导
english.OpenSetup=Open Agent Hub Setup
chinesesimp.DiagnosticsName=Agent Hub 导出诊断包
english.DiagnosticsName=Agent Hub Export Diagnostics

[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installer-tools\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy

[Icons]
Name: "{group}\Agent Hub"; Filename: "{app}\AgentHubSetup.exe"; Parameters: "--language={code:UiLanguage}"; WorkingDir: "{app}"
Name: "{group}\{cm:ConfigureName}"; Filename: "{app}\AgentHubSetup.exe"; Parameters: "--configure --language={code:UiLanguage}"; WorkingDir: "{app}"
Name: "{autodesktop}\Agent Hub"; Filename: "{app}\AgentHubSetup.exe"; Parameters: "--language={code:UiLanguage}"; WorkingDir: "{app}"; Tasks: desktopicon

Name: "{group}\{cm:DiagnosticsName}"; Filename: "{app}\AgentHubDiagnostics.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\AgentHubSetup.exe"; Parameters: "--language={code:UiLanguage}"; Description: "{cm:OpenSetup}"; Flags: nowait postinstall skipifsilent

[Code]
function UiLanguage(Param: String): String;
begin
  if ActiveLanguage = 'english' then Result := 'en' else Result := 'zh-CN';
end;

function HasWebView2: Boolean;
var Version: String;
begin
  Result := (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM32, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM64, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var ExitCode: Integer;
begin
  Result := '';
  if not HasWebView2 then begin
    if ActiveLanguage = 'english' then WizardForm.StatusLabel.Caption := 'Installing Microsoft WebView2 Runtime (internet required)...'
    else WizardForm.StatusLabel.Caption := '正在安装 Microsoft WebView2 Runtime（需要联网）…';
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      Result := '无法启动 WebView2 安装程序。请从 https://developer.microsoft.com/microsoft-edge/webview2/ 安装 Runtime 后重试。'
    else if not HasWebView2 then
      Result := 'WebView2 Runtime 尚未安装成功。请检查网络，或从微软官网手动安装后重试。';
    if (Result <> '') and (ActiveLanguage = 'english') then
      Result := 'WebView2 Runtime could not be installed. Check your connection or install it from https://developer.microsoft.com/microsoft-edge/webview2/ and try again.';
  end;
end;
