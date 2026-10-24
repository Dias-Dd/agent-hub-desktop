param([string]$VmName='Hub',[Parameter(Mandatory=$true)][string]$ResultPath)
$ErrorActionPreference='Stop'
$result=@{ok=$false;vm=$VmName}
try {
    $id=(Get-VM -Name $VmName).Id.ToString()
    $vm=Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_ComputerSystem -Filter "Name='$id'"
    $keyboard=Get-CimAssociatedInstance -InputObject $vm -ResultClassName Msvm_Keyboard | Select-Object -First 1
    $mouse=Get-CimAssociatedInstance -InputObject $vm -ResultClassName Msvm_SyntheticMouse | Select-Object -First 1
    if(-not $keyboard -or -not $mouse){throw 'Synthetic input device not found'}
    # Shift alone has no default shell action. Always release even if the probe fails.
    try {
        $down=Invoke-CimMethod -InputObject $keyboard -MethodName PressKey -Arguments @{keyCode=[uint32]16}
    } finally {
        $up=Invoke-CimMethod -InputObject $keyboard -MethodName ReleaseKey -Arguments @{keyCode=[uint32]16}
    }
    $move=Invoke-CimMethod -InputObject $mouse -MethodName SetAbsolutePosition -Arguments @{horizontalPosition=[int]500;verticalPosition=[int]500}
    $result=@{ok=($down.ReturnValue -eq 0 -and $up.ReturnValue -eq 0 -and $move.ReturnValue -eq 0);vm=$VmName;press=$down.ReturnValue;release=$up.ReturnValue;mouse_move=$move.ReturnValue}
} catch {$result.error=$_.Exception.Message}
[IO.File]::WriteAllText($ResultPath,($result|ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
