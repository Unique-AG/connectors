param($Mode, $Address, $User)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/exchange.ps1"
$alias = ($Address -split '@')[0]
if (-not (Connect-Seed $Mode)) { 'no'; return }
$full = { Get-MailboxPermission -Identity $alias -User $User | Where-Object { $_.AccessRights -contains 'FullAccess' -and -not $_.Deny } }
$send = { Get-RecipientPermission -Identity $alias -Trustee $User | Where-Object { $_.AccessRights -contains 'SendAs' } }
if ($Mode -eq 'apply') {
    if (-not (Get-Mailbox -Identity $alias -ErrorAction SilentlyContinue)) {
        New-Mailbox -Shared -Name 'seed-v1 shared' -Alias $alias -PrimarySmtpAddress $Address | Out-Null
    }
    if (-not (& $full)) { Add-MailboxPermission -Identity $alias -User $User -AccessRights FullAccess -AutoMapping $false | Out-Null }
    if (-not (& $send)) { Add-RecipientPermission -Identity $alias -Trustee $User -AccessRights SendAs -Confirm:$false | Out-Null }
    return
}
$shared = Get-Mailbox -Identity $alias -RecipientTypeDetails SharedMailbox -ErrorAction SilentlyContinue
if ($shared -and "$($shared.PrimarySmtpAddress)" -eq $Address -and (& $full) -and (& $send)) { 'yes' } else { 'no' }
