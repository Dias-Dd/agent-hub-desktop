param([string]$Root='C:\ProgramData\AgentHubDesktop')
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes,System.Drawing,System.Windows.Forms
Add-Type @'
using System.Runtime.InteropServices;
public static class HubScreenDpi {
 [DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags);
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern System.IntPtr SetThreadDpiAwarenessContext(System.IntPtr value);
 [DllImport("user32.dll")] public static extern int GetSystemMetrics(int index);
 [DllImport("kernel32.dll")] public static extern uint WTSGetActiveConsoleSessionId();
 [DllImport("wtsapi32.dll",CharSet=CharSet.Unicode)] public static extern bool WTSQuerySessionInformation(System.IntPtr server,int session,int info,out System.IntPtr buffer,out int bytes);
 [DllImport("wtsapi32.dll")] public static extern void WTSFreeMemory(System.IntPtr buffer);
}
public static class HubControlMessage {
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] public static extern bool MoveFileEx(string source,string target,uint flags);
 [DllImport("user32.dll",CharSet=CharSet.Unicode,EntryPoint="SendMessageTimeoutW",SetLastError=true)]
 public static extern System.IntPtr Text(System.IntPtr hwnd,uint msg,System.UIntPtr wparam,string text,uint flags,uint timeout,out System.UIntPtr result);
 [DllImport("user32.dll",EntryPoint="SendMessageTimeoutW",SetLastError=true)]
 public static extern System.IntPtr Click(System.IntPtr hwnd,uint msg,System.UIntPtr wparam,System.IntPtr lparam,uint flags,uint timeout,out System.UIntPtr result);
}
'@
[HubScreenDpi]::SetProcessDPIAware() | Out-Null
New-Item -ItemType Directory -Path "$Root\requests","$Root\results" -Force | Out-Null
function Write-Result($path,$value) {
    $temp=$path+'.'+[guid]::NewGuid().ToString('N')+'.tmp'
    try {
      [IO.File]::WriteAllText($temp,($value|ConvertTo-Json -Depth 12 -Compress),[Text.UTF8Encoding]::new($false))
      for($attempt=0;$attempt -lt 20;$attempt++){
        if([HubControlMessage]::MoveFileEx($temp,$path,9)){return}
        $code=[Runtime.InteropServices.Marshal]::GetLastWin32Error()
        Start-Sleep -Milliseconds 25
      }
      throw [ComponentModel.Win32Exception]::new($code)
    } finally {if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue}}
}
function Describe($element) {
    $c=$element.Current;$bounds=$c.BoundingRectangle
    @{element_id=($element.GetRuntimeId()-join ',');name=$c.Name;automation_id=$c.AutomationId;type=$c.ControlType.ProgrammaticName;
      class_name=$c.ClassName;patterns=@($element.GetSupportedPatterns() | ForEach-Object ProgrammaticName);
      enabled=$c.IsEnabled;offscreen=$c.IsOffscreen;window_handle=$c.NativeWindowHandle;process_id=$c.ProcessId;
      bounds=@{x=$bounds.X;y=$bounds.Y;width=$bounds.Width;height=$bounds.Height}}
}
$mutex=[Threading.Mutex]::new($false,'Local\AgentHubDesktopWorker')
try {if(-not $mutex.WaitOne(5000)){$mutex.Dispose();exit}}catch [Threading.AbandonedMutexException] {}
# User settings apply in the interactive account, including its first logon.
$preferenceFile=Join-Path $Root 'unattended.json'
if(Test-Path -LiteralPath $preferenceFile){
 try{
  $preference=Get-Content -LiteralPath $preferenceFile -Raw -Encoding UTF8|ConvertFrom-Json
  $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  $beforePath=Join-Path $Root ('unattended-user-'+$sid+'.json')
  $settings=@(
   @{path='HKCU:\Control Panel\Desktop';name='ScreenSaveActive';value='0'},
   @{path='HKCU:\Control Panel\Desktop';name='ScreenSaverIsSecure';value='0'},
   @{path='HKCU:\Software\Policies\Microsoft\Windows\Control Panel\Desktop';name='ScreenSaveActive';value='0'},
   @{path='HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Winlogon';name='EnableGoodbye';value=0;kind='DWord'}
  )
  if($preference.enabled -and $preference.sid -eq $sid){
   if(-not(Test-Path -LiteralPath $beforePath)){
    $before=@(foreach($row in $settings){$key=Get-Item -LiteralPath $row.path -ErrorAction SilentlyContinue;$exists=$key -and $key.GetValueNames() -contains $row.name;@{path=$row.path;name=$row.name;exists=[bool]$exists;value=$(if($exists){$key.GetValue($row.name)}else{$null});kind=$(if($exists){$key.GetValueKind($row.name).ToString()}else{'String'})}})
    Write-Result $beforePath @{registry=$before}
   }
   foreach($row in $settings){New-Item -Path $row.path -Force|Out-Null;New-ItemProperty -LiteralPath $row.path -Name $row.name -Value $row.value -PropertyType $(if($row.kind){$row.kind}else{'String'}) -Force|Out-Null}
   [HubScreenDpi]::SetThreadExecutionState([uint32]2147483651)|Out-Null
  }elseif(-not $preference.enabled -and (Test-Path -LiteralPath $beforePath)){
   $before=Get-Content -LiteralPath $beforePath -Raw -Encoding UTF8|ConvertFrom-Json
   foreach($row in $before.registry){if($row.exists){New-ItemProperty -LiteralPath $row.path -Name $row.name -Value $row.value -PropertyType $row.kind -Force|Out-Null}else{Remove-ItemProperty -LiteralPath $row.path -Name $row.name -ErrorAction SilentlyContinue}}
   Remove-Item -LiteralPath $beforePath -Force
  }
 }catch{Write-Result (Join-Path $Root 'unattended-user-error.json') @{error=$_.Exception.Message}}
}
function Read-SessionInfo([int]$id,[int]$info) {
 $buffer=[IntPtr]::Zero;$bytes=0
 if(-not [HubScreenDpi]::WTSQuerySessionInformation([IntPtr]::Zero,$id,$info,[ref]$buffer,[ref]$bytes)){throw 'Cannot inspect desktop session'}
 try{if($info -eq 8){return [Runtime.InteropServices.Marshal]::ReadInt32($buffer)};return [Runtime.InteropServices.Marshal]::PtrToStringUni($buffer)}finally{[HubScreenDpi]::WTSFreeMemory($buffer)}
}
function Restore-ConsoleDesktop {
 # Recover only this account's disconnected session, never take over active RDP or another user.
 try{
  $preference=Get-Content -LiteralPath $preferenceFile -Raw -Encoding UTF8|ConvertFrom-Json
  if(-not $preference.enabled -or $preference.sid -ne [Security.Principal.WindowsIdentity]::GetCurrent().User.Value){return}
  $own=[Diagnostics.Process]::GetCurrentProcess().SessionId
  $console=[HubScreenDpi]::WTSGetActiveConsoleSessionId()
  if($own -eq $console -or (Read-SessionInfo $own 8) -ne 4){return}
  if($console -ne [uint32]::MaxValue -and (Read-SessionInfo ([int]$console) 5)){return}
  & "$env:SystemRoot\System32\tscon.exe" $own /dest:console 2>&1|Out-Null
  if($LASTEXITCODE -ne 0){throw "Console reconnect failed: $LASTEXITCODE"}
 }catch{Write-Result (Join-Path $Root 'console-recovery.json') @{error=$_.Exception.Message;updated=([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())}}
}
function Screen-Space {
 [HubScreenDpi]::SetThreadDpiAwarenessContext([IntPtr](-4))|Out-Null
 @{width=[HubScreenDpi]::GetSystemMetrics(78);height=[HubScreenDpi]::GetSystemMetrics(79);origin_x=[HubScreenDpi]::GetSystemMetrics(76);origin_y=[HubScreenDpi]::GetSystemMetrics(77);units='physical_pixels';session=[Diagnostics.Process]::GetCurrentProcess().SessionId;console_session=[HubScreenDpi]::WTSGetActiveConsoleSessionId()}
}
$nextConsoleCheck=[DateTime]::MinValue
$leaseOwner='';$leaseUntil=0
$nextCleanup=[DateTime]::UtcNow
Remove-Item -LiteralPath "$Root\error.json" -Force -ErrorAction SilentlyContinue
try {
 while($true) {
    if([DateTime]::UtcNow -ge $nextConsoleCheck){$nextConsoleCheck=[DateTime]::UtcNow.AddSeconds(10);Restore-ConsoleDesktop}
    [HubScreenDpi]::SetThreadDpiAwarenessContext([IntPtr](-4))|Out-Null
    Write-Result "$Root\status.json" @{updated=([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0);session=[Diagnostics.Process]::GetCurrentProcess().SessionId;backend='Windows UI Automation';pid=$PID}
    foreach($file in Get-ChildItem -LiteralPath "$Root\requests" -Filter '*.json' | Sort-Object LastWriteTimeUtc) {
      $out=Join-Path "$Root\results" $file.Name
      if(Test-Path -LiteralPath $out){
        $prior=Get-Content -LiteralPath $out -Raw -Encoding UTF8|ConvertFrom-Json
        if($prior.state -eq 'running'){Write-Result $out @{state='failed';error='Desktop worker restarted during operation; not replayed.'}}
        Remove-Item -LiteralPath $file.FullName -Force;continue
      }
      $request=$null
      try {
        $request=Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if($request.expires -lt [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()){throw 'Desktop request expired; not replayed.'}
        Write-Result $out @{state='running'}
        $now=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        if($request.action -in @('ui_invoke','ui_set_value','desktop_acquire','desktop_launch')) {
          if($leaseUntil -gt $now -and $leaseOwner -ne $request.owner){throw "Desktop is in use by $leaseOwner; retry after lease expiry or ask that agent to release it."}
          $leaseOwner=$request.owner;$leaseUntil=$now+120
        }
        if($request.action -in @('desktop_status','desktop_acquire')) {
          $result=@{screen=(Screen-Space);backend='Windows UI Automation';console_session=[HubScreenDpi]::WTSGetActiveConsoleSessionId();lease_owner=$leaseOwner;lease_until=$leaseUntil;session=[Diagnostics.Process]::GetCurrentProcess().SessionId}
        } elseif($request.action -eq 'desktop_release') {
          if($leaseOwner -and $leaseOwner -ne $request.owner -and $leaseUntil -gt $now){throw 'Only the desktop owner can release its active lease.'}
          $leaseOwner='';$leaseUntil=0;$result=@{released=$true}
        } elseif($request.action -eq 'desktop_launch') {
          function Get-LaunchFingerprint([string]$Path) {
            $stream=[IO.File]::OpenRead($Path);$hash=[Security.Cryptography.SHA256]::Create()
            try {return ([BitConverter]::ToString($hash.ComputeHash($stream))).Replace('-','').ToLowerInvariant()} finally {$stream.Dispose();$hash.Dispose()}
          }
          $program=[string]$request.executable
          if(-not(Test-Path -LiteralPath $program -PathType Leaf)){throw ('Executable not found: '+$program)}
          $program=(Resolve-Path -LiteralPath $program).ProviderPath
          $fingerprint=(Get-LaunchFingerprint $program)
          $version=[Diagnostics.FileVersionInfo]::GetVersionInfo($program).FileVersion
          $existing=@(Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($program)) -ErrorAction SilentlyContinue | ForEach-Object {try {if($_.Path -eq $program){@{pid=$_.Id;started=$_.StartTime.ToUniversalTime().ToString('o');path=$_.Path}}}catch{}})
          $launchedAt=[DateTime]::UtcNow.ToString('o')
          $stdout=Join-Path "$Root\results" ($file.BaseName+'.stdout.txt')
          $stderr=Join-Path "$Root\results" ($file.BaseName+'.stderr.txt')
          $args=@{FilePath=$program;WorkingDirectory=(Split-Path -Parent $program);PassThru=$true;RedirectStandardOutput=$stdout;RedirectStandardError=$stderr}
          if($request.value){$args.ArgumentList=[string]$request.value}
          $process=Start-Process @args
          $processHandle=$process.Handle
          Start-Sleep -Milliseconds 1500
          $process.Refresh()
          $result=@{pid=$process.Id;session=[Diagnostics.Process]::GetCurrentProcess().SessionId;exited=$process.HasExited;window_handle=0;executable=$program;sha256=$fingerprint;file_version=$version;launched_at=$launchedAt;existing_instances=$existing}
          if($process.HasExited){$result.exit_code=$process.ExitCode;$result.stdout=[IO.File]::ReadAllText($stdout);$result.stderr=[IO.File]::ReadAllText($stderr)}else{$result.window_handle=$process.MainWindowHandle.ToInt64()}
          $result.artifact_unchanged=((Get-LaunchFingerprint $program) -eq $fingerprint)
          $result.note='Inspect this new PID and its window, not a pre-existing instance. If this process exited or the artifact changed, its old windows do not verify the new build. Inspect stderr; no window alone is not evidence of missing OpenGL.'
          $process.Dispose()
        } elseif($request.action -eq 'screenshot') {
          [HubScreenDpi]::SetThreadDpiAwarenessContext([IntPtr](-4)) | Out-Null
          $bounds=[Drawing.Rectangle]::new([HubScreenDpi]::GetSystemMetrics(76),[HubScreenDpi]::GetSystemMetrics(77),[HubScreenDpi]::GetSystemMetrics(78),[HubScreenDpi]::GetSystemMetrics(79))
          $bitmap=[Drawing.Bitmap]::new($bounds.Width,$bounds.Height)
          $graphics=[Drawing.Graphics]::FromImage($bitmap)
          try {
            $graphics.CopyFromScreen($bounds.X,$bounds.Y,0,0,$bounds.Size)
            $image=Join-Path "$Root\results" ($file.BaseName+'.png')
            $bitmap.Save($image,[Drawing.Imaging.ImageFormat]::Png)
            $result=@{image_path=$image;width=$bounds.Width;height=$bounds.Height;origin_x=$bounds.X;origin_y=$bounds.Y;screen=(Screen-Space)}
          } finally {$graphics.Dispose();$bitmap.Dispose()}
        } elseif($request.action -eq 'windows') {
          $elements=[Windows.Automation.AutomationElement]::RootElement.FindAll([Windows.Automation.TreeScope]::Children,[Windows.Automation.Condition]::TrueCondition)
          $rows=@();foreach($element in $elements){try{$rows+=Describe $element}catch{}}
          $result=@{windows=$rows;screen=(Screen-Space);coordinate_note='UIA bounds are control metadata; use fresh screenshot physical pixels for synthetic mouse.'}
        } else {
          if(-not $request.window_handle){throw 'Provide a window_handle from windows.'}
          $window=[Windows.Automation.AutomationElement]::FromHandle([IntPtr][long]$request.window_handle)
          $elements=$window.FindAll([Windows.Automation.TreeScope]::Subtree,[Windows.Automation.Condition]::TrueCondition)
          if($request.action -eq 'ui_tree') {
            $rows=@();foreach($element in $elements){try{$rows+=Describe $element}catch{};if($rows.Count -ge 200){break}}
            $result=@{controls=$rows;total=$elements.Count;truncated=($elements.Count -gt 200);screen=(Screen-Space)}
          } else {
            $target=$null;foreach($element in $elements){if(($element.GetRuntimeId()-join ',') -eq $request.element_id){$target=$element;break}}
            if(-not $target){throw 'Control changed or disappeared. Read ui_tree again.'}
            if($request.action -eq 'ui_invoke') {
              $pattern=$null
              if($target.TryGetCurrentPattern([Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)){([Windows.Automation.InvokePattern]$pattern).Invoke()}
              elseif($target.TryGetCurrentPattern([Windows.Automation.SelectionItemPattern]::Pattern,[ref]$pattern)){([Windows.Automation.SelectionItemPattern]$pattern).Select()}
              elseif($target.TryGetCurrentPattern([Windows.Automation.TogglePattern]::Pattern,[ref]$pattern)){([Windows.Automation.TogglePattern]$pattern).Toggle()}
              elseif($target.Current.NativeWindowHandle -and $target.Current.ClassName -match '(?i)button'){
                $sent=[UIntPtr]::Zero
                if([HubControlMessage]::Click([IntPtr]$target.Current.NativeWindowHandle,0xF5,[UIntPtr]::Zero,[IntPtr]::Zero,2,3000,[ref]$sent) -eq [IntPtr]::Zero){throw 'Button message failed or timed out'}
              } else{throw 'Control does not support Invoke/Selection/Toggle; use virtual input if necessary.'}
              $result=@{invoked=$request.element_id}
            } elseif($request.action -eq 'ui_set_value') {
              $pattern=$null
              if($target.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern,[ref]$pattern)){([Windows.Automation.ValuePattern]$pattern).SetValue([string]$request.value)}
              elseif($target.Current.NativeWindowHandle -and $target.Current.ClassName -match '(?i)edit'){
                $sent=[UIntPtr]::Zero
                if([HubControlMessage]::Text([IntPtr]$target.Current.NativeWindowHandle,0xC,[UIntPtr]::Zero,[string]$request.value,2,3000,[ref]$sent) -eq [IntPtr]::Zero){throw 'Text message failed or timed out'}
              } else{throw 'Control does not support editable values'}
              $result=@{updated=$request.element_id}
            } else {throw 'Unsupported desktop action'}
          }
        }
        Write-Result $out @{state='completed';result=$result}
      } catch {Write-Result $out @{state='failed';error=$_.Exception.Message}}
      finally {Remove-Item -LiteralPath $file.FullName -Force -ErrorAction SilentlyContinue}
    }
    # Keep recent request history; images are also copied back by the host.
    if([DateTime]::UtcNow -gt $nextCleanup){
      $nextCleanup=[DateTime]::UtcNow.AddMinutes(1)
      Get-ChildItem -LiteralPath "$Root\results" -Filter '*.json' | Sort-Object LastWriteTimeUtc -Descending | Select-Object -Skip 500 | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName,(Join-Path $_.DirectoryName ($_.BaseName+'.png')),(Join-Path $_.DirectoryName ($_.BaseName+'.stdout.txt')),(Join-Path $_.DirectoryName ($_.BaseName+'.stderr.txt')) -Force -ErrorAction SilentlyContinue
      }
    }
    Start-Sleep -Milliseconds 250
 }
} catch {Write-Result "$Root\error.json" @{error=$_.Exception.Message;line=$_.InvocationInfo.ScriptLineNumber};throw}
finally {$mutex.ReleaseMutex();$mutex.Dispose()}
