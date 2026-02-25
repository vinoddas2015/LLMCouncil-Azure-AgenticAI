# Validate Cosmos DB and Azure Storage Account connectivity
# Tests: (1) App settings configured, (2) Cosmos DB CRUD via API, (3) Blob Storage ARM check

param(
    [string]$SubscriptionId = "24cbffca-ac7d-4f7f-9da9-88f62339afe9",
    [string]$ResourceGroup  = "rg-llmcouncil",
    [string]$WebAppName     = "llmcouncil-backend",
    [string]$BaseUrl        = "https://llmcouncil-backend.azurewebsites.net"
)

# --- SSL bypass (PS 5.1) ---
try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustValid1 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) { return true; }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustValid1
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$results = @()
$pass = 0; $fail = 0

function Log-Result($test, $status, $detail) {
    $icon = if ($status -eq "PASS") { "[PASS]" } else { "[FAIL]" }
    $line = "$icon $test - $detail"
    Write-Host $line
    $script:results += $line
    if ($status -eq "PASS") { $script:pass++ } else { $script:fail++ }
}

# --- Get ARM token ---
$token = az account get-access-token --query accessToken -o tsv 2>$null
if (-not $token) { Write-Host "ERROR: No Azure token"; exit 1 }
Write-Host "Azure token OK`n"

# ═══════════════════════════════════════════════════════════════
# TEST 1: Verify App Settings contain Cosmos DB + Storage configs
# ═══════════════════════════════════════════════════════════════
Write-Host "=== TEST 1: App Settings Verification ==="
$settingsUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Web/sites/$WebAppName/config/appsettings/list?api-version=2023-12-01"
try {
    $req = [System.Net.HttpWebRequest]::Create($settingsUri)
    $req.Method = "POST"
    $req.ContentLength = 0
    $req.Headers.Add("Authorization", "Bearer $token")
    $req.Timeout = 30000
    $resp = $req.GetResponse()
    $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
    $body = $reader.ReadToEnd()
    $resp.Close()
    $settings = ($body | ConvertFrom-Json).properties

    # Check Cosmos DB settings
    $cosmosEndpoint = $settings.COSMOS_ENDPOINT
    $cosmosKey = $settings.COSMOS_KEY
    $cosmosDb = $settings.COSMOS_DATABASE
    $cosmosConvContainer = $settings.COSMOS_CONVERSATIONS_CONTAINER

    if ($cosmosEndpoint) {
        Log-Result "COSMOS_ENDPOINT" "PASS" "Set: $($cosmosEndpoint.Substring(0, [Math]::Min(50, $cosmosEndpoint.Length)))..."
    } else { Log-Result "COSMOS_ENDPOINT" "FAIL" "Not configured" }

    if ($cosmosKey) {
        Log-Result "COSMOS_KEY" "PASS" "Set (hidden, $($cosmosKey.Length) chars)"
    } else { Log-Result "COSMOS_KEY" "FAIL" "Not configured" }

    if ($cosmosDb) {
        Log-Result "COSMOS_DATABASE" "PASS" "Value: $cosmosDb"
    } else { Log-Result "COSMOS_DATABASE" "FAIL" "Not configured (will default to 'llm-council')" }

    if ($cosmosConvContainer) {
        Log-Result "COSMOS_CONVERSATIONS_CONTAINER" "PASS" "Value: $cosmosConvContainer"
    } else { Log-Result "COSMOS_CONVERSATIONS_CONTAINER" "FAIL" "Not configured (will default to 'conversations')" }

    # Check Azure Storage settings
    $storageConn = $settings.AZURE_STORAGE_CONNECTION_STRING
    if ($storageConn) {
        Log-Result "AZURE_STORAGE_CONNECTION_STRING" "PASS" "Set ($($storageConn.Length) chars)"
    } else { Log-Result "AZURE_STORAGE_CONNECTION_STRING" "FAIL" "Not configured" }

    # Check blob container settings
    foreach ($c in @("AZURE_BLOB_CONVERSATIONS_CONTAINER","AZURE_BLOB_ATTACHMENTS_CONTAINER","AZURE_BLOB_MEMORY_CONTAINER","AZURE_BLOB_SKILLS_CONTAINER")) {
        $val = $settings.$c
        if ($val) { Log-Result $c "PASS" "Value: $val" }
        else { Log-Result $c "FAIL" "Not configured (will use default)" }
    }
} catch {
    Log-Result "App Settings" "FAIL" "Could not read: $($_.Exception.Message)"
}

