# Create deployment ZIP with forward-slash paths and deploy via Kudu
param([string]$Token)

$ErrorActionPreference = "Stop"
$staging = "$env:TEMP\llmcouncil-frontend-staging"
$zipPath = "$env:TEMP\llmcouncil-fe-final.zip"
$WebAppName = "llmcouncil-frontend"

if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

# Create ZIP
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
$files = Get-ChildItem $staging -Recurse -File
foreach ($f in $files) {
    $rel = $f.FullName.Substring($staging.Length + 1).Replace('\', '/')
    $entry = $zip.CreateEntry($rel, [System.IO.Compression.CompressionLevel]::Optimal)
    $es = $entry.Open()
    $fs = [System.IO.File]::OpenRead($f.FullName)
    $fs.CopyTo($es)
    $fs.Close()
    $es.Close()
}
$zip.Dispose()
Write-Host "ZIP: $([math]::Round((Get-Item $zipPath).Length/1MB,2)) MB ($($files.Count) files)"

# SSL bypass
$csCode = 'using System.Net; using System.Security.Cryptography.X509Certificates; public class TrustAll99 : ICertificatePolicy { public bool CheckValidationResult(ServicePoint s, X509Certificate c, WebRequest r, int p) { return true; } }'
try { Add-Type -TypeDefinition $csCode } catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAll99
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

# Upload
Write-Host "Uploading to Kudu..."
$uri = "https://$WebAppName.scm.azurewebsites.net/api/zipdeploy?isAsync=true"
$bytes = [System.IO.File]::ReadAllBytes($zipPath)
$req = [System.Net.HttpWebRequest]::Create($uri)
$req.Method = "POST"
$req.ContentType = "application/zip"
$req.Headers.Add("Authorization", "Bearer $Token")
$req.Timeout = 600000
$req.ContentLength = $bytes.Length
$rs = $req.GetRequestStream()
$rs.Write($bytes, 0, $bytes.Length)
$rs.Close()
$resp = $req.GetResponse()
$code = [int]$resp.StatusCode
Write-Host "Response: $code $($resp.StatusDescription)"

if ($code -eq 202) {
    $poll = $resp.Headers["Location"]
    $resp.Close()
    if (-not $poll) { $poll = "https://$WebAppName.scm.azurewebsites.net/api/deployments/latest" }
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 15
        try {
            $pr = [System.Net.HttpWebRequest]::Create($poll)
            $pr.Headers.Add("Authorization", "Bearer $Token")
            $pr.Timeout = 30000
            $prs = $pr.GetResponse()
            $sr = New-Object System.IO.StreamReader($prs.GetResponseStream())
            $body = $sr.ReadToEnd(); $prs.Close()
            $d = $body | ConvertFrom-Json
            Write-Host "  [$([int](($i+1)*15))s] status=$($d.status) complete=$($d.complete)"
            if ($d.complete -eq $true -or $d.status -eq 4) { Write-Host "DEPLOYED OK"; break }
            if ($d.status -eq 3) { Write-Host "FAILED"; exit 1 }
        } catch { Write-Host "  poll error: $_" }
    }
} else {
    $resp.Close()
    Write-Host "DEPLOYED OK"
}
