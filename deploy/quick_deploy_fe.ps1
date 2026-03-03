# Quick frontend deploy via Kudu ZIP Deploy using TrustAllCertsPolicy
# Creates proper ZIP with forward-slash paths, then POSTs to Kudu

$ErrorActionPreference = "Stop"
$ProjectRoot = "C:\Users\EOVBK\Django\Architect\LLMCouncilMGA-Azure"
$frontendDir = Join-Path $ProjectRoot "frontend"
$WebAppName = "llmcouncil-frontend"

# --- SSL bypass ---
try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllCertsQD : ICertificatePolicy {
    public bool CheckValidationResult(ServicePoint sp, X509Certificate cert, WebRequest req, int prob) { return true; }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllCertsQD
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

# --- Get token ---
Write-Host "Getting Azure token..."
$token = az account get-access-token --query accessToken -o tsv 2>$null
if (-not $token) { Write-Host "ERROR: token failed"; exit 1 }
Write-Host "Token OK (len=$($token.Length))"

# --- Staging ---
$stagingDir = Join-Path $env:TEMP "llmcouncil-fe-qdeploy"
$zipPath = Join-Path $env:TEMP "llmcouncil-fe-qdeploy.zip"
if (Test-Path $stagingDir) { Remove-Item $stagingDir -Recurse -Force }
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
New-Item -ItemType Directory -Path $stagingDir | Out-Null

Copy-Item (Join-Path $frontendDir "server.js") (Join-Path $stagingDir "server.js")
Copy-Item (Join-Path $frontendDir "package.json") (Join-Path $stagingDir "package.json")
Copy-Item (Join-Path $frontendDir "dist") (Join-Path $stagingDir "dist") -Recurse

Write-Host "Installing production deps..."
Push-Location $stagingDir
npm install --omit=dev 2>&1 | Out-Null
Pop-Location
Write-Host "Deps installed: $((Get-ChildItem (Join-Path $stagingDir 'node_modules') -Directory).Count) packages"

# --- Create ZIP with forward slashes ---
Write-Host "Creating ZIP with forward-slash paths..."
Add-Type -AssemblyName System.IO.Compression.FileSystem

$zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
$allFiles = Get-ChildItem $stagingDir -Recurse -File
$count = 0
foreach ($f in $allFiles) {
    $rel = $f.FullName.Substring($stagingDir.Length + 1).Replace('\', '/')
    $entry = $zip.CreateEntry($rel, [System.IO.Compression.CompressionLevel]::Optimal)
    $entryStream = $entry.Open()
    $fileStream = [System.IO.File]::OpenRead($f.FullName)
    $fileStream.CopyTo($entryStream)
    $fileStream.Close()
    $entryStream.Close()
    $count++
}
$zip.Dispose()
$zipSize = [math]::Round((Get-Item $zipPath).Length / 1MB, 2)
Write-Host "ZIP: $zipSize MB ($count files)"

# --- Kudu deploy ---
Write-Host "Deploying to Kudu..."
$kuduUri = "https://$WebAppName.scm.azurewebsites.net/api/zipdeploy?isAsync=true"
$zipBytes = [System.IO.File]::ReadAllBytes($zipPath)

$request = [System.Net.HttpWebRequest]::Create($kuduUri)
$request.Method = "POST"
$request.ContentType = "application/zip"
$request.Headers.Add("Authorization", "Bearer $token")
$request.Timeout = 600000
$request.ContentLength = $zipBytes.Length

$reqStream = $request.GetRequestStream()
$reqStream.Write($zipBytes, 0, $zipBytes.Length)
$reqStream.Close()

$response = $request.GetResponse()
$statusCode = [int]$response.StatusCode
Write-Host "Upload: $statusCode $($response.StatusDescription)"

if ($statusCode -eq 202) {
    $pollUrl = $response.Headers["Location"]
    $response.Close()
    if (-not $pollUrl) { $pollUrl = "https://$WebAppName.scm.azurewebsites.net/api/deployments/latest" }
    Write-Host "Polling..."
    $maxWait = 300; $elapsed = 0; $interval = 15
    while ($elapsed -lt $maxWait) {
        Start-Sleep -Seconds $interval; $elapsed += $interval
        try {
            $pr = [System.Net.HttpWebRequest]::Create($pollUrl)
            $pr.Headers.Add("Authorization", "Bearer $token")
            $pr.Timeout = 30000
            $presp = $pr.GetResponse()
            $rd = New-Object System.IO.StreamReader($presp.GetResponseStream())
            $body = $rd.ReadToEnd(); $presp.Close()
            $ds = ($body | ConvertFrom-Json)
            Write-Host "  [$elapsed s] Status=$($ds.status) Complete=$($ds.complete)"
            if ($ds.complete -eq $true -or $ds.status -eq 4) {
                Write-Host "SUCCESS - Frontend deployed!" -ForegroundColor Green
                break
            }
            if ($ds.status -eq 3) { Write-Host "DEPLOY FAILED" -ForegroundColor Red; exit 1 }
        } catch { Write-Host "  [$elapsed s] Poll error: $($_.Exception.Message)" }
    }
} else {
    $response.Close()
    Write-Host "SUCCESS - Frontend deployed!" -ForegroundColor Green
}

# Cleanup
Remove-Item $stagingDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "URL: https://$WebAppName.azurewebsites.net"
