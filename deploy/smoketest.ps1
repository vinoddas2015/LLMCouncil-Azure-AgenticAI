try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustSmoke2 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint sp, X509Certificate cert, WebRequest req, int prob) { return true; }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustSmoke2
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$base = "https://llmcouncil-backend.azurewebsites.net"

Write-Host "=== GET /health ==="
try {
    $r = Invoke-RestMethod -Uri "$base/health" -TimeoutSec 20
    Write-Host ($r | ConvertTo-Json -Compress)
} catch { Write-Host "Error: $($_.Exception.Message)" }

Write-Host ""
Write-Host "=== GET / ==="
try {
    $r = Invoke-RestMethod -Uri "$base/" -TimeoutSec 20
    Write-Host ($r | ConvertTo-Json -Compress)
} catch { Write-Host "Error: $($_.Exception.Message)" }

Write-Host ""
Write-Host "=== GET /api/models (first 500 chars) ==="
try {
    $r = Invoke-WebRequest -Uri "$base/api/models" -UseBasicParsing -TimeoutSec 20
    Write-Host $r.Content.Substring(0, [Math]::Min(500, $r.Content.Length))
} catch { Write-Host "Error: $($_.Exception.Message)" }

Write-Host ""
Write-Host "=== GET /api/conversations (with user-id header) ==="
try {
    $r = Invoke-RestMethod -Uri "$base/api/conversations" -Headers @{ "user-id" = "test-user" } -TimeoutSec 20
    Write-Host ($r | ConvertTo-Json -Compress)
} catch { Write-Host "Error: $($_.Exception.Message)" }

Write-Host ""
Write-Host "Done."
