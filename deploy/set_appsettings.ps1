# Configure App Settings via ARM REST API (PowerShell 5.1 compatible)
# Sets all environment variables for the Web App

param(
    [string]$SubscriptionId = "24cbffca-ac7d-4f7f-9da9-88f62339afe9",
    [string]$ResourceGroup  = "rg-llmcouncil",
    [string]$WebAppName     = "llmcouncil-backend"
)

# --- Bypass SSL certificate validation (PS 5.1 compatible) ---
Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllCertsPolicy2 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) {
        return true;
    }
}
"@
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllCertsPolicy2
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

# --- Get access token ---
Write-Host "Getting access token..."
$token = az account get-access-token --query accessToken -o tsv 2>$null
if (-not $token) { Write-Host "ERROR: Could not get access token."; exit 1 }
Write-Host "Token obtained."

$headers = @{
    Authorization  = "Bearer $token"
    "Content-Type" = "application/json"
}

# --- App Settings (environment variables) ---
$appSettings = @{
    properties = @{
        # Bayer myGenAssist API
        OPENROUTER_API_KEY = "<YOUR_OPENROUTER_API_KEY>"
        OPENROUTER_API_URL = "https://chat.int.bayer.com/api/v2/chat/completions"
        
        # Google AI Studio
        GOOGLE_API_KEY = "<YOUR_GOOGLE_API_KEY>"
        
        # Azure Cosmos DB
        COSMOS_ENDPOINT = "https://llmcouncil-cosmos.documents.azure.com:443/"
        COSMOS_KEY = "<YOUR_COSMOS_KEY>"
        COSMOS_DATABASE = "llm-council"
        COSMOS_CONVERSATIONS_CONTAINER = "conversations"
        COSMOS_MEMORY_CONTAINER = "memory"
        COSMOS_SKILLS_CONTAINER = "skills"
        
        # Azure Blob Storage
        AZURE_STORAGE_CONNECTION_STRING = "<YOUR_AZURE_STORAGE_CONNECTION_STRING>"
        AZURE_BLOB_CONVERSATIONS_CONTAINER = "conversations"
        AZURE_BLOB_ATTACHMENTS_CONTAINER = "attachments"
        AZURE_BLOB_MEMORY_CONTAINER = "memory"
        AZURE_BLOB_SKILLS_CONTAINER = "skills"
        
        # App Service configuration
        WEBSITES_PORT = "8000"
        SCM_DO_BUILD_DURING_DEPLOYMENT = "true"
        WEBSITE_HTTPLOGGING_RETENTION_DAYS = "3"
    }
} | ConvertTo-Json -Depth 3

$uri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/sites/$WebAppName/config/appsettings?api-version=2023-12-01"

Write-Host "Configuring app settings for '$WebAppName'..."

try {
    $response = Invoke-RestMethod -Uri $uri -Method Put -Headers $headers -Body $appSettings
    Write-Host "SUCCESS - App settings configured!" -ForegroundColor Green
    Write-Host "Settings count: $($response.properties.PSObject.Properties.Name.Count)"
    $response.properties.PSObject.Properties.Name | ForEach-Object { Write-Host "  - $_" }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
        Write-Host "Details: $($_.ErrorDetails.Message)"
    }
    exit 1
}
