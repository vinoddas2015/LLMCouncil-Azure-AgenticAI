# Fetch Docker container logs for diagnosis
# Uses TrustAllCertsPolicy to bypass Bayer proxy SSL issues

# --- Bypass SSL ---
try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllLogCheck : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) {
        return true;
    }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllLogCheck
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$token = az account get-access-token --query accessToken -o tsv 2>$null
$app = "llmcouncil-backend"

Write-Output "=== Fetching Docker logs ==="

# Get Docker/App logs
$logsUrl = "https://$app.scm.azurewebsites.net/api/logs/docker"
$logsResp = Invoke-RestMethod -Uri $logsUrl -Headers @{ Authorization = "Bearer $token" }

# Get the 2 most recent log files
$latest = $logsResp | Sort-Object -Property last_updated -Descending | Select-Object -First 2
foreach ($log in $latest) {
    Write-Output "=== Log: $($log.name) ($($log.size) bytes) ==="
    $href = $log.href
    try {
        $content = Invoke-RestMethod -Uri $href -Headers @{ Authorization = "Bearer $token" }
        # Get last 100 lines
        $lines = $content -split "`n"
        $start = [Math]::Max(0, $lines.Count - 100)
        $lines[$start..($lines.Count-1)] | ForEach-Object { Write-Output $_ }
    } catch {
        Write-Output "Could not fetch: $($_.Exception.Message)"
    }
    Write-Output ""
}

Write-Output "=== Current Startup Command ==="
$subId = "24cbffca-ac7d-4f7f-9da9-88f62339afe9"
$rg = "rg-llmcouncil"
$configUri = "https://management.azure.com/subscriptions/$subId/resourceGroups/$rg/providers/Microsoft.Web/sites/$app/config/web?api-version=2023-12-01"
$config = Invoke-RestMethod -Uri $configUri -Method Get -Headers @{
    Authorization = "Bearer $token"
}
Write-Output "appCommandLine: $($config.properties.appCommandLine)"
Write-Output "linuxFxVersion: $($config.properties.linuxFxVersion)"

Write-Output ""
Write-Output "Done."
