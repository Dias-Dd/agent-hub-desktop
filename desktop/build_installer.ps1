param(
    [string]$Python = 'python',
    [string]$Compiler = "$PSScriptRoot/installer-tools/inno/ISCC.exe"
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$bootstrapper = Join-Path $PSScriptRoot 'installer-tools/MicrosoftEdgeWebview2Setup.exe'
$signature = Get-AuthenticodeSignature -LiteralPath $bootstrapper
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw 'The WebView2 bootstrapper must have a valid Microsoft signature.'
}
$compilerSignature = Get-AuthenticodeSignature -LiteralPath $Compiler
if ($compilerSignature.Status -ne 'Valid' -or $compilerSignature.SignerCertificate.Subject -notmatch 'Pyrsys') {
    throw 'The Inno Setup compiler must have a valid Pyrsys signature.'
}
Push-Location $taskRoot
try {
    & $Python -m PyInstaller --noconfirm --distpath desktop/installer-bundle-dist --workpath desktop/installer-bundle-build desktop/hub_installer_bundle.spec
    if ($LASTEXITCODE -ne 0) { throw 'Application build failed.' }
    $payload = Join-Path $PSScriptRoot 'installer-bundle-dist/AgentHub'
    [IO.File]::WriteAllText((Join-Path $payload 'installation.json'), '{"main":"AgentMessageHubDesktop.exe"}', [Text.UTF8Encoding]::new($false))
    & $Python -m PyInstaller --noconfirm --distpath desktop/diagnostics-dist --workpath desktop/diagnostics-build desktop/AgentHubDiagnostics.spec
    if ($LASTEXITCODE -ne 0) { throw 'Diagnostic exporter build failed.' }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'diagnostics-dist/AgentHubDiagnostics.exe') -Destination $payload
    & $Compiler '/DPayload=installer-bundle-dist/AgentHub' (Join-Path $PSScriptRoot 'agent_hub_setup.iss')
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
} finally { Pop-Location }
