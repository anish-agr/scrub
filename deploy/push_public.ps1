# Copy the public page to the Vultr server and start nginx on port 80.
# Usage: powershell -File deploy/push_public.ps1 -Target root@SERVER_IP
param(
    [Parameter(Mandatory = $true)]
    [string]$Target
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not (Test-Path (Join-Path $Root ".env"))) {
    throw "missing $Root\.env with MONGODB_URI"
}
ssh $Target "mkdir -p /opt/scrub/ledger /opt/scrub/deploy"
scp -r "$Root\ledger\*" "${Target}:/opt/scrub/ledger/"
scp -r "$Root\deploy\*" "${Target}:/opt/scrub/deploy/"
scp "$Root\.env" "${Target}:/opt/scrub/.env"
ssh $Target "chmod +x /opt/scrub/deploy/setup_public.sh && bash /opt/scrub/deploy/setup_public.sh"
Write-Host "open http://$($Target.Split('@')[-1])/"
