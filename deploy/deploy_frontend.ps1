# Deploy frontend code via Kudu ZIP Deploy API (PowerShell 5.1 compatible)
# Uses TrustAllCertsPolicy to accept the corporate proxy self-signed certificate

param(
    [string]$SubscriptionId = "24cbffca-ac7d-4f7f-9da9-88f62339afe9",
    [string]$ResourceGroup  = "rg-llmcouncil",
    [string]$WebAppName     = "llmcouncil-frontend",
    [string]$ProjectRoot    = "C:\Users\EOVBK\Django\Architect\LLMCouncilMGA-Azure"
)

# --- Bypass SSL certificate validation (PS 5.1) ---
try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllCertsPolicy4 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) {
        return true;
    }
}
"@
} catch {}  # Ignore if already defined
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllCertsPolicy4
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

# --- Get access token ---
Write-Host "Getting access token..."
$token = az account get-access-token --query accessToken -o tsv 2>$null
if (-not $token) { Write-Host "ERROR: Could not get access token."; exit 1 }
Write-Host "Token obtained."

# --- Build frontend for Azure ---
$frontendDir = Join-Path $ProjectRoot "frontend"
Write-Host ""
Write-Host "Building frontend for Azure..."
Push-Location $frontendDir
try {
    & npx vite build --mode azure 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Frontend build failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "Frontend build completed." -ForegroundColor Green
} finally {
    Pop-Location
}

# --- Build deployment ZIP ---
$zipPath = Join-Path $env:TEMP "llmcouncil-frontend-deploy.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

Write-Host ""
Write-Host "Building deployment package..."

# Create a staging directory
$stagingDir = Join-Path $env:TEMP "llmcouncil-frontend-staging"
if (Test-Path $stagingDir) { Remove-Item $stagingDir -Recurse -Force }
New-Item -ItemType Directory -Path $stagingDir | Out-Null

# Copy server.js
Copy-Item (Join-Path $frontendDir "server.js") (Join-Path $stagingDir "server.js")
Write-Host "  + server.js"

# Copy package.json and package-lock.json
Copy-Item (Join-Path $frontendDir "package.json") (Join-Path $stagingDir "package.json")
Write-Host "  + package.json"

if (Test-Path (Join-Path $frontendDir "package-lock.json")) {
    Copy-Item (Join-Path $frontendDir "package-lock.json") (Join-Path $stagingDir "package-lock.json")
    Write-Host "  + package-lock.json"
}

# Copy dist/ folder
$srcDist = Join-Path $frontendDir "dist"
$dstDist = Join-Path $stagingDir "dist"
if (Test-Path $srcDist) {
    Copy-Item $srcDist $dstDist -Recurse
    $fileCount = (Get-ChildItem $dstDist -Recurse -File).Count
    Write-Host "  + dist/ ($fileCount files)"
} else {
    Write-Host "ERROR: dist/ folder not found. Run 'npm run build:azure' first." -ForegroundColor Red
    exit 1
}

# Install production dependencies (node_modules) in staging
# Required because SCM_DO_BUILD_DURING_DEPLOYMENT=false skips Oryx build
Write-Host "  Installing production dependencies in staging..."
Push-Location $stagingDir
npm install --omit=dev 2>&1 | ForEach-Object { Write-Host "    $_" }
Pop-Location
$modCount = (Get-ChildItem (Join-Path $stagingDir "node_modules") -Directory).Count
Write-Host "  + node_modules/ ($modCount packages)"

# Create ZIP with FORWARD SLASHES (critical for Linux App Service)
# PowerShell's Compress-Archive uses backslashes which causes rsync "Invalid argument (22)" errors on Linux
Write-Host "Compressing to $zipPath (with forward-slash paths)..."
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, 'Create')
Get-ChildItem $stagingDir -Recurse -File | ForEach-Object {
    $relativePath = $_.FullName.Substring($stagingDir.Length + 1).Replace('\', '/')
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, $relativePath, 'Optimal') | Out-Null
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
                    Write-Host "SUCCESS - Frontend deployed!" -ForegroundColor Green
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
        Write-Host "SUCCESS - Frontend deployed!" -ForegroundColor Green
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

# --- Set startup command and runtime ---
Write-Host ""
Write-Host "Setting startup command and runtime..."

$configUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/sites/$WebAppName/config/web?api-version=2023-12-01"
$configBody = @{
    properties = @{
        appCommandLine = "node server.js"
        linuxFxVersion = "NODE|24-lts"
        alwaysOn       = $true
    }
} | ConvertTo-Json -Depth 3

try {
    $configResponse = Invoke-RestMethod -Uri $configUri -Method Patch -Headers @{
        Authorization  = "Bearer $token"
        "Content-Type" = "application/json"
    } -Body $configBody
    Write-Host "Startup command set: node server.js" -ForegroundColor Green
    Write-Host "Runtime set: NODE|24-lts" -ForegroundColor Green
} catch {
    Write-Host "WARNING: Could not set config: $($_.Exception.Message)" -ForegroundColor Yellow
}

# Cleanup
Remove-Item $stagingDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Deployment complete!" -ForegroundColor Green
Write-Host "Frontend URL: https://$WebAppName.azurewebsites.net"
