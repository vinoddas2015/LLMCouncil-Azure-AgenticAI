# Deploy backend code via Kudu ZIP Deploy API (PowerShell 5.1 compatible)
# Uses TrustAllCertsPolicy to accept the corporate proxy self-signed certificate

param(
    [string]$SubscriptionId = "24cbffca-ac7d-4f7f-9da9-88f62339afe9",
    [string]$ResourceGroup  = "rg-llmcouncil",
    [string]$WebAppName     = "llmcouncil-backend",
    [string]$ProjectRoot    = "C:\Users\EOVBK\Django\Architect\LLMCouncilMGA-Azure"
)

# --- Bypass SSL certificate validation (PS 5.1) ---
try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllCertsPolicy3 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) {
        return true;
    }
}
"@
} catch {}  # Ignore if already defined
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllCertsPolicy3
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

# --- Get access token ---
Write-Host "Getting access token..."
$token = az account get-access-token --query accessToken -o tsv 2>$null
if (-not $token) { Write-Host "ERROR: Could not get access token."; exit 1 }
Write-Host "Token obtained."

# --- Build deployment ZIP ---
$zipPath = Join-Path $env:TEMP "llmcouncil-deploy.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

Write-Host "Building deployment package..."

# Create a staging directory
$stagingDir = Join-Path $env:TEMP "llmcouncil-staging"
if (Test-Path $stagingDir) { Remove-Item $stagingDir -Recurse -Force }
New-Item -ItemType Directory -Path $stagingDir | Out-Null

# Copy required files
$filesToCopy = @(
    "requirements.txt"
    "gunicorn.conf.py"
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
    "backend\auth.py"
    "backend\health_probe.py"
    "run_server.py"
    "startup.sh"
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
        Write-Host "  SKIP (not found): $file"
    }
}

# Create startup.txt for the startup command
$startupCmd = "python run_server.py"
$startupCmd | Out-File -FilePath (Join-Path $stagingDir "startup.txt") -Encoding ascii -NoNewline

# Create ZIP with FORWARD SLASHES (critical: Linux App Service treats backslashes as literal filename chars)
Write-Host "Compressing to $zipPath ..."
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
$stagingDirFull = (Resolve-Path $stagingDir).Path.TrimEnd('\') + '\'
Get-ChildItem -Path $stagingDir -Recurse -File | ForEach-Object {
    $relativePath = $_.FullName.Substring($stagingDirFull.Length).Replace('\', '/')
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, $relativePath) | Out-Null
    Write-Host "  zip: $relativePath"
}
$zip.Dispose()
$zipSize = (Get-Item $zipPath).Length
Write-Host "ZIP created: $([math]::Round($zipSize / 1KB, 1)) KB"

# --- Deploy via Kudu ZIP Deploy (async) ---
Write-Host ""
Write-Host "Deploying to https://$WebAppName.scm.azurewebsites.net ..."

$kuduUri = "https://$WebAppName.scm.azurewebsites.net/api/zipdeploy?isAsync=true"
$zipBytes = [System.IO.File]::ReadAllBytes($zipPath)

try {
    # Use HttpWebRequest for timeout control
    $request = [System.Net.HttpWebRequest]::Create($kuduUri)
    $request.Method = "POST"
    $request.ContentType = "application/zip"
    $request.Headers.Add("Authorization", "Bearer $token")
    $request.Timeout = 600000  # 10 minutes
    $request.ContentLength = $zipBytes.Length

    $reqStream = $request.GetRequestStream()
    $reqStream.Write($zipBytes, 0, $zipBytes.Length)
    $reqStream.Close()

    $response = $request.GetResponse()
    $statusCode = [int]$response.StatusCode
    Write-Host "Upload response: $statusCode $($response.StatusDescription)"

    # For async deploy (202), poll the status
    if ($statusCode -eq 202) {
        $pollUrl = $response.Headers["Location"]
        $response.Close()
        Write-Host "Async deploy started. Polling for completion..."

        if (-not $pollUrl) {
            $pollUrl = "https://$WebAppName.scm.azurewebsites.net/api/deployments/latest"
        }

        $maxWait = 300  # 5 minutes
        $elapsed = 0
        $interval = 15
        while ($elapsed -lt $maxWait) {
            Start-Sleep -Seconds $interval
            $elapsed += $interval
            try {
                $pollReq = [System.Net.HttpWebRequest]::Create($pollUrl)
                $pollReq.Headers.Add("Authorization", "Bearer $token")
                $pollReq.Timeout = 30000
                $pollResp = $pollReq.GetResponse()
                $reader = New-Object System.IO.StreamReader($pollResp.GetResponseStream())
                $body = $reader.ReadToEnd()
                $pollResp.Close()

                $deployStatus = ($body | ConvertFrom-Json)
                $status = $deployStatus.status
                $complete = $deployStatus.complete
                Write-Host "  [$elapsed s] Status: $status, Complete: $complete"

                if ($complete -eq $true -or $status -eq 4) {
                    Write-Host ""
                    Write-Host "SUCCESS - Code deployed!" -ForegroundColor Green
                    Write-Host "URL: https://$WebAppName.azurewebsites.net"
                    break
                }
                if ($status -eq 3) {
                    Write-Host "DEPLOY FAILED on server." -ForegroundColor Red
                    Write-Host $body
                    exit 1
                }
            } catch {
                Write-Host "  [$elapsed s] Poll error: $($_.Exception.Message)"
            }
        }
        if ($elapsed -ge $maxWait) {
            Write-Host "WARNING: Timed out waiting for deploy, but it may still complete on the server."
        }
    } else {
        $response.Close()
        Write-Host ""
        Write-Host "SUCCESS - Code deployed!" -ForegroundColor Green
        Write-Host "URL: https://$WebAppName.azurewebsites.net"
    }
} catch [System.Net.WebException] {
    $ex = $_.Exception
    Write-Host "ERROR: $($ex.Message)" -ForegroundColor Red
    if ($ex.Response) {
        $stream = $ex.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        $errBody = $reader.ReadToEnd()
        Write-Host "Details: $errBody"
    }
    exit 1
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# --- Set startup command ---
Write-Host ""
Write-Host "Setting startup command..."

$configUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/sites/$WebAppName/config/web?api-version=2023-12-01"
$configBody = @{
    properties = @{
        appCommandLine = $startupCmd
        linuxFxVersion = "PYTHON|3.12"
        alwaysOn       = $true
    }
} | ConvertTo-Json -Depth 3

try {
    $configResponse = Invoke-RestMethod -Uri $configUri -Method Patch -Headers @{
        Authorization  = "Bearer $token"
        "Content-Type" = "application/json"
    } -Body $configBody
    Write-Host "Startup command set: $startupCmd" -ForegroundColor Green
} catch {
    Write-Host "WARNING: Could not set startup command: $($_.Exception.Message)" -ForegroundColor Yellow
}

# Cleanup
Remove-Item $stagingDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Deployment complete!" -ForegroundColor Green
Write-Host "Health check: https://$WebAppName.azurewebsites.net/health"
