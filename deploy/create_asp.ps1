# Create App Service Plan via ARM REST API (PowerShell 5.1 compatible)
# Bypasses Bayer corporate proxy SSL interception

param(
    [string]$SubscriptionId = "24cbffca-ac7d-4f7f-9da9-88f62339afe9",
    [string]$ResourceGroup = "rg-llmcouncil",
    [string]$PlanName = "asp-llmcouncil",
    [string]$Location = "eastus",
    [string]$Sku = "S2",
    [string]$Tier = "Standard"
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

# --- Get access token from Azure CLI (uses cached token) ---
Write-Host "Getting access token..."
$token = az account get-access-token --query accessToken -o tsv 2>$null
if (-not $token) {
    Write-Host "ERROR: Could not get access token. Run 'az login' first."
    exit 1
}
Write-Host "Token obtained (length: $($token.Length))"

# --- Create App Service Plan via ARM REST API ---
$uri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/serverfarms/${PlanName}?api-version=2023-12-01"

$body = @{
    location   = $Location
    kind       = "linux"
    properties = @{
        reserved = $true
    }
    sku = @{
        name     = $Sku
        tier     = $Tier
        capacity = 1
    }
} | ConvertTo-Json -Depth 5

Write-Host "Creating App Service Plan '$PlanName' in '$ResourceGroup' ($Location, $Sku)..."
Write-Host "URI: $uri"

try {
    $response = Invoke-RestMethod -Uri $uri -Method Put -Headers @{
        Authorization  = "Bearer $token"
        "Content-Type" = "application/json"
    } -Body $body
    Write-Host ""
    Write-Host "SUCCESS - App Service Plan created!" -ForegroundColor Green
    $response | ConvertTo-Json -Depth 4
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
        Write-Host "Details: $($_.ErrorDetails.Message)"
    }
    exit 1
}