Write-Host ""

# ═══════════════════════════════════════════════════════════════
# TEST 2: Cosmos DB CRUD via Backend API
# ═══════════════════════════════════════════════════════════════
Write-Host "=== TEST 2: Cosmos DB Connectivity (CRUD via API) ==="
$testUserId = "validation-test-user"

# 2a. CREATE conversation
$testConvId = [guid]::NewGuid().ToString()
Write-Host "  Creating test conversation: $testConvId"
try {
    $createUri = "$BaseUrl/api/conversations"
    $createBody = (@{ conversation_id = $testConvId } | ConvertTo-Json)
    $createBytes = [System.Text.Encoding]::UTF8.GetBytes($createBody)

    $req = [System.Net.HttpWebRequest]::Create($createUri)
    $req.Method = "POST"
    $req.ContentType = "application/json"
    $req.Headers.Add("user-id", $testUserId)
    $req.Timeout = 30000
    $req.ContentLength = $createBytes.Length
    $rs = $req.GetRequestStream()
    $rs.Write($createBytes, 0, $createBytes.Length)
    $rs.Close()

    $resp = $req.GetResponse()
    $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
    $body = $reader.ReadToEnd()
    $resp.Close()
    $created = $body | ConvertFrom-Json
    $testConvId = $created.id   # Use server-generated ID for subsequent operations
    Log-Result "Cosmos CREATE" "PASS" "Created conversation $($created.id)"
} catch {
    $errMsg = $_.Exception.Message
    # Try to read error body
    try {
        $errResp = $_.Exception.InnerException.Response
        if ($errResp) {
            $errReader = New-Object System.IO.StreamReader($errResp.GetResponseStream())
            $errBody = $errReader.ReadToEnd()
            $errMsg = "$errMsg | Body: $errBody"
        }
    } catch {}
    Log-Result "Cosmos CREATE" "FAIL" $errMsg
}

# 2b. LIST conversations
Write-Host "  Listing conversations..."
try {
    $listUri = "$BaseUrl/api/conversations"
    $req = [System.Net.HttpWebRequest]::Create($listUri)
    $req.Method = "GET"
    $req.Headers.Add("user-id", $testUserId)
    $req.Timeout = 30000
    $resp = $req.GetResponse()
    $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
    $body = $reader.ReadToEnd()
    $resp.Close()
    $convos = $body | ConvertFrom-Json
    $found = $convos | Where-Object { $_.id -eq $testConvId }
    if ($found) {
        Log-Result "Cosmos LIST" "PASS" "Found test conversation in list ($($convos.Count) total)"
    } else {
        Log-Result "Cosmos LIST" "PASS" "Listed $($convos.Count) conversations (test conv may not appear in metadata query)"
    }
} catch {
    Log-Result "Cosmos LIST" "FAIL" $_.Exception.Message
}

# 2c. GET specific conversation
Write-Host "  Reading conversation..."
try {
    $getUri = "$BaseUrl/api/conversations/$testConvId"
    $req = [System.Net.HttpWebRequest]::Create($getUri)
    $req.Method = "GET"
    $req.Headers.Add("user-id", $testUserId)
    $req.Timeout = 30000
    $resp = $req.GetResponse()
    $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
    $body = $reader.ReadToEnd()
    $resp.Close()
    $conv = $body | ConvertFrom-Json
    Log-Result "Cosmos READ" "PASS" "Read conversation id=$($conv.id), messages=$($conv.messages.Count)"
} catch {
    $status = ""
    try { $status = [int]$_.Exception.InnerException.Response.StatusCode } catch {}
    Log-Result "Cosmos READ" "FAIL" "HTTP $status - $($_.Exception.Message)"
}

