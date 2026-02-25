# Fix: use 'python -m gunicorn' which adds CWD to sys.path

try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllFix10 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) {
        return true;
    }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllFix10
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$token = az account get-access-token --query accessToken -o tsv 2>$null
$subId = "24cbffca-ac7d-4f7f-9da9-88f62339afe9"
$rg = "rg-llmcouncil"
$app = "llmcouncil-backend"

# The fix: python -m gunicorn adds CWD to sys.path
$newCmd = 'python -m gunicorn backend.main:app -b 0.0.0.0:8000 -w 4 -k uvicorn.workers.UvicornWorker --timeout 120'

$configUri = "https://management.azure.com/subscriptions/$subId/resourceGroups/$rg/providers/Microsoft.Web/sites/$app/config/web?api-version=2023-12-01"
$body = @{
    properties = @{
        appCommandLine = $newCmd
        linuxFxVersion = "PYTHON|3.12"
        alwaysOn       = $true
    }
} | ConvertTo-Json -Depth 3

Write-Output "Setting: $newCmd"
$resp = Invoke-RestMethod -Uri $configUri -Method Patch -Headers @{
    Authorization  = "Bearer $token"
    "Content-Type" = "application/json"
} -Body $body
Write-Output "Confirmed: $($resp.properties.appCommandLine)"

# Restart
$restartUri = "https://management.azure.com/subscriptions/$subId/resourceGroups/$rg/providers/Microsoft.Web/sites/$app/restart?api-version=2023-12-01"
try {
    Invoke-RestMethod -Uri $restartUri -Method Post -Headers @{
        Authorization  = "Bearer $token"
        "Content-Type" = "application/json"
    }
    Write-Output "Restarted."
} catch {
    Write-Output "Restart: $($_.Exception.Message)"
}

# Wait 120s for container startup (cert updates take ~15s + oryx extract + pip)
Write-Output "Waiting 120 seconds..."
Start-Sleep -Seconds 120

# Health check
Write-Output "Checking health..."
try {
    $h = Invoke-RestMethod -Uri "https://$app.azurewebsites.net/health" -Method Get -TimeoutSec 30
    Write-Output "HEALTH OK: $h"
} catch {
    $sc = $null
    if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode }
    Write-Output "Health: HTTP $sc"
}

try {
    $ah = Invoke-RestMethod -Uri "https://$app.azurewebsites.net/api/health" -Method Get -TimeoutSec 30
    Write-Output "API: $($ah | ConvertTo-Json -Compress)"
} catch {
    $sc = $null
    if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode }
    Write-Output "API: HTTP $sc"
    
    # Fetch logs on failure
    Write-Output ""
    Write-Output "Fetching logs..."
    $logsUrl = "https://$app.scm.azurewebsites.net/api/logs/docker"
    $logsResp = Invoke-RestMethod -Uri $logsUrl -Headers @{ Authorization = "Bearer $token" }
    $latest = $logsResp | Sort-Object -Property last_updated -Descending | Select-Object -First 2
    foreach ($log in $latest) {
        Write-Output "=== $($log.name) ($($log.size) bytes) ==="
        try {
            $content = Invoke-RestMethod -Uri $log.href -Headers @{ Authorization = "Bearer $token" }
            $lines = $content -split "`n"
            $start = [Math]::Max(0, $lines.Count - 25)
            $lines[$start..($lines.Count-1)] | ForEach-Object { Write-Output $_ }
        } catch {}
    }
}

Write-Output "Done."
