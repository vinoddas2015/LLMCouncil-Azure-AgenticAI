# Fix startup command - prepend $(pwd) to PYTHONPATH so 'backend' is importable

try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllFix9 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) {
        return true;
    }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllFix9
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$token = az account get-access-token --query accessToken -o tsv 2>$null
$subId = "24cbffca-ac7d-4f7f-9da9-88f62339afe9"
$rg = "rg-llmcouncil"
$app = "llmcouncil-backend"

# New startup command: prepend $(pwd) to PYTHONPATH
$newCmd = 'export PYTHONPATH=$(pwd):$PYTHONPATH && gunicorn -w 4 -k uvicorn.workers.UvicornWorker backend.main:app --bind 0.0.0.0:8000 --timeout 120'

$configUri = "https://management.azure.com/subscriptions/$subId/resourceGroups/$rg/providers/Microsoft.Web/sites/$app/config/web?api-version=2023-12-01"
$body = @{
    properties = @{
        appCommandLine = $newCmd
        linuxFxVersion = "PYTHON|3.12"
        alwaysOn       = $true
    }
} | ConvertTo-Json -Depth 3

Write-Output "Updating startup command..."
Write-Output "New command: $newCmd"

$resp = Invoke-RestMethod -Uri $configUri -Method Patch -Headers @{
    Authorization  = "Bearer $token"
    "Content-Type" = "application/json"
} -Body $body
Write-Output "SUCCESS: $($resp.properties.appCommandLine)"

# Restart
Write-Output "Restarting..."
$restartUri = "https://management.azure.com/subscriptions/$subId/resourceGroups/$rg/providers/Microsoft.Web/sites/$app/restart?api-version=2023-12-01"
try {
    Invoke-RestMethod -Uri $restartUri -Method Post -Headers @{
        Authorization  = "Bearer $token"
        "Content-Type" = "application/json"
    }
    Write-Output "Restart triggered."
} catch {
    Write-Output "Restart: $($_.Exception.Message)"
}

Write-Output "Waiting 90 seconds..."
Start-Sleep -Seconds 90

# Health check
Write-Output "Checking /health..."
try {
    $h = Invoke-RestMethod -Uri "https://$app.azurewebsites.net/health" -Method Get -TimeoutSec 30
    Write-Output "HEALTH OK: $h"
} catch {
    $sc = $null
    if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode }
    Write-Output "Health: HTTP $sc - $($_.Exception.Message)"
}

Write-Output "Checking /api/health..."
try {
    $ah = Invoke-RestMethod -Uri "https://$app.azurewebsites.net/api/health" -Method Get -TimeoutSec 30
    Write-Output "API HEALTH: $($ah | ConvertTo-Json -Compress)"
} catch {
    $sc = $null
    if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode }
    Write-Output "API Health: HTTP $sc - $($_.Exception.Message)"
}

Write-Output "Done."
