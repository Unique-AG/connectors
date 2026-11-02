param($Mode, $Users)
$ErrorActionPreference = 'Stop'
$policy = 'seed-v1 recording'
$names = $Users -split ','
if (-not (Get-Module -ListAvailable MicrosoftTeams)) {
    if ($Mode -eq 'check') { 'no'; return }
    Install-Module MicrosoftTeams -Scope CurrentUser -Force
}
Import-Module MicrosoftTeams
Connect-MicrosoftTeams -UseDeviceAuthentication | Out-Null
if ($Mode -eq 'apply') {
    $flags = @{ AllowCloudRecording = $true; AllowTranscription = $true }
    if (Get-CsTeamsMeetingPolicy -Identity $policy -ErrorAction SilentlyContinue) {
        Set-CsTeamsMeetingPolicy -Identity $policy @flags
    } else {
        New-CsTeamsMeetingPolicy -Identity $policy @flags
    }
    foreach ($name in $names) { Grant-CsTeamsMeetingPolicy -Identity $name -PolicyName $policy }
    return
}
$current = Get-CsTeamsMeetingPolicy -Identity $policy -ErrorAction SilentlyContinue
$ok = $current -and $current.AllowCloudRecording -and $current.AllowTranscription
foreach ($name in $names) {
    if ("$((Get-CsOnlineUser -Identity $name).TeamsMeetingPolicy)" -ne $policy) { $ok = $false }
}
if ($ok) { 'yes' } else { 'no' }
