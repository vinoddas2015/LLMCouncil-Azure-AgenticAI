# Deploy with run_server.py entry point — fixes ModuleNotFoundError
# 'python run_server.py' adds the script's directory to sys.path[0],
# which makes 'import backend' work regardless of Oryx temp directory.

param(
    [string]$SubscriptionId = "24cbffca-ac7d-4f7f-9da9-88f62339afe9",
    [string]$ResourceGroup  = "rg-llmcouncil",
    [string]$WebAppName     = "llmcouncil-backend",
    [string]$ProjectRoot    = "C:\Users\EOVBK\Django\Architect\LLMCouncilMGA-Azure"
)

# --- SSL bypass (PS 5.1) ---
try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllDeploy6 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) { return true; }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllDeploy6
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

# --- Token ---
$token = az account get-access-token --query accessToken -o tsv 2>$null
if (-not $token) { Write-Host "ERROR: No token"; exit 1 }
Write-Host "Token OK"

# --- Build ZIP ---
$zipPath = Join-Path $env:TEMP "llmcouncil-deploy.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
$stagingDir = Join-Path $env:TEMP "llmcouncil-staging"
if (Test-Path $stagingDir) { Remove-Item $stagingDir -Recurse -Force }
New-Item -ItemType Directory -Path $stagingDir | Out-Null

$filesToCopy = @(
    "requirements.txt"
    "run_server.py"
    "backend\__init__.py"
    "backend\main.py"
    "backend\config.py"
    "backend\council.py"
    "backend\openrouter.py"
    "backend\google_provider.py"
    "backend\storage.py"
    "backend\grounding.py"
    "backend\agents.py"
    "backend\memory.py"
    "backend\memory_store.py"
    "backend\skills.py"
    "backend\skills_store.py"
    "backend\infographics.py"
    "backend\model_sync.py"
    "backend\orchestrator.py"
    "backend\prompt_guard.py"
    "backend\reranker.py"
    "backend\resilience.py"
    "backend\security.py"
    "backend\token_tracking.py"
)

foreach ($file in $filesToCopy) {
    $src = Join-Path $ProjectRoot $file
    $dst = Join-Path $stagingDir $file
    $dstDir = Split-Path $dst -Parent
    if (-not (Test-Path $dstDir)) { New-Item -ItemType Directory -Path $dstDir -Force | Out-Null }
    if (Test-Path $src) {
        Copy-Item $src $dst
        Write-Host "  + $file"
    } else {
        Write-Host "  SKIP: $file"
    }
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
# CRITICAL: Use ZipArchive to create entries with forward slashes.
# .NET Framework's CreateFromDirectory uses backslashes on Windows,
# which become literal backslash characters in filenames on Linux.
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, 'Create')
foreach ($file in (Get-ChildItem $stagingDir -Recurse -File)) {
    $relativePath = $file.FullName.Substring($stagingDir.Length + 1).Replace('\', '/')
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $file.FullName, $relativePath) | Out-Null
    Write-Host "  zip: $relativePath"
}
$zip.Dispose()
$zipSize = (Get-Item $zipPath).Length
Write-Host "ZIP: $([math]::Round($zipSize / 1KB, 1)) KB"

# --- Deploy via Kudu ---
Write-Host "Deploying..."
$kuduUri = "https://$WebAppName.scm.azurewebsites.net/api/zipdeploy?isAsync=true"
$zipBytes = [System.IO.File]::ReadAllBytes($zipPath)

