# After the domain's A record points at the server.
# Usage: powershell -File deploy/enable_https.ps1 -Target root@SERVER_IP -Domain scrub.example -Email you@school.edu
param(
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$Domain,
    [Parameter(Mandatory = $true)][string]$Email
)
$ErrorActionPreference = "Stop"
ssh $Target "bash /opt/scrub/deploy/setup_public.sh $Domain $Email"
Write-Host "open https://$Domain/"
