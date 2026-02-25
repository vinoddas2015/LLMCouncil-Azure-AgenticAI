# Fix startup command - add cd /home/site/wwwroot before gunicorn
# Uses TrustAllCertsPolicy to bypass Bayer proxy SSL issues

param(
    [string]$SubscriptionId = "24cbffca-ac7d-4f7f-9da9-88f62339afe9",
    [string]$ResourceGroup  = "rg-llmcouncil",
    [string]$WebAppName     = "llmcouncil-backend"
)

# --- Bypass SSL ---
try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllFix7 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) {
        return true;
    }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllFix7
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

# --- Get access token ---
$token = az account get-access-token --query accessToken -o tsv 2>$null
if (-not $token) {
    Write-Output "ERROR: Could not get access token."
    exit 1
}
Write-Output "Token obtained (length: $($token.Length))"

# --- Update startup command ---
$configUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/sites/$WebAppName/config/web?api-version=2023-12-01"
$newCmd = "cd /home/site/wwwroot && gunicorn -w 4 -k uvicorn.workers.UvicornWorker backend.main:app --bind 0.0.0.0:8000 --timeout 120"

$body = @{
    properties = @{
        appCommandLine = $newCmd
        linuxFxVersion = "PYTHON|3.12"
        alwaysOn       = $true
    }
} | ConvertTo-Json -Depth 3

Write-Output "Updating startup command..."
try {
    $resp = Invoke-RestMethod -Uri $configUri -Method Patch -Headers @{
        Authorization  = "Bearer $token"
        "Content-Type" = "application/json"
    } -Body $body
    Write-Output "SUCCESS: appCommandLine = $($resp.properties.appCommandLine)"
} catch {
    Write-Output "ERROR updating config: $($_.Exception.Message)"
    exit 1
}

# --- Restart the app ---
Write-Output ""
Write-Output "Restarting web app..."
$restartUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/sites/$WebAppName/restart?api-version=2023-12-01"
try {
    Invoke-RestMethod -Uri $restartUri -Method Post -Headers @{
        Authorization  = "Bearer $token"
        "Content-Type" = "application/json"
    }
    Write-Output "Restart triggered successfully."
} catch {
    Write-Output "Restart note: $($_.Exception.Message)"
}

Write-Output ""
Write-Output "Waiting 90 seconds for container cold start..."
Start-Sleep -Seconds 90

# --- Health check ---
Write-Output "Checking health..."
try {
    $health = Invoke-RestMethod -Uri "https://$WebAppName.azurewebsites.net/health" -Method Get -TimeoutSec 30
    Write-Output "HEALTH OK: $health"
} catch {
    $statusCode = $null
    if ($_.Exception.Response) {
        $statusCode = [int]$_.Exception.Response.StatusCode
    }
    Write-Output "Health check result: HTTP $statusCode - $($_.Exception.Message)"
}

try {
    $apiHealth = Invoke-RestMethod -Uri "https://$WebAppName.azurewebsites.net/api/health" -Method Get -TimeoutSec 30
    Write-Output "API HEALTH OK: $($apiHealth | ConvertTo-Json -Compress)"
} catch {
    $statusCode = $null
    if ($_.Exception.Response) {
        $statusCode = [int]$_.Exception.Response.StatusCode
    }
    Write-Output "API health check result: HTTP $statusCode - $($_.Exception.Message)"
}

Write-Output ""
Write-Output "Done."