try {
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
    Write-Host "Upload: $statusCode"

    if ($statusCode -eq 202) {
        $pollUrl = $response.Headers["Location"]
        $response.Close()
        if (-not $pollUrl) { $pollUrl = "https://$WebAppName.scm.azurewebsites.net/api/deployments/latest" }
        
        $maxWait = 300; $elapsed = 0; $interval = 15
        while ($elapsed -lt $maxWait) {
            Start-Sleep -Seconds $interval; $elapsed += $interval
            try {
                $pollReq = [System.Net.HttpWebRequest]::Create($pollUrl)
                $pollReq.Headers.Add("Authorization", "Bearer $token")
                $pollReq.Timeout = 30000
                $pollResp = $pollReq.GetResponse()
                $reader = New-Object System.IO.StreamReader($pollResp.GetResponseStream())
                $body = $reader.ReadToEnd()
                $pollResp.Close()
                $d = ($body | ConvertFrom-Json)
                Write-Host "  [$elapsed s] Status: $($d.status), Complete: $($d.complete)"
                if ($d.complete -eq $true -or $d.status -eq 4) { Write-Host "Deploy OK"; break }
                if ($d.status -eq 3) { Write-Host "Deploy FAILED"; Write-Host $body; exit 1 }
            } catch { Write-Host "  [$elapsed s] Poll: $($_.Exception.Message)" }
        }
    } else { $response.Close(); Write-Host "Deploy OK" }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    exit 1
}

# --- Set startup command: python run_server.py ---
$startupCmd = "python run_server.py"
Write-Host ""
Write-Host "Setting startup: $startupCmd"

$configUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/sites/$WebAppName/config/web?api-version=2023-12-01"
$configBody = @{
    properties = @{
        appCommandLine = $startupCmd
        linuxFxVersion = "PYTHON|3.12"
        alwaysOn       = $true
    }
} | ConvertTo-Json -Depth 3

try {
    Invoke-RestMethod -Uri $configUri -Method Patch -Headers @{
        Authorization  = "Bearer $token"
        "Content-Type" = "application/json"
    } -Body $configBody | Out-Null
    Write-Host "Startup set: $startupCmd"
} catch {
    Write-Host "WARNING: $($_.Exception.Message)"
}

# --- Restart ---
Write-Host "Restarting app..."
$restartUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/sites/${WebAppName}/restart?api-version=2023-12-01"
try {
    Invoke-RestMethod -Uri $restartUri -Method Post -Headers @{
        Authorization = "Bearer $token"
    }
    Write-Host "Restarted."
} catch { Write-Host "Restart: $($_.Exception.Message)" }

# --- Wait and check health ---
Write-Host "Waiting 120 seconds for container startup..."
Start-Sleep -Seconds 120

Write-Host "Health check..."
try {
    $h = Invoke-WebRequest -Uri "https://$WebAppName.azurewebsites.net/health" -UseBasicParsing -TimeoutSec 30
    Write-Host "Health: HTTP $($h.StatusCode)"
    Write-Host $h.Content
} catch {
    $sc = "unknown"
    if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode }
    Write-Host "Health: HTTP $sc"
}

# --- Fetch logs on failure ---
if ($sc -eq "unknown" -or $sc -eq 503) {
    Write-Host ""
    Write-Host "Fetching Docker logs..."
    $logUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/sites/$WebAppName/config/logs?api-version=2023-12-01"
    # Enable logging first
    $logBody = @{
        properties = @{
            httpLogs = @{
                fileSystem = @{ enabled = $true; retentionInMb = 100; retentionInDays = 3 }
            }
        }
    } | ConvertTo-Json -Depth 5
    try {
        Invoke-RestMethod -Uri $logUri -Method Put -Headers @{
            Authorization  = "Bearer $token"
            "Content-Type" = "application/json"
        } -Body $logBody | Out-Null
    } catch {}

    # Fetch log stream
    foreach ($logType in @("docker", "default")) {
        $logUrl = "https://$WebAppName.scm.azurewebsites.net/api/logs/$logType"
        try {
            $logs = Invoke-RestMethod -Uri $logUrl -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30
            foreach ($entry in $logs) {
                if ($entry.href) {
                    Write-Host ""
                    Write-Host "=== $($entry.href) ($($entry.size) bytes) ==="
                    try {
                        $logContent = Invoke-RestMethod -Uri $entry.href -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30
                        Write-Host $logContent
                    } catch { Write-Host "Could not fetch: $($_.Exception.Message)" }
                }
            }
        } catch { Write-Host "Log fetch ($logType): $($_.Exception.Message)" }
    }
}

# Cleanup
Remove-Item $stagingDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Done."
