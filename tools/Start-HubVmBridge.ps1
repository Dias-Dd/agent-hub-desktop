param(
    [PSCredential]$Credential,
    [switch]$ServiceMode,
    [int]$OwnerPid = 0,
    [string]$VmName = 'Hub',
    [string]$DataDirectory = "$env:LOCALAPPDATA\AgentMessageHubDesktop\data"
)
# A desktop launched from PowerShell 7 can inherit incompatible module paths.
$env:PSModulePath=(Join-Path $PSHOME 'Modules')+';'+(Join-Path $env:ProgramFiles 'WindowsPowerShell\Modules')
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script in your administrator PowerShell window.'
}
if (-not $ServiceMode -and -not $Credential) { $Credential = Get-Credential -Message 'Windows account inside the VM (not model credentials)' }
if ($OwnerPid) {
    $ownerProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$OwnerPid"
    $ownerSid=(Invoke-CimMethod -InputObject $ownerProcess -MethodName GetOwnerSid).Sid
    if ($ownerSid -ne $identity.User.Value) { throw 'Use the same Windows account for UAC as for Hub.' }
}
$root = Join-Path $DataDirectory 'vm-bridge' 
$requests = Join-Path $root 'requests'; $results = Join-Path $root 'results'; $requestHistory=Join-Path $root 'request-history'
New-Item -ItemType Directory -Path $requests,$results,$requestHistory -Force | Out-Null
# The queue authorizes guest execution: restrict it to this Windows user and SYSTEM.
$acl = [Security.AccessControl.DirectorySecurity]::new()
$acl.SetAccessRuleProtection($true,$false)
foreach ($sid in @($identity.User,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
}
Set-Acl -LiteralPath $root -AclObject $acl
$mutex = [Threading.Mutex]::new($false, 'Local\AgentHubVmBridge')
try {if (-not $mutex.WaitOne(0)) { throw 'A VM bridge is already running.' }}catch [Threading.AbandonedMutexException] {}
# Copy to exact file paths: existing directories are overlaid, never nested.
function Copy-HubSourceToVm {
    param([string]$Source,[string]$Destination,$Session)
    function Get-HubTransferSha256([string]$File){
        $stream=[IO.File]::OpenRead($File);$sha=[Security.Cryptography.SHA256]::Create()
        try{return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','')}finally{$stream.Dispose();$sha.Dispose()}
    }
    $item=Get-Item -LiteralPath $Source -Force -ErrorAction Stop
    $entries=@()
    if($item.PSIsContainer){
        $base=$item.FullName.TrimEnd('\')
        $files=@(Get-ChildItem -LiteralPath $Source -File -Recurse -Force -ErrorAction Stop)
        foreach($file in $files){
            $relative=$file.FullName.Substring($base.Length).TrimStart('\')
            $entries+=@{source=$file.FullName;target=(Join-Path $Destination $relative);sha256=(Get-HubTransferSha256 $file.FullName);bytes=$file.Length}
        }
        Invoke-Command -Session $Session -ArgumentList $Destination -ScriptBlock {param($p) New-Item -ItemType Directory -Path $p -Force|Out-Null}|Out-Null
    }else{
        $entries=@(@{source=$item.FullName;target=$Destination;sha256=(Get-HubTransferSha256 $item.FullName);bytes=$item.Length})
    }
    $manifest=ConvertTo-Json -InputObject @($entries) -Depth 4 -Compress
    Invoke-Command -Session $Session -ArgumentList $manifest -ScriptBlock {
        param($data)
        $parsed=ConvertFrom-Json -InputObject $data
        foreach($entry in $parsed){
            New-Item -ItemType Directory -Path (Split-Path -Parent $entry.target) -Force|Out-Null
            if(Test-Path -LiteralPath $entry.target -PathType Container){throw ('Expected a file, found a directory: '+$entry.target)}
        }
    }|Out-Null
    foreach($entry in $entries){Copy-Item -LiteralPath $entry.source -Destination $entry.target -ToSession $Session -Force -ErrorAction Stop}
    Invoke-Command -Session $Session -ArgumentList $manifest -ScriptBlock {
        param($data)
        $parsed=ConvertFrom-Json -InputObject $data
        foreach($entry in $parsed){
            $stream=[IO.File]::OpenRead($entry.target);$sha=[Security.Cryptography.SHA256]::Create()
            try{$actual=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','')}finally{$stream.Dispose();$sha.Dispose()}
            if($actual -ne $entry.sha256){throw ('Transfer content mismatch: '+$entry.target)}
        }
    }|Out-Null
    $bytes=0;foreach($entry in $entries){$bytes+=$entry.bytes}
    return @{files=$entries.Count;bytes=$bytes;verified=$true;mode=$(if($item.PSIsContainer){'overlay-directory'}else{'replace-file'})}
}
function Invoke-HubChildCommand {
    param([string]$Cwd,[string]$Code,[int]$TimeoutSeconds=300)
    $file=Join-Path ([IO.Path]::GetTempPath()) ('hub-command-'+[guid]::NewGuid().ToString('N')+'.ps1')
    $process=$null
    try {
        $prefix="[Console]::OutputEncoding=[Text.UTF8Encoding]::new(`$false);`$OutputEncoding=[Console]::OutputEncoding;`$ErrorActionPreference='Stop';`$global:LASTEXITCODE=0;`r`ntry {`r`n"
        $suffix="`r`n} catch { [Console]::Error.WriteLine((`$_ | Out-String)); exit 1 }; exit `$global:LASTEXITCODE"
        [IO.File]::WriteAllText($file,$prefix+$Code+$suffix,[Text.UTF8Encoding]::new($true))
        $info=[Diagnostics.ProcessStartInfo]::new()
        $info.FileName=Join-Path $PSHOME 'powershell.exe'
        $info.Arguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$file+'"'
        $info.WorkingDirectory=$Cwd;$info.UseShellExecute=$false;$info.CreateNoWindow=$true
        $info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
        $info.StandardOutputEncoding=[Text.Encoding]::UTF8;$info.StandardErrorEncoding=[Text.Encoding]::UTF8
        $process=[Diagnostics.Process]::new();$process.StartInfo=$info
        if(-not $process.Start()){throw 'Cannot start isolated PowerShell process'}
        $stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
        if(-not $process.WaitForExit($TimeoutSeconds*1000)){
            & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F 2>&1|Out-Null
            throw 'Command timed out; isolated process tree stopped. Inspect files before retrying.'
        }
        $process.WaitForExit()
        $principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
        return [pscustomobject]@{output=($stdout.Result+$stderr.Result);exit_code=$process.ExitCode;elevated=$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)}
    } finally {if($process){$process.Dispose()};Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue}
}
$activeCommands=@{}
function Get-HubActorKey($Job){return ([string]$Job.project+':'+[string]$Job.agent)}
function Test-HubActorBusy($Job){
    $actor=Get-HubActorKey $Job
    foreach($entry in $script:activeCommands.Values){if($entry.actor -eq $actor){return $true}}
    return $false
}
function Complete-HubCommands {
    foreach($id in @($script:activeCommands.Keys)){
        $entry=$script:activeCommands[$id];$remote=$entry.remote
        if($remote.State -notin @('Completed','Failed','Stopped') -and (Now)-$entry.started -le ($entry.timeout+30)){continue}
        try{
            if($remote.State -notin @('Completed','Failed','Stopped')){Stop-Job $remote;throw 'Command connection timed out; operation may have executed. Inspect guest state before retrying.'}
            $value=Receive-Job $remote -ErrorAction Stop
            if($null -eq $value -or $null -eq $value.exit_code){throw 'Command returned no execution result; not confirmed successful. Inspect guest state before retrying.'}
            Save-Json $entry.path @{request_id=$id;state='completed';output=$value.output;exit_code=$value.exit_code;elevated=$value.elevated;finished=(Now)}
        }catch{
            Save-Json $entry.path @{request_id=$id;state='unknown';error=$_.Exception.Message;finished=(Now)}
        }finally{Remove-Job $remote -Force -ErrorAction SilentlyContinue;$script:activeCommands.Remove($id)}
    }
}
$session = $null
$probe = $null
$busyId = $null
$autoReconnectEnabled=$false;$lastConnectionCipher=$null;$nextReconnect=0;$reconnectDelay=3;$connectionError=$null
function Save-Json($Path,$Value) {
    $temp = "$Path.tmp"
    [IO.File]::WriteAllText($temp,($Value | ConvertTo-Json -Depth 12 -Compress),[Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temp -Destination $Path -Force
}
function Now { [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0 }
function Connect-Guest($Name,$Login,$Unattended=$true,[bool]$Recovering=$false) {
    if($script:desktopHealthJob){Stop-Job $script:desktopHealthJob -ErrorAction SilentlyContinue;Remove-Job $script:desktopHealthJob -Force -ErrorAction SilentlyContinue;$script:desktopHealthJob=$null}
    if ($script:session) { Remove-PSSession $script:session -ErrorAction SilentlyContinue; $script:session=$null; $script:probe=$null }
    $VmName = $Name; $Credential = $Login
    $vm=Get-VM -Name $VmName
    $script:VmName=$VmName
    $script:connectionPhase=if($Recovering){'reconnecting'}else{'booting'};Publish-Status
    if($Recovering -and $vm.State -ne 'Running'){throw 'Windows is not running; waiting without starting it.'}
    if(-not $Recovering -and ($vm.State -eq 'Off' -or $vm.State -eq 'Saved')){Start-VM -Name $VmName | Out-Null}
    elseif(-not $Recovering -and $vm.State -eq 'Paused'){Resume-VM -Name $VmName | Out-Null}
    $deadline=(Get-Date).AddMinutes(5)
    while(-not $script:session){
        if($OwnerPid -and -not(Get-Process -Id $OwnerPid -ErrorAction SilentlyContinue)){throw 'Hub exited'}
        Publish-Status
        if(Test-Path -LiteralPath (Join-Path $root 'power-override.json')){$pendingPower=Get-Content -LiteralPath (Join-Path $root 'power-override.json') -Raw -Encoding UTF8|ConvertFrom-Json;if($pendingPower.vm -eq $VmName -and (Now)-$pendingPower.created -lt 120){throw 'User requested VM shutdown; connection cancelled.'}}
        try{$script:session=New-PSSession -VMName $VmName -Credential $Credential -ErrorAction Stop}
        catch{if($Recovering -or $_.Exception.Message -match 'credential|password|authentication|凭据|密码|认证|登录失败' -or (Get-Date) -ge $deadline){throw};Start-Sleep -Seconds 2}
    }
    if($script:desktopHealthJob){Stop-Job $script:desktopHealthJob -ErrorAction SilentlyContinue;Remove-Job $script:desktopHealthJob -Force -ErrorAction SilentlyContinue;$script:desktopHealthJob=$null}
    $script:desktopReady=$false
    $script:connectionPhase='deploying' 
    $script:probe = Invoke-Command -Session $session -ScriptBlock {
        $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
        $principal=[Security.Principal.WindowsPrincipal]::new($identity)
        [pscustomobject]@{elevated=$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator);account=$identity.Name; windows=(Get-CimInstance Win32_OperatingSystem).Caption; powershell=$PSVersionTable.PSVersion.ToString()}
    }
    if($Recovering){
        $script:connectionPhase='ready';$script:connectionError=$null;$script:desktopReady=$false;$script:lastDesktopHealth=0
        $script:desktopWarning='命令连接已恢复，正在检查 Windows 桌面。'
        return
    }
    $probeId = [guid]::NewGuid().ToString('N')
    $probeLocal = Join-Path $root "probe-$probeId.txt"
    $probeReturn = Join-Path $root "probe-$probeId-return.txt"
    $probeGuest = Invoke-Command -Session $session -ArgumentList $probeId -ScriptBlock { param($id) Join-Path $env:TEMP "hub-probe-$id.txt" }
    try {
        [IO.File]::WriteAllText($probeLocal, "Deskfellows transfer probe $probeId")
        Copy-Item -LiteralPath $probeLocal -Destination $probeGuest -ToSession $session
        Copy-Item -LiteralPath $probeGuest -Destination $probeReturn -FromSession $session
        if ((Get-FileHash -LiteralPath $probeLocal).Hash -ne (Get-FileHash -LiteralPath $probeReturn).Hash) { throw 'VM transfer probe hash mismatch' }
        Write-Host 'PowerShell Direct execution and two-way file transfer probe passed.'
    } finally {
        Remove-Item -LiteralPath $probeLocal,$probeReturn -Force -ErrorAction SilentlyContinue
        Invoke-Command -Session $session -ArgumentList $probeGuest -ScriptBlock { param($p) Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }
    }

    $script:desktopWarning=$null
    $script:unattendedWarning=$null
    $script:unattendedConfigured=$false
    $script:unattendedEnabled=[bool]$Unattended
    try {
        $setupSource=Join-Path $PSScriptRoot 'Configure-HubVmUnattended.ps1'
        Invoke-Command -Session $session -ScriptBlock {New-Item -ItemType Directory -Path 'C:\ProgramData\AgentHubDesktop' -Force|Out-Null}
        Copy-Item -LiteralPath $setupSource -Destination 'C:\ProgramData\AgentHubDesktop\Configure-HubVmUnattended.ps1' -ToSession $session -Force
        $configured=Invoke-Command -Session $session -ArgumentList $Login,([bool]$Unattended) -ScriptBlock {param($login,$enabled) & ([scriptblock]::Create((Get-Content -LiteralPath 'C:\ProgramData\AgentHubDesktop\Configure-HubVmUnattended.ps1' -Raw -Encoding UTF8))) -Credential $login -Enabled $enabled}
        $script:unattendedConfigured=[bool]$configured.configured
    }catch{$script:unattendedWarning='无人值守配置未完成：'+$_.Exception.Message}
    try {
        $desktopSource=Join-Path $PSScriptRoot 'HubDesktopAgent.ps1'
        if(-not(Test-Path -LiteralPath $desktopSource)){throw 'Desktop service package is missing'}
        Invoke-Command -Session $session -ScriptBlock {New-Item -ItemType Directory -Path 'C:\ProgramData\AgentHubDesktop' -Force | Out-Null}
        Copy-Item -LiteralPath $desktopSource -Destination 'C:\ProgramData\AgentHubDesktop\HubDesktopAgent.ps1' -ToSession $session -Force
        Invoke-Command -Session $session -ScriptBlock {
            $root='C:\ProgramData\AgentHubDesktop';$account=[Security.Principal.WindowsIdentity]::GetCurrent().Name
            $old=Get-ScheduledTask -TaskName AgentHubDesktop -ErrorAction SilentlyContinue
            if($old){Stop-ScheduledTask -TaskName AgentHubDesktop -ErrorAction SilentlyContinue}
            $action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "'+$root+'\HubDesktopAgent.ps1"')
            $principal=New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Highest
            $trigger=New-ScheduledTaskTrigger -AtLogOn -User $account
            $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
            Register-ScheduledTask -TaskName AgentHubDesktop -Action $action -Principal $principal -Trigger $trigger -Settings $settings -Force | Out-Null
            $desktopStarted=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0
            Start-ScheduledTask -TaskName AgentHubDesktop
            for($i=0;$i -lt 30;$i++){
                if(Test-Path "$root\status.json"){try{$st=Get-Content "$root\status.json" -Raw -Encoding UTF8|ConvertFrom-Json;if($st.updated -ge $desktopStarted -and ([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0)-$st.updated -lt 5){return}}catch{}}
                Start-Sleep -Milliseconds 200
            };throw 'Desktop service waiting for an interactive Windows logon; command execution remains available.'
        }
    } catch {$script:desktopWarning='桌面通道暂未就绪，等待 Windows 更新完成或用户登录；命令通道可单独使用。'}
    $script:desktopReady=-not [bool]$script:desktopWarning
    $script:VmName = $Name
    $script:connectionPhase='ready';$script:connectionError=$null
}
function Update-DesktopHealth {
    if($script:desktopHealthJob){
        $job=$script:desktopHealthJob
        if($job.State -in @('Completed','Failed','Stopped')){
            try{
                $health=Receive-Job $job -ErrorAction Stop
                $script:desktopReady=[bool]$health.ready
                $script:desktopWarning=if($script:desktopReady){$null}elseif($health.warning){$health.warning}else{'桌面通道暂未就绪，等待 Windows 更新完成或用户登录；命令通道可单独使用。'}
            }catch{$script:desktopReady=$false;$script:desktopWarning='桌面状态暂时不可读，正在自动重试。'}
            Remove-Job $job -Force -ErrorAction SilentlyContinue;$script:desktopHealthJob=$null
        }elseif((Now)-$script:desktopHealthStarted -gt 8){
            Stop-Job $job -ErrorAction SilentlyContinue;Remove-Job $job -Force -ErrorAction SilentlyContinue;$script:desktopHealthJob=$null
            $script:desktopReady=$false;$script:desktopWarning='桌面状态暂时不可读，正在自动重试。'
        }
        return
    }
    if($session -and $session.State -eq 'Opened' -and $session.Availability -eq 'Available' -and $connectionPhase -eq 'ready' -and (Now)-$script:lastDesktopHealth -gt $(if($script:desktopReady){30}else{10})){
        $script:lastDesktopHealth=Now;$script:desktopHealthStarted=Now
        try{$healthLogin=if($lastConnectionCipher){Get-ReconnectCredential $lastConnectionCipher}else{$Credential};$script:desktopHealthJob=Invoke-Command -VMName $VmName -Credential $healthLogin -AsJob -ScriptBlock {
            try{
                $st=Get-Content -LiteralPath 'C:\ProgramData\AgentHubDesktop\status.json' -Raw -Encoding UTF8 -ErrorAction Stop|ConvertFrom-Json
                $ready=([bool]$st.updated -and ([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0)-$st.updated -lt 8)
                if(-not $ready){
                    $task=Get-ScheduledTask -TaskName AgentHubDesktop -ErrorAction SilentlyContinue
                    if($task -and $task.State -ne 'Running'){Start-ScheduledTask -TaskName AgentHubDesktop -ErrorAction SilentlyContinue}
                    if(Test-Path 'C:\ProgramData\AgentHubDesktop\error.json'){
                        $fault=Get-Content 'C:\ProgramData\AgentHubDesktop\error.json' -Raw -Encoding UTF8|ConvertFrom-Json
                        return @{ready=$false;warning=('桌面服务异常，正在恢复：'+$fault.error)}
                    }
                }
                @{ready=$ready}
            }catch{@{ready=$false;warning=('桌面状态检查失败：'+$_.Exception.Message)}}
        }}catch{$script:desktopReady=$false}finally{$healthLogin=$null}
    }
}
function Get-ReconnectCredential($cipher){
    Add-Type -AssemblyName System.Security
    $bytes=$null;$login=$null
    try{
        $bytes=[Security.Cryptography.ProtectedData]::Unprotect([Convert]::FromBase64String($cipher),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
        $login=[Text.Encoding]::UTF8.GetString($bytes)|ConvertFrom-Json
        [PSCredential]::new($login.username,(ConvertTo-SecureString $login.password -AsPlainText -Force))
    }finally{if($bytes){[Array]::Clear($bytes,0,$bytes.Length)};$login=$null}
}
function Restore-ReconnectPreference {
    if(-not $ServiceMode){return}
    try{
        $last=Get-Content -LiteralPath (Join-Path $root 'last-vm.json') -Raw -Encoding UTF8|ConvertFrom-Json
        if($last.auto_connect -eq $false){return}
        $hash=[Security.Cryptography.SHA256]::Create()
        try{$name=([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($last.vm)))).Replace('-','').ToLowerInvariant()}finally{$hash.Dispose()}
        $saved=Get-Content -LiteralPath (Join-Path $root ('saved-connections\'+$name+'.json')) -Raw -Encoding UTF8|ConvertFrom-Json
        $script:VmName=$saved.vm;$script:lastConnectionCipher=$saved.credential_encrypted
        $script:lastUnattended=if($null -eq $saved.unattended){$true}else{[bool]$saved.unattended}
        $script:autoReconnectEnabled=$true;$script:connectionPhase='reconnecting'
    }catch{}
}
function Update-VmConnection {
    if(-not $script:autoReconnectEnabled -or -not $script:lastConnectionCipher -or $busyId){return}
    if($session -and $session.State -eq 'Opened' -and $script:vmPowerState -eq 'Running'){return}
    $script:desktopReady=$false
    if((Now) -lt $script:nextReconnect){return}
    $loginCredential=$null
    try{
        $power=(Get-VM -Name $VmName -ErrorAction Stop).State.ToString()
        if($power -ne 'Running'){
            if($session){Remove-PSSession $session -ErrorAction SilentlyContinue;$script:session=$null}
            $script:connectionPhase='waiting_windows';$script:connectionError='等待虚拟机 Windows 启动；不会自动启动用户已关闭的虚拟机。'
            $script:nextReconnect=(Now)+3;return
        }
        $script:connectionPhase='reconnecting';$script:connectionError='命令连接已断开，正在自动重连；不会重放已发送的命令。'
        Publish-Status
        try{$loginCredential=Get-ReconnectCredential $script:lastConnectionCipher}
        catch{$script:autoReconnectEnabled=$false;$script:connectionPhase='credentials_required';$script:connectionError='已保存凭据无法解密，请重新填写虚拟机凭据。';return}
        Connect-Guest $VmName $loginCredential $script:lastUnattended $true
        $script:reconnectDelay=3;$script:nextReconnect=0;$script:connectionError=$null
    }catch{
        if($_.Exception.Message -match 'credential|password|authentication|凭据|密码|认证|登录失败|logon failure|0x8007052e'){
            $script:autoReconnectEnabled=$false;$script:connectionPhase='credentials_required';$script:connectionError='虚拟机凭据无效，请更新账号或密码；已停止自动尝试。'
        }else{
            $script:connectionPhase='reconnecting';$script:connectionError='Windows 暂未接受连接，稍后自动重试。'
            $script:nextReconnect=(Now)+$script:reconnectDelay;$script:reconnectDelay=[Math]::Min(60,$script:reconnectDelay*2)
        }
    }finally{if($loginCredential){$loginCredential.Password.Dispose();$loginCredential=$null}}
}
function Publish-Status {
    if($script:lastPublish -and (Now)-$script:lastPublish -lt 2){return}
    $script:lastPublish=Now
    if($connectionPhase -eq 'ready' -and (-not $session -or $session.State -ne 'Opened')){
        $script:connectionPhase=if($autoReconnectEnabled){'reconnecting'}else{'disconnected'}
        $script:desktopReady=$false
    }
    Update-DesktopHealth
    if(-not $script:nextPowerPoll -or (Get-Date) -gt $script:nextPowerPoll){
        $script:nextPowerPoll=(Get-Date).AddSeconds(10)
        try{$script:vmPowerState=(Get-VM -Name $VmName -ErrorAction Stop).State.ToString();$script:powerWarning=$null}catch{$script:powerWarning='电源状态暂时不可读，保留上次状态';if(-not $script:vmPowerState){$script:vmPowerState='Unknown'}}
    }
    $commandConnected=([bool]$session -and $session.State -eq 'Opened' -and $vmPowerState -eq 'Running')
    if(-not $commandConnected){
        $script:desktopReady=$false
        if($connectionPhase -eq 'ready'){$script:connectionPhase=if(-not $autoReconnectEnabled){'disconnected'}elseif($vmPowerState -ne 'Running'){'waiting_windows'}else{'reconnecting'}}
    }
    Save-Json (Join-Path $root 'status.json') @{vm=$VmName;updated=(Now);connected=$commandConnected;power_state=$vmPowerState;power_warning=$powerWarning;connection_phase=$connectionPhase;connection_error=$connectionError;auto_reconnect=$autoReconnectEnabled;account=$probe.account;command_elevated=$(if($commandConnected){$probe.elevated}else{$null});unattended=@{enabled=$unattendedEnabled;configured=$unattendedConfigured;warning=$unattendedWarning};windows=$probe.windows;busy=$busyId;operations=@('thumbnail','exec','push','pull','desktop_launch','windows','ui_tree','ui_invoke','ui_set_value','screenshot','key','mouse');desktop=(@{backend='Windows UI Automation';ready=[bool]$desktopReady;warning=$desktopWarning;virtual_input='Hyper-V synthetic devices'});protocol=4;command_isolation='process-and-connection';parallel_commands=$activeCommands.Count;helper_pid=$PID;service_mode=[bool]$ServiceMode}
}
try {
    if (-not $ServiceMode) { Connect-Guest $VmName $Credential }else{Restore-ReconnectPreference}
    # Never replay an operation whose old worker stopped before recording completion.
    foreach ($file in Get-ChildItem -LiteralPath $requests -Filter '*.json') {
        $resultPath = Join-Path $results $file.Name
        $oldRequest = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($oldRequest.control) {
            if (Test-Path -LiteralPath $resultPath) {
                $oldResult=Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($oldResult.state -eq 'running') { Save-Json $resultPath @{state='failed';error='Connection worker restarted; please reconnect.'} }
            } elseif ((Now)-$oldRequest.created -gt 120) {
                $oldRequest.PSObject.Properties.Remove('credential_encrypted'); Save-Json $file.FullName $oldRequest
                Save-Json $resultPath @{state='failed';error='Connection request expired; please reconnect.'}
            }
            continue
        }
        if (-not (Test-Path -LiteralPath $resultPath)) {
            Save-Json $resultPath @{request_id=$file.BaseName;state='not_replayed';error='Bridge restarted before this operation was processed; inspect guest state before resubmitting.'}
        } else {
            $previous = Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($previous.state -eq 'running') { Save-Json $resultPath @{request_id=$file.BaseName;state='unknown';error='Worker stopped during operation; not replayed.'} }
        }
    }
    Write-Host "Connected to VM $VmName as $($probe.account). Leave this window open. Ctrl+C disconnects the bridge."
    while ($true) {
        if ($OwnerPid -and -not (Get-Process -Id $OwnerPid -ErrorAction SilentlyContinue)) { break }
        Complete-HubCommands
        $busyId=if($activeCommands.Count){@($activeCommands.Keys)[0]}else{$null}; Publish-Status
        $blockedActors=@{}
        foreach ($file in Get-ChildItem -LiteralPath $requests -Filter '*.json' | Sort-Object LastWriteTimeUtc,Name) {
            if ($OwnerPid -and -not (Get-Process -Id $OwnerPid -ErrorAction SilentlyContinue)) { break }
            $resultPath = Join-Path $results $file.Name
            if (Test-Path -LiteralPath $resultPath) {
                try{
                    $record=Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8|ConvertFrom-Json
                    if($record.state -notin @('queued','running')){
                        $archive=Join-Path $requestHistory $file.Name
                        if(-not(Test-Path -LiteralPath $archive)){Move-Item -LiteralPath $file.FullName -Destination $archive -ErrorAction Stop}
                    }
                }catch{Write-Warning 'Could not archive a completed request; it remains available.'}
                continue
            }
            try {$job=Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json}
            catch {if(Test-Path -LiteralPath $file.FullName){Save-Json $resultPath @{state='failed';error='Invalid bridge request; not executed.'}};continue}
            $actor=Get-HubActorKey $job
            if(-not $job.control -and ($blockedActors.ContainsKey($actor) -or (Test-HubActorBusy $job))){$blockedActors[$actor]=$true;continue}
            if($job.action -eq 'exec' -and $activeCommands.Count -ge 16){$blockedActors[$actor]=$true;continue}
            Save-Json $resultPath @{request_id=$job.id;state='running';started=(Now)}
            $submitted=$false
            try {
                if ($job.control) {
                    if ($job.action -eq 'list') {
                        $vms = @(Get-VM | Select-Object @{N='name';E={$_.Name}},@{N='state';E={$_.State.ToString()}},@{N='id';E={$_.Id.ToString()}},@{N='generation';E={$_.Generation}})
                        Save-Json $resultPath @{state='completed';vms=$vms}
                    } elseif ($job.action -eq 'thumbnail') {
                        $vm=Get-VM -Name $job.vm_name -ErrorAction Stop
                        if($vm.State -ne 'Running'){Save-Json $resultPath @{state='completed';available=$false;vm=$vm.Name;power_state=$vm.State.ToString();note='虚拟机未运行'};continue}
                        $ns='root\virtualization\v2'
                        $system=Get-CimInstance -Namespace $ns -ClassName Msvm_ComputerSystem -Filter ("Name='"+$vm.Id.ToString()+"'")
                        $setting=Get-CimAssociatedInstance -InputObject $system -Association Msvm_SettingsDefineState -ResultClassName Msvm_VirtualSystemSettingData | Select-Object -First 1
                        if(-not $setting){throw 'Hyper-V did not return current virtual system settings'}
                        $service=Get-CimInstance -Namespace $ns -ClassName Msvm_VirtualSystemManagementService
                        $thumb=Invoke-CimMethod -InputObject $service -MethodName GetVirtualSystemThumbnailImage -Arguments @{TargetSystem=$setting;WidthPixels=[uint16]320;HeightPixels=[uint16]180}
                        if($thumb.ReturnValue -ne 0){throw ('GetVirtualSystemThumbnailImage failed: '+$thumb.ReturnValue)}
                        $pixels=[byte[]]$thumb.ImageData
                        $expected=320*180*2
                        if($pixels.Length -eq $expected+4){
                            # CIM OctetString carries a network-order length before its octets.
                            $length=([uint32]$pixels[0]*16777216)+([uint32]$pixels[1]*65536)+([uint32]$pixels[2]*256)+[uint32]$pixels[3]
                            if($length -ne $expected -and $length -ne $pixels.Length){throw ('Invalid CIM OctetString length: '+$length)}
                            $raw=[byte[]]::new($expected);[Array]::Copy($pixels,4,$raw,0,$expected);$pixels=$raw
                        }
                        if($pixels.Length -ne $expected){throw ('Unexpected RGB565 payload size: '+$pixels.Length)}
                        Save-Json $resultPath @{state='completed';available=$true;vm=$vm.Name;width=320;height=180;format='rgb565le';image_data=[Convert]::ToBase64String($pixels);captured_at=(Now)}
                    } elseif ($job.action -eq 'connect') {
                        $script:autoReconnectEnabled=$false
                        Add-Type -AssemblyName System.Security
                        try {
                            $savedCipher=$job.credential_encrypted
                            $bytes=[Security.Cryptography.ProtectedData]::Unprotect([Convert]::FromBase64String($job.credential_encrypted),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
                            $login=[Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json
                            $secret=ConvertTo-SecureString -String $login.password -AsPlainText -Force
                            $loginCredential=[PSCredential]::new($login.username,$secret)
                        } finally {
                            if ($bytes) { [Array]::Clear($bytes,0,$bytes.Length) }; $login=$null
                            $job.PSObject.Properties.Remove('credential_encrypted'); Save-Json $file.FullName $job
                        }
                        $script:lastConnectionCipher=$savedCipher;$script:lastUnattended=[bool]$job.unattended;$script:VmName=$job.vm_name
                        $script:autoReconnectEnabled=$true;$script:nextReconnect=0;$script:reconnectDelay=3
                        try { Connect-Guest $job.vm_name $loginCredential $job.unattended }
                        finally { $loginCredential=$null; if ($secret) { $secret.Dispose();$secret=$null } }
                        if ($job.remember -and $job.saved_path) {
                            New-Item -ItemType Directory -Path (Split-Path -Parent $job.saved_path) -Force | Out-Null
                            Save-Json $job.saved_path @{vm=$VmName;account=$probe.account;credential_encrypted=$savedCipher;unattended=[bool]$job.unattended}
                        }elseif($job.saved_path -and (Test-Path -LiteralPath $job.saved_path)){
                            $savedPreferences=Get-Content -LiteralPath $job.saved_path -Raw -Encoding UTF8|ConvertFrom-Json
                            $savedPreferences|Add-Member -NotePropertyName unattended -NotePropertyValue ([bool]$job.unattended) -Force
                            Save-Json $job.saved_path $savedPreferences
                        }
                        Save-Json (Join-Path $root 'last-vm.json') @{vm=$VmName;auto_connect=$true}
                        $savedCipher=$null
                        Publish-Status
                        Save-Json $resultPath @{state='completed';vm=$VmName;account=$probe.account;transfer_probe='passed';credential_saved=[bool]$job.remember;desktop_warning=$desktopWarning;unattended_enabled=$unattendedEnabled;unattended_configured=$unattendedConfigured;unattended_warning=$unattendedWarning}
                    } elseif ($job.action -in @('power_on','power_off','power_force')) {
                        if($job.action -eq 'power_on'){if((Get-VM -Name $job.vm_name).State -eq 'Paused'){Resume-VM -Name $job.vm_name | Out-Null}elseif((Get-VM -Name $job.vm_name).State -ne 'Running'){Start-VM -Name $job.vm_name | Out-Null}}
                        elseif($job.action -eq 'power_off'){if((Get-VM -Name $job.vm_name).State -ne 'Off'){Stop-VM -Name $job.vm_name -Confirm:$false}}
                        else{if((Get-VM -Name $job.vm_name).State -ne 'Off'){Stop-VM -Name $job.vm_name -TurnOff -Force -Confirm:$false}}
                        if($job.action -ne 'power_on' -and $job.vm_name -eq $VmName){
                            $script:autoReconnectEnabled=$false;$script:connectionPhase='disconnected';$script:connectionError=$null
                            Save-Json (Join-Path $root 'last-vm.json') @{vm=$VmName;auto_connect=$false}
                            if($session){Remove-PSSession $session -ErrorAction SilentlyContinue};$session=$null;$probe=$null
                        }
                        Remove-Item -LiteralPath (Join-Path $root 'power-override.json') -Force -ErrorAction SilentlyContinue
                        $script:nextPowerPoll=$null;Publish-Status
                        Save-Json $resultPath @{state='completed';vm=$job.vm_name;power_state=(Get-VM -Name $job.vm_name).State.ToString()}
                    } elseif ($job.action -eq 'disconnect') {
                        $script:autoReconnectEnabled=$false;$script:connectionPhase='disconnected';$script:connectionError=$null
                        Save-Json (Join-Path $root 'last-vm.json') @{vm=$VmName;auto_connect=$false}
                        if ($session) { Remove-PSSession $session }; $session=$null; $probe=$null
                        Publish-Status; Save-Json $resultPath @{state='completed';connected=$false}
                    }
                    continue
                }
                if (-not $session -or $session.State -ne 'Opened') { throw 'VM is not connected. Reconnect in settings.' }
                $busyId=$job.id; Publish-Status
                Invoke-Command -Session $session -ArgumentList $job.guest_cwd -ScriptBlock { param($cwd) New-Item -ItemType Directory -Path $cwd -Force | Out-Null }
                if ($job.action -in @('key','mouse')) {
                    $lease=Invoke-Command -Session $session -ArgumentList $job.owner -ScriptBlock {
                        param($owner)
                        $r='C:\ProgramData\AgentHubDesktop';$id=[guid]::NewGuid().ToString('N')
                        [IO.File]::WriteAllText("$r\requests\$id.tmp",(@{action='desktop_acquire';owner=$owner;expires=([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+30)}|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
                        Move-Item -LiteralPath "$r\requests\$id.tmp" -Destination "$r\requests\$id.json"
                        for($i=0;$i -lt 40;$i++){
                            if(Test-Path "$r\results\$id.json"){$reply=Get-Content "$r\results\$id.json" -Raw -Encoding UTF8|ConvertFrom-Json;if($reply.state -ne 'running'){return $reply}}
                            Start-Sleep -Milliseconds 200
                        };throw 'Desktop lease timed out'
                    }
                    if($lease.state -ne 'completed'){throw $lease.error}
                    if($lease.result.session -ne $lease.result.console_session){throw 'Virtual input targets the console. Attach the logged-in desktop to the VM console first; UI Automation remains separate.'}
                    if($job.action -eq 'mouse' -and ($job.x -lt 0 -or $job.y -lt 0 -or $job.x -ge $lease.result.screen.width -or $job.y -ge $lease.result.screen.height)){throw 'Mouse coordinates must use current screenshot physical pixels; capture a new screenshot after a resolution/session change.'}
                    $vmId=(Get-VM -Name $VmName).Id.ToString()
                    $vmSystem=Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_ComputerSystem -Filter "Name='$vmId'"
                    if($job.action -eq 'key') {
                        $device=Get-CimAssociatedInstance -InputObject $vmSystem -ResultClassName Msvm_Keyboard | Select-Object -First 1
                        $pressed=@()
                        try {
                            foreach($key in $job.key_codes){$r=Invoke-CimMethod -InputObject $device -MethodName PressKey -Arguments @{keyCode=[uint32]$key};if($r.ReturnValue -ne 0){throw "Hyper-V PressKey failed: $($r.ReturnValue)"};$pressed+= $key}
                        } finally {
                            [Array]::Reverse($pressed)
                            foreach($key in $pressed){Invoke-CimMethod -InputObject $device -MethodName ReleaseKey -Arguments @{keyCode=[uint32]$key} | Out-Null}
                        }
                    } else {
                        $device=Get-CimAssociatedInstance -InputObject $vmSystem -ResultClassName Msvm_SyntheticMouse | Select-Object -First 1
                        $r=Invoke-CimMethod -InputObject $device -MethodName SetAbsolutePosition -Arguments @{horizontalPosition=[int]$job.x;verticalPosition=[int]$job.y}
                        if($r.ReturnValue -ne 0){throw "Hyper-V mouse position failed: $($r.ReturnValue)"}
                        if($job.button){$r=Invoke-CimMethod -InputObject $device -MethodName ClickButton -Arguments @{buttonIndex=[uint32]$job.button};if($r.ReturnValue -ne 0){throw "Hyper-V click failed: $($r.ReturnValue)"}}
                    }
                    Save-Json $resultPath @{state='completed';backend='Hyper-V synthetic input';request_id=$job.id}
                } elseif ($job.action -eq 'exec') {
                    $submitted=$true
                    # Each command gets a separate PowerShell Direct connection and
                    # child process. Never execute member scripts in the management session.
                    $login=if($lastConnectionCipher){Get-ReconnectCredential $lastConnectionCipher}else{$Credential}
                    if(-not $login){throw 'VM command credentials are unavailable; reconnect in settings.'}
                    try{
                        $remote = Invoke-Command -VMName $VmName -Credential $login -AsJob -ArgumentList $job.guest_cwd,$job.script,$job.timeout_seconds,${function:Invoke-HubChildCommand}.ToString() -ScriptBlock {
                            param($cwd,$code,$seconds,$functionCode)
                            $ErrorActionPreference='Stop'
                            New-Item -ItemType Directory -Path $cwd -Force|Out-Null
                            ${function:Invoke-HubChildCommand}=[scriptblock]::Create($functionCode)
                            Invoke-HubChildCommand -Cwd $cwd -Code $code -TimeoutSeconds $seconds
                        }
                    }finally{$login=$null}
                    $activeCommands[$job.id]=@{remote=$remote;actor=(Get-HubActorKey $job);path=$resultPath;started=(Now);timeout=$job.timeout_seconds}
                } elseif ($job.action -eq 'push') {
                    $submitted=$true
                    $copied=Copy-HubSourceToVm -Source $job.local_path -Destination $job.guest_path -Session $session
                    Save-Json $resultPath @{request_id=$job.id;state='completed';guest_path=$job.guest_path;transfer=$copied;finished=(Now)}
                } elseif ($job.action -eq 'pull') {
                    if (Test-Path -LiteralPath $job.local_path -PathType Container) { throw 'Destination directory exists; choose a new transfer directory.' }
                    New-Item -ItemType Directory -Path (Split-Path -Parent $job.local_path) -Force | Out-Null
                    $submitted=$true
                    Copy-Item -LiteralPath $job.guest_path -Destination $job.local_path -FromSession $session -Recurse -Force
                    Save-Json $resultPath @{request_id=$job.id;state='completed';local_path=$job.local_path}
                } else { throw 'Unsupported operation' }
            } catch {
                $safeError=$_.Exception.Message
                if ($job.control -and $job.action -eq 'connect') {
                    if ($session) { Remove-PSSession $session -ErrorAction SilentlyContinue }; $session=$null; $probe=$null; Publish-Status
                    if($safeError -match 'credential|password|authentication|凭据|密码|认证|登录失败|logon failure|0x8007052e'){$script:autoReconnectEnabled=$false;$script:connectionPhase='credentials_required';$script:connectionError='虚拟机凭据无效，请更新账号或密码；已停止自动尝试。'}
                    elseif($autoReconnectEnabled){$script:connectionPhase='reconnecting'}
                    $safeError='Connection failed. Check VM running state, Windows username and password, and use the same host Windows account for UAC.' }
                if($job.control -and $job.action -in @('power_off','power_force')){Remove-Item -LiteralPath (Join-Path $root 'power-override.json') -Force -ErrorAction SilentlyContinue}
                $outcome='failed'
                if($submitted -and (-not $session -or $session.State -ne 'Opened')){$outcome='unknown';$safeError='命令连接在执行途中断开；操作可能已执行，不自动重放，请恢复连接后检查现场。'}
                Save-Json $resultPath @{request_id=$job.id;state=$outcome;error=$safeError;finished=(Now)}
            }
        }
        Update-VmConnection
        Start-Sleep -Milliseconds $(if($activeCommands.Count){250}else{750})
    }
} catch {
    Save-Json (Join-Path $root 'last-error.json') @{at=(Now);error_type=$_.Exception.GetType().FullName;error_id=$_.FullyQualifiedErrorId;line=$_.InvocationInfo.ScriptLineNumber}
} finally {
    foreach($id in @($activeCommands.Keys)){
        $entry=$activeCommands[$id];Stop-Job $entry.remote -ErrorAction SilentlyContinue
        Remove-Job $entry.remote -Force -ErrorAction SilentlyContinue
        Save-Json $entry.path @{request_id=$id;state='unknown';error='Bridge stopped during this command; inspect guest state before retrying.';finished=(Now)}
    }
    if($script:desktopHealthJob){Stop-Job $script:desktopHealthJob -ErrorAction SilentlyContinue;Remove-Job $script:desktopHealthJob -Force -ErrorAction SilentlyContinue}
    Save-Json (Join-Path $root 'status.json') @{vm=$VmName;updated=0;connected=$false}
    if ($session) { Remove-PSSession $session }
    $mutex.ReleaseMutex();$mutex.Dispose()
}
