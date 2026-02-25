try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustSmoke3 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint sp, X509Certificate cert, WebRequest req, int prob) { return true; }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustSmoke3
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$base = "https://llmcouncil-backend.azurewebsites.net"
$out = ""

$out += "=== GET /health ===`r`n"
try {
    $r = Invoke-RestMethod -Uri "$base/health" -TimeoutSec 30
    $out += ($r | ConvertTo-Json -Compress) + "`r`n"
} catch { $out += "Error: $($_.Exception.Message)`r`n" }

$out += "`r`n=== GET / ===`r`n"
try {
    $r = Invoke-RestMethod -Uri "$base/" -TimeoutSec 30
    $out += ($r | ConvertTo-Json -Compress) + "`r`n"
} catch { $out += "Error: $($_.Exception.Message)`r`n" }

$out += "`r`n=== GET /api/models ===`r`n"
try {
    $r = Invoke-WebRequest -Uri "$base/api/models" -UseBasicParsing -TimeoutSec 30
    $out += $r.Content.Substring(0, [Math]::Min(500, $r.Content.Length)) + "`r`n"
} catch { $out += "Error: $($_.Exception.Message)`r`n" }

$out += "`r`n=== GET /api/conversations ===`r`n"
try {
    $r = Invoke-WebRequest -Uri "$base/api/conversations" -UseBasicParsing -Headers @{ "user-id" = "test-user" } -TimeoutSec 30
    $out += "Status: $($r.StatusCode)`r`n"
    $out += $r.Content.Substring(0, [Math]::Min(500, $r.Content.Length)) + "`r`n"
} catch { $out += "Error: $($_.Exception.Message)`r`n" }

$out += "`r`nDone."
$out | Out-File -FilePath "C:\Users\EOVBK\Django\Architect\LLMCouncilMGA-Azure\deploy\smoketest_result.txt" -Encoding UTF8
Write-Host "Results written to deploy\smoketest_result.txt"
