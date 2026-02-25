# Health check with wait - check multiple times

try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllHC4 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) {
        return true;
    }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllHC4
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$app = "llmcouncil-backend"

Write-Output "Waiting 90 seconds for container cold start..."
Start-Sleep -Seconds 90

# Try health check up to 3 times with 30s gap
for ($i = 1; $i -le 3; $i++) {
    Write-Output ""
    Write-Output "=== Attempt $i ==="
    try {
        $resp = Invoke-RestMethod -Uri "https://$app.azurewebsites.net/health" -Method Get -TimeoutSec 30
        Write-Output "HEALTH OK: $resp"
        
        $apiResp = Invoke-RestMethod -Uri "https://$app.azurewebsites.net/api/health" -Method Get -TimeoutSec 30
        Write-Output "API HEALTH: $($apiResp | ConvertTo-Json -Compress)"
        Write-Output "SUCCESS!"
        exit 0
    } catch {
        $sc = $null
        if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode }
        Write-Output "HTTP $sc - $($_.Exception.Message)"
        if ($i -lt 3) {
            Write-Output "  Waiting 30s before retry..."
            Start-Sleep -Seconds 30
        }
    }
}

Write-Output ""
Write-Output "All attempts failed. Checking logs..."

# Quick log check
$token = az account get-access-token --query accessToken -o tsv 2>$null
$logsUrl = "https://$app.scm.azurewebsites.net/api/logs/docker"
$logsResp = Invoke-RestMethod -Uri $logsUrl -Headers @{ Authorization = "Bearer $token" }
$appLogs = $logsResp | Sort-Object -Property last_updated -Descending
foreach ($log in ($appLogs | Select-Object -First 2)) {
    Write-Output ""
    Write-Output "=== $($log.name) ($($log.size) bytes) ==="
    try {
        $content = Invoke-RestMethod -Uri $log.href -Headers @{ Authorization = "Bearer $token" }
        $lines = $content -split "`n"
        $start = [Math]::Max(0, $lines.Count - 30)
        $lines[$start..($lines.Count-1)] | ForEach-Object { Write-Output $_ }
    } catch {
        Write-Output "  Error: $($_.Exception.Message)"
    }
}
