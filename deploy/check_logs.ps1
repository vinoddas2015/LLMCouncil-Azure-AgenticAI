# Check App Service logs via ARM REST API
try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAll6 : ICertificatePolicy {
    public bool CheckValidationResult(ServicePoint sp, X509Certificate cert, WebRequest req, int prob) { return true; }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAll6
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$token = az account get-access-token --query accessToken -o tsv 2>$null
$webAppName = "llmcouncil-backend"

# Check Kudu deployment logs
Write-Host "=== Deployment Log ==="
try {
    $deployLog = Invoke-RestMethod -Uri "https://$webAppName.scm.azurewebsites.net/api/deployments" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30
    foreach ($d in $deployLog) {
        Write-Host "  ID: $($d.id)  Status: $($d.status)  StatusText: $($d.status_text)  Complete: $($d.complete)  Message: $($d.message)"
    }
    # Get latest deployment log entries
    if ($deployLog.Count -gt 0) {
        $latestId = $deployLog[0].id
        Write-Host ""
        Write-Host "=== Latest Deployment Log Entries ($latestId) ==="
        try {
            $logEntries = Invoke-RestMethod -Uri "https://$webAppName.scm.azurewebsites.net/api/deployments/$latestId/log" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30
            foreach ($e in $logEntries) {
                Write-Host "  [$($e.log_time)] $($e.message)"
                if ($e.details_url) {
                    try {
                        $detail = Invoke-RestMethod -Uri $e.details_url -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 15
                        foreach ($d in $detail) { Write-Host "    $($d.message)" }
                    } catch {}
                }
            }
        } catch { Write-Host "  Could not get log entries: $($_.Exception.Message)" }
    }
} catch { Write-Host "  Error: $($_.Exception.Message)" }

Write-Host ""
Write-Host "=== Docker/Application Log (last 200 lines) ==="
try {
    $logStream = Invoke-RestMethod -Uri "https://$webAppName.scm.azurewebsites.net/api/logs/docker" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30
    foreach ($log in $logStream | Select-Object -Last 5) {
        Write-Host "  Log file: $($log.name) ($($log.size) bytes)"
        if ($log.href) {
            try {
                $content = Invoke-RestMethod -Uri $log.href -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30
                $content -split "`n" | Select-Object -Last 50 | ForEach-Object { Write-Host "    $_" }
            } catch { Write-Host "    Could not read: $($_.Exception.Message)" }
        }
    }
} catch { Write-Host "  Error: $($_.Exception.Message)" }
