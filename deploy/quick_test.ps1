# Minimal test to verify basic connectivity
$baseUrl = "https://llmcouncil-backend.azurewebsites.net"
$outFile = "C:\Users\EOVBK\Django\Architect\LLMCouncilMGA-Azure\deploy\quick_test.txt"

try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustQuick1 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) { return true; }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustQuick1
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$out = @()
$out += "=== Quick Connectivity Test ==="
$out += "Time: $(Get-Date)"

# Test 1: Health
try {
    $h = Invoke-WebRequest -Uri "$baseUrl/health" -UseBasicParsing -TimeoutSec 30
    $out += "Health: HTTP $($h.StatusCode) - $($h.Content)"
} catch {
    $out += "Health: FAILED - $($_.Exception.Message)"
}

# Test 2: Create conversation
try {
    $c = Invoke-WebRequest -Uri "$baseUrl/api/conversations" -Method POST -UseBasicParsing -TimeoutSec 30 -Headers @{ "Content-Type"="application/json"; "user-id"="test-quick" } -Body "{}"
    $out += "Create: HTTP $($c.StatusCode) - $($c.Content)"
    $convData = $c.Content | ConvertFrom-Json
    $convId = $convData.id
    $out += "Conv ID: $convId"
} catch {
    $sc = 0; if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode }
    $out += "Create: FAILED HTTP $sc - $($_.Exception.Message)"
    $convId = $null
}

# Test 3: Get conversation
if ($convId) {
    try {
        $g = Invoke-WebRequest -Uri "$baseUrl/api/conversations/$convId" -UseBasicParsing -TimeoutSec 30 -Headers @{ "user-id"="test-quick" }
        $out += "Get: HTTP $($g.StatusCode) - $($g.Content)"
    } catch {
        $sc = 0; if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode }
        $out += "Get: FAILED HTTP $sc"
    }
}

# Test 4: List conversations
try {
    $l = Invoke-WebRequest -Uri "$baseUrl/api/conversations" -UseBasicParsing -TimeoutSec 30 -Headers @{ "user-id"="test-quick" }
    $lData = $l.Content | ConvertFrom-Json
    $out += "List: HTTP $($l.StatusCode) - $($lData.Count) conversations"
} catch {
    $out += "List: FAILED"
}

# Test 5: Delete conversation
if ($convId) {
    try {
        $d = Invoke-WebRequest -Uri "$baseUrl/api/conversations/$convId" -Method DELETE -UseBasicParsing -TimeoutSec 30 -Headers @{ "user-id"="test-quick" }
        $out += "Delete: HTTP $($d.StatusCode)"
    } catch {
        $sc = 0; if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode }
        $out += "Delete: FAILED HTTP $sc"
    }
}

# Test 6: Verify deletion
if ($convId) {
    try {
        $v = Invoke-WebRequest -Uri "$baseUrl/api/conversations/$convId" -UseBasicParsing -TimeoutSec 30 -Headers @{ "user-id"="test-quick" }
        $out += "Verify-Delete: FAILED - got HTTP $($v.StatusCode) instead of 404"
    } catch {
        $sc = 0; if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode }
        $out += "Verify-Delete: HTTP $sc (expected 404)"
    }
}

# Test 7: Memory stats
try {
    $m = Invoke-WebRequest -Uri "$baseUrl/api/memory/stats" -UseBasicParsing -TimeoutSec 30
    $out += "Memory-Stats: HTTP $($m.StatusCode) - $($m.Content)"
} catch {
    $sc = 0; if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode }
    $out += "Memory-Stats: FAILED HTTP $sc"
}

$out += ""
$out += "=== Done ==="

$out -join "`n" | Set-Content $outFile -Encoding ASCII
Write-Host "Results written to $outFile"
