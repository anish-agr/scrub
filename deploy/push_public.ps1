# Copy the public page to the Vultr server and start nginx on port 80.
# Usage: powershell -File deploy/push_public.ps1 -Target root@SERVER_IP [-Domain the-domain.tld -Email you@school.edu]
# The server gets only MONGODB_URI and SCRUB_PUBLIC_URL from .env, and no ledger/buffer.jsonl.
param(
    [Parameter(Mandatory = $true)]
    [string]$Target,
    [string]$Domain = "",
    [string]$Email = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvFile = Join-Path $Root ".env"
if (-not (Test-Path $EnvFile)) {
    throw "missing $EnvFile with MONGODB_URI"
}
$Stage = Join-Path ([System.IO.Path]::GetTempPath()) ("scrub-push-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $Stage | Out-Null
try {
    foreach ($dir in "ledger", "deploy") {
        Copy-Item -Recurse (Join-Path $Root $dir) (Join-Path $Stage $dir)
    }
    Get-ChildItem -Path $Stage -Recurse -Force |
        Where-Object { $_.Name -eq "__pycache__" -or $_.Name -eq "buffer.jsonl" } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    $keep = Get-Content $EnvFile | Where-Object { $_ -match '^(MONGODB_URI|SCRUB_PUBLIC_URL)=' }
    if (-not ($keep | Where-Object { $_ -match '^MONGODB_URI=.+' })) {
        throw "MONGODB_URI is empty in $EnvFile"
    }
    # LF line endings and no BOM, so the server reads it cleanly
    [System.IO.File]::WriteAllText((Join-Path $Stage ".env"), (($keep -join "`n") + "`n"))
    ssh $Target "mkdir -p /opt/scrub"
    scp -r (Join-Path $Stage "ledger") (Join-Path $Stage "deploy") (Join-Path $Stage ".env") "${Target}:/opt/scrub/"
}
finally {
    Remove-Item -Recurse -Force $Stage -ErrorAction SilentlyContinue
}
$setupArgs = ""
if ($Domain -ne "" -and $Email -ne "") { $setupArgs = "$Domain $Email" }
ssh $Target "chmod 600 /opt/scrub/.env && bash /opt/scrub/deploy/setup_public.sh $setupArgs"
Write-Host "open http://$($Target.Split('@')[-1])/"