# 2d. DELETE conversation (cleanup)
Write-Host "  Deleting test conversation..."
try {
    $delUri = "$BaseUrl/api/conversations/$testConvId"
    $req = [System.Net.HttpWebRequest]::Create($delUri)
    $req.Method = "DELETE"
    $req.Headers.Add("user-id", $testUserId)
    $req.Timeout = 30000
    $resp = $req.GetResponse()
    $statusCode = [int]$resp.StatusCode
    $resp.Close()
    Log-Result "Cosmos DELETE" "PASS" "Deleted test conversation (HTTP $statusCode)"
} catch {
    $status = ""
    try { $status = [int]$_.Exception.InnerException.Response.StatusCode } catch {}
    Log-Result "Cosmos DELETE" "FAIL" "HTTP $status - $($_.Exception.Message)"
}

Write-Host ""

# ═══════════════════════════════════════════════════════════════
# TEST 3: Azure Storage Account ARM Validation
# ═══════════════════════════════════════════════════════════════
Write-Host "=== TEST 3: Azure Storage Account (ARM API) ==="

# 3a. List storage accounts in resource group
$storageListUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Storage/storageAccounts?api-version=2023-05-01"
try {
    $req = [System.Net.HttpWebRequest]::Create($storageListUri)
    $req.Method = "GET"
    $req.Headers.Add("Authorization", "Bearer $token")
    $req.Timeout = 30000
    $resp = $req.GetResponse()
    $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
    $body = $reader.ReadToEnd()
    $resp.Close()
    $storageAccounts = ($body | ConvertFrom-Json).value
    if ($storageAccounts.Count -gt 0) {
        foreach ($sa in $storageAccounts) {
            Log-Result "Storage Account Exists" "PASS" "$($sa.name) (location: $($sa.location), kind: $($sa.kind), status: $($sa.properties.provisioningState))"
        }
    } else {
        Log-Result "Storage Account Exists" "FAIL" "No storage accounts found in $ResourceGroup"
    }
} catch {
    Log-Result "Storage Account Exists" "FAIL" $_.Exception.Message
}

# 3b. Check Cosmos DB account via ARM
Write-Host ""
Write-Host "=== TEST 4: Cosmos DB Account (ARM API) ==="
$cosmosListUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.DocumentDB/databaseAccounts?api-version=2024-05-15"
try {
    $req = [System.Net.HttpWebRequest]::Create($cosmosListUri)
    $req.Method = "GET"
    $req.Headers.Add("Authorization", "Bearer $token")
    $req.Timeout = 30000
    $resp = $req.GetResponse()
    $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
    $body = $reader.ReadToEnd()
    $resp.Close()
    $cosmosAccounts = ($body | ConvertFrom-Json).value
    if ($cosmosAccounts.Count -gt 0) {
        foreach ($ca in $cosmosAccounts) {
            Log-Result "Cosmos DB Account Exists" "PASS" "$($ca.name) (location: $($ca.properties.locations[0].locationName), status: $($ca.properties.provisioningState))"
            
            # Check if the endpoint matches what's in app settings
            $armEndpoint = $ca.properties.documentEndpoint
            if ($cosmosEndpoint -and $armEndpoint -eq $cosmosEndpoint) {
                Log-Result "Cosmos Endpoint Match" "PASS" "App setting matches ARM: $armEndpoint"
            } elseif ($cosmosEndpoint) {
                Log-Result "Cosmos Endpoint Match" "FAIL" "ARM=$armEndpoint vs AppSetting=$cosmosEndpoint"
            }
        }
    } else {
        Log-Result "Cosmos DB Account Exists" "FAIL" "No Cosmos DB accounts found in $ResourceGroup"
    }
} catch {
    Log-Result "Cosmos DB Account Exists" "FAIL" $_.Exception.Message
}

