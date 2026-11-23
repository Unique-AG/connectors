function Connect-Seed($Mode) {
    if (-not (Get-Module -ListAvailable ExchangeOnlineManagement)) {
        if ($Mode -eq 'check') { return $false }
        Install-Module ExchangeOnlineManagement -Scope CurrentUser -Force
    }
    Import-Module ExchangeOnlineManagement | Out-Null
    Connect-ExchangeOnline -Device -ShowBanner:$false | Out-Null
    return $true
}
