param($Mode, $Address)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/exchange.ps1"
$alias = ($Address -split '@')[0]
if (-not (Connect-Seed $Mode)) { 'no'; return }
if ($Mode -eq 'apply') {
    if (-not (Get-Mailbox -Identity $alias -ErrorAction SilentlyContinue)) {
        New-Mailbox -Room -Name 'seed-v1 room' -Alias $alias -PrimarySmtpAddress $Address | Out-Null
    }
    Set-Mailbox -Identity $alias -HiddenFromAddressListsEnabled $false -ResourceCapacity 8
    Set-CalendarProcessing -Identity $alias -AutomateProcessing AutoAccept
    return
}
$room = Get-Mailbox -Identity $alias -RecipientTypeDetails RoomMailbox -ErrorAction SilentlyContinue
$ok = $room -and "$($room.PrimarySmtpAddress)" -eq $Address -and $room.ResourceCapacity -eq 8
if ($ok -and (Get-CalendarProcessing -Identity $alias).AutomateProcessing -eq 'AutoAccept') { 'yes' } else { 'no' }
