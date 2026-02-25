# Create Web App via ARM REST API (PowerShell 5.1 compatible)
# Bypasses Bayer corporate proxy SSL interception

param(
    [string]$SubscriptionId = "24cbffca-ac7d-4f7f-9da9-88f62339afe9",
    [string]$ResourceGroup  = "rg-llmcouncil",
    [string]$WebAppName     = "llmcouncil-backend",
    [string]$PlanName       = "asp-llmcouncil",
    [string]$Location       = "eastus",
    [string]$PythonVersion  = "3.12"
)

# --- Bypass SSL certificate validation (PS 5.1 compatible) ---
Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllCertsPolicy : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) {
        return true;
    }
}
"@
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllCertsPolicy
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

# --- Get access token ---
Write-Host "Getting access token..."
$token = az account get-access-token --query accessToken -o tsv 2>$null
if (-not $token) {
    Write-Host "ERROR: Could not get access token."
    exit 1
}
Write-Host "Token obtained (length: $($token.Length))"

$planId = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/serverfarms/$PlanName"

# --- Create Web App ---
$uri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/sites/${WebAppName}?api-version=2023-12-01"

$body = @{
    location   = $Location
    kind       = "app,linux"
    properties = @{
        serverFarmId = $planId
        reserved     = $true
        siteConfig   = @{
            linuxFxVersion  = "PYTHON|$PythonVersion"
            appCommandLine  = "gunicorn -w 4 -k uvicorn.workers.UvicornWorker backend.main:app --bind 0.0.0.0:8000"
            alwaysOn        = $true
            http20Enabled   = $true
            ftpsState       = "Disabled"
            appSettings     = @(
                @{ name = "WEBSITES_PORT"; value = "8000" }
                @{ name = "SCM_DO_BUILD_DURING_DEPLOYMENT"; value = "true" }
            )
        }
        httpsOnly = $true
    }
} | ConvertTo-Json -Depth 6

Write-Host "Creating Web App '$WebAppName' on plan '$PlanName'..."
Write-Host "URI: $uri"

try {
    $response = Invoke-RestMethod -Uri $uri -Method Put -Headers @{
        Authorization  = "Bearer $token"
        "Content-Type" = "application/json"
    } -Body $body
    Write-Host ""
    Write-Host "SUCCESS - Web App created!" -ForegroundColor Green
    Write-Host "URL: https://$WebAppName.azurewebsites.net"
    $response | ConvertTo-Json -Depth 4
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
        Write-Host "Details: $($_.ErrorDetails.Message)"
    }
    exit 1
}
