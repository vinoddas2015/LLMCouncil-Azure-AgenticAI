# Health check via PowerShell 5.1 (SSL bypass)
try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAll5 : ICertificatePolicy {
    public bool CheckValidationResult(ServicePoint sp, X509Certificate cert, WebRequest req, int prob) { return true; }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAll5
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$base = "https://llmcouncil-backend.azurewebsites.net"

Write-Host "Checking $base/health ..."
try {
    $r = Invoke-RestMethod -Uri "$base/health" -TimeoutSec 60
    Write-Host "HEALTH OK:" -ForegroundColor Green
    $r | ConvertTo-Json -Depth 3
} catch {
    Write-Host "Health error: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.ErrorDetails) { Write-Host $_.ErrorDetails.Message }
}

Write-Host ""
Write-Host "Checking $base/api/health ..."
try {
    $r2 = Invoke-RestMethod -Uri "$base/api/health" -TimeoutSec 60
    Write-Host "API HEALTH OK:" -ForegroundColor Green
    $r2 | ConvertTo-Json -Depth 3
} catch {
    Write-Host "API health error: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.ErrorDetails) { Write-Host $_.ErrorDetails.Message }
}
