# Fetch the latest Docker container log (application stdout/stderr)
# Focuses on the MOST RECENT entries only

param(
    [string]$WebAppName = "llmcouncil-backend"
)

try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllLog8 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint sp, X509Certificate cert, WebRequest req, int prob) { return true; }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllLog8
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$token = az account get-access-token --query accessToken -o tsv 2>$null

# List all docker log files
$logUrl = "https://$WebAppName.scm.azurewebsites.net/api/logs/docker"
$logs = Invoke-RestMethod -Uri $logUrl -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30

Write-Host "=== Log files available ==="
foreach ($entry in $logs) {
    Write-Host "  $($entry.name) - $($entry.size) bytes - $($entry.m_time)"
}

# Fetch the actual docker log content and show LAST 80 lines
foreach ($entry in $logs) {
    if ($entry.href -and $entry.size -gt 0) {
        Write-Host ""
        Write-Host "=== $($entry.name) (last 80 lines) ==="
        try {
            $content = Invoke-RestMethod -Uri $entry.href -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 60
            $lines = $content -split "`n"
            $start = [Math]::Max(0, $lines.Count - 80)
            $lines[$start..($lines.Count - 1)] | ForEach-Object { Write-Host $_ }
        } catch {
            Write-Host "Error: $($_.Exception.Message)"
        }
    }
}

Write-Host ""
Write-Host "Done."