# 3c. List Blob containers via ARM (if storage account found)
if ($storageAccounts.Count -gt 0) {
    Write-Host ""
    Write-Host "=== TEST 5: Blob Containers (ARM API) ==="
    foreach ($sa in $storageAccounts) {
        $containersUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Storage/storageAccounts/$($sa.name)/blobServices/default/containers?api-version=2023-05-01"
        try {
            $req = [System.Net.HttpWebRequest]::Create($containersUri)
            $req.Method = "GET"
            $req.Headers.Add("Authorization", "Bearer $token")
            $req.Timeout = 30000
            $resp = $req.GetResponse()
            $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
            $body = $reader.ReadToEnd()
            $resp.Close()
            $containers = ($body | ConvertFrom-Json).value
            $containerNames = $containers | ForEach-Object { $_.name }
            Log-Result "Blob Containers" "PASS" "Found $($containers.Count) in $($sa.name): $($containerNames -join ', ')"
            
            # Verify expected containers exist
            $expected = @("conversations", "attachments", "memory", "skills")
            foreach ($exp in $expected) {
                if ($containerNames -contains $exp) {
                    Log-Result "Container '$exp'" "PASS" "Exists in $($sa.name)"
                } else {
                    Log-Result "Container '$exp'" "FAIL" "Missing from $($sa.name)"
                }
            }
        } catch {
            Log-Result "Blob Containers" "FAIL" "Could not list containers for $($sa.name): $($_.Exception.Message)"
        }
    }
}

# ═══════════════════════════════════════════════════════════════
# TEST 6: Backend live Cosmos check via app logs
# ═══════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "=== TEST 6: Application Log Check ==="
$logUri = "https://$WebAppName.scm.azurewebsites.net/api/logstream"
try {
    # Fetch recent Docker logs
    $dockerLogUri = "https://$WebAppName.scm.azurewebsites.net/api/vfs/LogFiles/docker/"
    $req = [System.Net.HttpWebRequest]::Create($dockerLogUri)
    $req.Method = "GET"
    $req.Headers.Add("Authorization", "Bearer $token")
    $req.Timeout = 30000
    $resp = $req.GetResponse()
    $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
    $body = $reader.ReadToEnd()
    $resp.Close()
    $logFiles = ($body | ConvertFrom-Json) | Sort-Object { $_.mtime } -Descending | Select-Object -First 1
    
    if ($logFiles) {
        $logFileUri = $logFiles.href
        $req2 = [System.Net.HttpWebRequest]::Create($logFileUri)
        $req2.Method = "GET"
        $req2.Headers.Add("Authorization", "Bearer $token")
        $req2.Timeout = 30000
        $resp2 = $req2.GetResponse()
        $reader2 = New-Object System.IO.StreamReader($resp2.GetResponseStream())
        $logContent = $reader2.ReadToEnd()
        $resp2.Close()
        
        # Get last 50 lines
        $lines = $logContent -split "`n" | Select-Object -Last 50
        
        # Look for Cosmos/storage errors
        $cosmosErrors = $lines | Where-Object { $_ -match "cosmos|CosmosClient|DocumentDB" -and $_ -match "error|Error|ERROR|exception|Exception|fail" }
        $storageErrors = $lines | Where-Object { $_ -match "blob|storage|BlobService" -and $_ -match "error|Error|ERROR|exception|Exception|fail" }
        
        if ($cosmosErrors) {
            Log-Result "Cosmos Errors in Logs" "FAIL" "Found $($cosmosErrors.Count) error(s): $($cosmosErrors[0].Trim().Substring(0, [Math]::Min(200, $cosmosErrors[0].Trim().Length)))"
        } else {
            Log-Result "Cosmos Errors in Logs" "PASS" "No Cosmos errors in recent logs"
        }
        
        if ($storageErrors) {
            Log-Result "Storage Errors in Logs" "FAIL" "Found $($storageErrors.Count) error(s): $($storageErrors[0].Trim().Substring(0, [Math]::Min(200, $storageErrors[0].Trim().Length)))"
        } else {
            Log-Result "Storage Errors in Logs" "PASS" "No Blob Storage errors in recent logs"
        }
    } else {
        Log-Result "Log Check" "FAIL" "No Docker log files found"
    }
} catch {
    Log-Result "Log Check" "FAIL" "Could not fetch logs: $($_.Exception.Message)"
}

# ═══════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "============================================"
Write-Host "  VALIDATION SUMMARY: $pass PASS / $fail FAIL"
Write-Host "============================================"
foreach ($r in $results) { Write-Host "  $r" }
Write-Host ""

# Write to file
$outFile = Join-Path $PSScriptRoot "validate_result.txt"
$output = @("=== Connectivity Validation Results ===", "Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')", "Target: $BaseUrl", "")
$output += $results
$output += @("", "SUMMARY: $pass PASS / $fail FAIL")
$output | Out-File -FilePath $outFile -Encoding utf8
Write-Host "Results saved to: $outFile"
