# Enable application logging, restart, and fetch ACTUAL container stdout/stderr

param(
    [string]$SubscriptionId = "24cbffca-ac7d-4f7f-9da9-88f62339afe9",
    [string]$ResourceGroup  = "rg-llmcouncil",
    [string]$WebAppName     = "llmcouncil-backend"
)

try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllDiag7 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint sp, X509Certificate cert, WebRequest req, int prob) { return true; }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllDiag7
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$token = az account get-access-token --query accessToken -o tsv 2>$null
$headers = @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" }

# 1. Enable application logging (both file system and HTTP)
Write-Host "=== Enabling application logging ==="
$logUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/sites/$WebAppName/config/logs?api-version=2023-12-01"
$logBody = @{
    properties = @{
        applicationLogs = @{
            fileSystem = @{ level = "Information" }
        }
        httpLogs = @{
            fileSystem = @{ enabled = $true; retentionInMb = 100; retentionInDays = 3 }
        }
        detailedErrorMessages = @{ enabled = $true }
        failedRequestsTracing = @{ enabled = $true }
    }
} | ConvertTo-Json -Depth 5

try {
    Invoke-RestMethod -Uri $logUri -Method Put -Headers $headers -Body $logBody | Out-Null
    Write-Host "Logging enabled."
} catch {
    Write-Host "Log enable error: $($_.Exception.Message)"
}

# 2. Verify current startup command
Write-Host ""
Write-Host "=== Current config ==="
$configUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/sites/$WebAppName/config/web?api-version=2023-12-01"
try {
    $config = Invoke-RestMethod -Uri $configUri -Headers @{ Authorization = "Bearer $token" }
    Write-Host "appCommandLine: $($config.properties.appCommandLine)"
    Write-Host "linuxFxVersion: $($config.properties.linuxFxVersion)"
} catch { Write-Host "Config error: $($_.Exception.Message)" }

# 3. Restart the app
Write-Host ""
Write-Host "=== Restarting ==="
$restartUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/sites/$WebAppName/restart?api-version=2023-12-01"
try {
    Invoke-RestMethod -Uri $restartUri -Method Post -Headers @{ Authorization = "Bearer $token" }
    Write-Host "Restarted."
} catch { Write-Host "Restart: $($_.Exception.Message)" }

# 4. Wait for container startup
Write-Host "Waiting 90 seconds..."
Start-Sleep -Seconds 90

# 5. Health check
Write-Host ""
Write-Host "=== Health Check ==="
try {
    $h = Invoke-WebRequest -Uri "https://$WebAppName.azurewebsites.net/health" -UseBasicParsing -TimeoutSec 30
    Write-Host "Health: HTTP $($h.StatusCode) - $($h.Content)"
} catch {
    $sc = "timeout"
    if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode }
    Write-Host "Health: HTTP $sc"
}

# 6. Fetch ALL log types
Write-Host ""
Write-Host "=== Fetching logs ==="

# Docker logs
foreach ($logType in @("docker")) {
    $logUrl = "https://$WebAppName.scm.azurewebsites.net/api/logs/$logType"
    try {
        $logs = Invoke-RestMethod -Uri $logUrl -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30
        foreach ($entry in $logs) {
            if ($entry.href -and $entry.size -gt 0) {
                Write-Host ""
                Write-Host "--- $($entry.name) ($($entry.size) bytes) ---"
                try {
                    $logContent = Invoke-RestMethod -Uri $entry.href -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 60
                    # Show last 200 lines (most recent)
                    $lines = $logContent -split "`n"
                    $start = [Math]::Max(0, $lines.Count - 200)
                    $lines[$start..($lines.Count - 1)] | ForEach-Object { Write-Host $_ }
                } catch { Write-Host "Fetch error: $($_.Exception.Message)" }
            }
        }
    } catch { Write-Host "Log list ($logType): $($_.Exception.Message)" }
}

# Also try to get the log stream directly via Kudu
Write-Host ""
Write-Host "=== Recent log stream (last 5000 chars) ==="
$logStreamUrl = "https://$WebAppName.scm.azurewebsites.net/api/logstream/application"
try {
    $req = [System.Net.HttpWebRequest]::Create($logStreamUrl)
    $req.Headers.Add("Authorization", "Bearer $token")
    $req.Timeout = 10000
    $resp = $req.GetResponse()
    $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
    $buf = ""
    $startTime = [DateTime]::Now
    while (([DateTime]::Now - $startTime).TotalSeconds -lt 8) {
        if ($reader.Peek() -ge 0) {
            $buf += $reader.ReadLine() + "`n"
        } else {
            Start-Sleep -Milliseconds 200
        }
    }
    $resp.Close()
    if ($buf) { Write-Host $buf } else { Write-Host "(no log stream data within 8 seconds)" }
} catch { Write-Host "Log stream: $($_.Exception.Message)" }

# Also check VFS for any log files
Write-Host ""
Write-Host "=== VFS Log Files ==="
$vfsUrl = "https://$WebAppName.scm.azurewebsites.net/api/vfs/LogFiles/"
try {
    $files = Invoke-RestMethod -Uri $vfsUrl -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 20
    foreach ($f in $files) {
        if ($f.name -match "docker|default|error|app" -and $f.size -gt 0) {
            Write-Host ""
            Write-Host "--- $($f.name) ($($f.size) bytes) ---"
            try {
                $content = Invoke-RestMethod -Uri $f.href -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30
                # Show last 100 lines
                $clines = $content -split "`n"
                $s = [Math]::Max(0, $clines.Count - 100)
                $clines[$s..($clines.Count - 1)] | ForEach-Object { Write-Host $_ }
            } catch { Write-Host "Read error: $($_.Exception.Message)" }
        }
    }
} catch { Write-Host "VFS: $($_.Exception.Message)" }

Write-Host ""
Write-Host "Done."
