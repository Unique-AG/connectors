param($Mode, $Address)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/exchange.ps1"
$alias = ($Address -split '@')[0]
if (-not (Connect-Seed $Mode)) { 'no'; return }
if ($Mode -eq 'apply') {
    if (-not (Get-Mailbox -Identity $alias -ErrorAction SilentlyContinue)) {
        New-Mailbox -Room -Name 'seed-v1 room' -Alias $alias -PrimarySmtpAddress $Address | Out-Null
    }
    Set-Mailbox -Identity $alias -EmailAddressPolicyEnabled $false -PrimarySmtpAddress $Address -HiddenFromAddressListsEnabled $false
    Set-Place -Identity $alias -Capacity 8 -Building 'Lakeside HQ' -Floor 1
    Set-CalendarProcessing -Identity $alias -AutomateProcessing AutoAccept
    return
}
$room = Get-Mailbox -Identity $alias -RecipientTypeDetails RoomMailbox -ErrorAction SilentlyContinue
$place = Get-Place -Identity $alias -ErrorAction SilentlyContinue
$ok = $room -and "$($room.PrimarySmtpAddress)" -eq $Address -and $place.Capacity -eq 8 -and $place.Building -eq 'Lakeside HQ' -and $place.Floor -eq 1
if ($ok -and (Get-CalendarProcessing -Identity $alias).AutomateProcessing -eq 'AutoAccept') { 'yes' } else { 'no' }
