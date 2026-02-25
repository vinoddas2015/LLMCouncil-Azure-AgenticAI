# Quick log check - fetch last 40 lines of recent Docker app log

try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllQL : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) {
        return true;
    }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllQL
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$token = az account get-access-token --query accessToken -o tsv 2>$null
$app = "llmcouncil-backend"

$logsUrl = "https://$app.scm.azurewebsites.net/api/logs/docker"
$logsResp = Invoke-RestMethod -Uri $logsUrl -Headers @{ Authorization = "Bearer $token" }

# Get the two biggest recent logs (platform log + app log)
$sorted = $logsResp | Sort-Object -Property last_updated -Descending | Select-Object -First 3

foreach ($log in $sorted) {
    Write-Output "=== $($log.name) ($($log.size) bytes, updated: $($log.last_updated)) ==="
    try {
        $content = Invoke-RestMethod -Uri $log.href -Headers @{ Authorization = "Bearer $token" }
        $lines = $content -split "`n"
        $start = [Math]::Max(0, $lines.Count - 40)
        $lines[$start..($lines.Count-1)] | ForEach-Object { Write-Output $_ }
    } catch {
        Write-Output "  Error fetching: $($_.Exception.Message)"
    }
    Write-Output ""
}
