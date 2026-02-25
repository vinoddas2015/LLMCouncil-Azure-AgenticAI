# ============================================================================
# Test Scenarios: Data Creation in Cosmos DB & Azure Storage via Backend API
# ============================================================================
# Exercises the live backend at https://llmcouncil-backend.azurewebsites.net
# to verify data persistence in:
#   - Azure Cosmos DB (conversations container, memory container)
#   - Azure Blob Storage (4 containers: conversations, attachments, memory, skills)
#
# Usage: powershell -ExecutionPolicy Bypass -File deploy\test_data_creation.ps1
# ============================================================================

param(
    [string]$SubscriptionId = "24cbffca-ac7d-4f7f-9da9-88f62339afe9",
    [string]$ResourceGroup  = "rg-llmcouncil",
    [string]$WebAppName     = "llmcouncil-backend",
    [string]$StorageAccount = "llmcouncilmga",
    [string]$CosmosAccount  = "llmcouncil-cosmos",
    [string]$CosmosDatabase = "llm-council",
    [string]$TestUserId     = "test-data-creation-user"
)

$baseUrl = "https://$WebAppName.azurewebsites.net"
$outputFile = Join-Path $PSScriptRoot "test_data_creation_results.txt"

# --- SSL bypass (PS 5.1) ---
try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustTestData1 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) { return true; }
}
"@
} catch {}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustTestData1
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

# --- Helpers ---
$pass = 0; $fail = 0; $skip = 0
$results = [System.Collections.ArrayList]::new()

function Log($msg) {
    Write-Host $msg
    [void]$results.Add($msg)
}

function Test-Result($name, $condition, $detail) {
    if ($condition) {
        $script:pass++
        Log "  [PASS] $name"
    } else {
        $script:fail++
        Log "  [FAIL] $name -- $detail"
    }
}

function Invoke-Api {
    param(
        [string]$Method,
        [string]$Path,
        [string]$Body = $null,
        [string]$UserId = $TestUserId,
        [int]$TimeoutSec = 30
    )
    $uri = "$baseUrl$Path"
    $headers = @{ "Content-Type" = "application/json" }
    if ($UserId) { $headers["user-id"] = $UserId }
    
    try {
        $params = @{
            Uri             = $uri
            Method          = $Method
            Headers         = $headers
            UseBasicParsing = $true
            TimeoutSec      = $TimeoutSec
        }
        if ($Body) { $params.Body = $Body }
        $resp = Invoke-WebRequest @params
        return @{
            StatusCode = $resp.StatusCode
            Body       = ($resp.Content | ConvertFrom-Json)
            Raw        = $resp.Content
            Success    = $true
        }
    } catch {
        $sc = 0
        if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode }
        return @{
            StatusCode = $sc
            Body       = $null
            Raw        = $_.Exception.Message
            Success    = $false
        }
    }
}

# --- Get ARM token for direct Azure verification ---
$token = az account get-access-token --query accessToken -o tsv 2>$null
$hasArmToken = [bool]$token

Log "============================================================================"
Log "  LLM Council -- Data Creation Test Scenarios"
Log "  Backend:  $baseUrl"
Log "  User-ID:  $TestUserId"
if ($hasArmToken) { Log "  ARM Token: Available" } else { Log "  ARM Token: Unavailable (ARM tests skipped)" }
Log "  Started:  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Log "============================================================================"
Log ""

# +====================================================================+
# |  GROUP A: Conversation CRUD -- Cosmos DB conversations container    |
# +====================================================================+
Log "===================================================================="
Log "GROUP A: Conversation CRUD -- Cosmos DB conversations container"
Log "===================================================================="
Log ""

# --- A1: Create conversation ---
Log "A1: Create a new conversation"
$a1 = Invoke-Api -Method POST -Path "/api/conversations" -Body "{}"
Test-Result "HTTP 200 returned" ($a1.StatusCode -eq 200) "Got $($a1.StatusCode)"
$convId1 = $null
if ($a1.Success -and $a1.Body.id) {
    $convId1 = $a1.Body.id
    Test-Result "Conversation ID returned" ($true) ""
    Test-Result "ID is valid UUID" ($convId1 -match '^[0-9a-f]{8}-') "Got: $convId1"
    Test-Result "Has created_at field" ([bool]$a1.Body.created_at) "Missing"
    Test-Result "Messages array is empty" ($a1.Body.messages.Count -eq 0) "Count: $($a1.Body.messages.Count)"
    Log "  -> Created: $convId1"
} else {
    Test-Result "Response body valid" $false "No ID in response: $($a1.Raw)"
}
Log ""

# --- A2: Get conversation by ID ---
Log "A2: Read back conversation by ID"
if ($convId1) {
    $a2 = Invoke-Api -Method GET -Path "/api/conversations/$convId1"
    Test-Result "HTTP 200 returned" ($a2.StatusCode -eq 200) "Got $($a2.StatusCode)"
    Test-Result "ID matches" ($a2.Body.id -eq $convId1) "Expected $convId1, got $($a2.Body.id)"
    Test-Result "Messages still empty" ($a2.Body.messages.Count -eq 0) "Count: $($a2.Body.messages.Count)"
} else { Log "  [SKIP] No conversation ID from A1"; $skip++ }
Log ""

# --- A3: List conversations (verify new one appears) ---
Log "A3: List conversations -- verify new conversation appears"
if ($convId1) {
    $a3 = Invoke-Api -Method GET -Path "/api/conversations"
    Test-Result "HTTP 200 returned" ($a3.StatusCode -eq 200) "Got $($a3.StatusCode)"
    $found = $false
    if ($a3.Body) {
        foreach ($c in $a3.Body) {
            if ($c.id -eq $convId1) { $found = $true; break }
        }
    }
    Test-Result "New conversation in list" $found "Conversation $convId1 not found in list of $($a3.Body.Count) items"
} else { Log "  [SKIP] No conversation ID from A1"; $skip++ }
Log ""

# --- A4: Create second conversation ---
Log "A4: Create second conversation"
$a4 = Invoke-Api -Method POST -Path "/api/conversations" -Body "{}"
Test-Result "HTTP 200 returned" ($a4.StatusCode -eq 200) "Got $($a4.StatusCode)"
$convId2 = $null
if ($a4.Success -and $a4.Body.id) {
    $convId2 = $a4.Body.id
    Test-Result "Second ID returned" $true ""
    Test-Result "IDs are different" ($convId2 -ne $convId1) "Both are $convId2"
    Log "  -> Created: $convId2"
} else {
    Test-Result "Response body valid" $false "No ID: $($a4.Raw)"
}
Log ""

# --- A5: Create third conversation ---
Log "A5: Create third conversation"
$a5 = Invoke-Api -Method POST -Path "/api/conversations" -Body "{}"
Test-Result "HTTP 200 returned" ($a5.StatusCode -eq 200) "Got $($a5.StatusCode)"
$convId3 = $null
if ($a5.Success -and $a5.Body.id) {
    $convId3 = $a5.Body.id
    Test-Result "Third ID returned" $true ""
    Log "  -> Created: $convId3"
} else {
    Test-Result "Response body valid" $false "No ID: $($a5.Raw)"
}
Log ""

# --- A6: List all three ---
Log "A6: List conversations -- verify all three exist"
$a6 = Invoke-Api -Method GET -Path "/api/conversations"
Test-Result "HTTP 200 returned" ($a6.StatusCode -eq 200) "Got $($a6.StatusCode)"
$ids = @($convId1, $convId2, $convId3) | Where-Object { $_ }
$foundCount = 0
if ($a6.Body) {
    $listedIds = $a6.Body | ForEach-Object { $_.id }
    foreach ($id in $ids) {
        if ($listedIds -contains $id) { $foundCount++ }
    }
}
Test-Result "All $($ids.Count) conversations in list" ($foundCount -eq $ids.Count) "Found $foundCount of $($ids.Count)"
Log ""

# --- A7: Export conversation (Markdown) ---
Log "A7: Export conversation as Markdown"
if ($convId1) {
    $a7 = Invoke-Api -Method GET -Path "/api/conversations/$convId1/export?format=markdown"
    Test-Result "HTTP 200 returned" ($a7.StatusCode -eq 200) "Got $($a7.StatusCode)"
    Test-Result "Has filename field" ([bool]$a7.Body.filename) "Missing"
    Test-Result "Has content field" ([bool]$a7.Body.content) "Missing"
    Test-Result "Content type is markdown" ($a7.Body.content_type -eq "text/markdown") "Got: $($a7.Body.content_type)"
} else { Log "  [SKIP] No conversation ID"; $skip++ }
Log ""

# --- A8: Export conversation (JSON) ---
Log "A8: Export conversation as JSON"
if ($convId1) {
    $a8 = Invoke-Api -Method GET -Path "/api/conversations/$convId1/export?format=json"
    Test-Result "HTTP 200 returned" ($a8.StatusCode -eq 200) "Got $($a8.StatusCode)"
    Test-Result "Has filename field" ([bool]$a8.Body.filename) "Missing"
    Test-Result "Content type is JSON" ($a8.Body.content_type -eq "application/json") "Got: $($a8.Body.content_type)"
} else { Log "  [SKIP] No conversation ID"; $skip++ }
Log ""

# --- A9: Delete first conversation ---
Log "A9: Delete first conversation"
if ($convId1) {
    $a9 = Invoke-Api -Method DELETE -Path "/api/conversations/$convId1"
    Test-Result "HTTP 200 returned" ($a9.StatusCode -eq 200) "Got $($a9.StatusCode)"
    Test-Result "Status is 'deleted'" ($a9.Body.status -eq "deleted") "Got: $($a9.Body.status)"
} else { Log "  [SKIP] No conversation ID"; $skip++ }
Log ""

# --- A10: Verify deletion (404 expected) ---
Log "A10: Verify deleted conversation returns 404"
if ($convId1) {
    $a10 = Invoke-Api -Method GET -Path "/api/conversations/$convId1"
    Test-Result "HTTP 404 returned" ($a10.StatusCode -eq 404) "Got $($a10.StatusCode)"
} else { Log "  [SKIP] No conversation ID"; $skip++ }
Log ""

# --- A11: Verify deletion from list ---
Log "A11: Verify deleted conversation absent from list"
if ($convId1) {
    $a11 = Invoke-Api -Method GET -Path "/api/conversations"
    $stillPresent = $false
    if ($a11.Body) {
        foreach ($c in $a11.Body) {
            if ($c.id -eq $convId1) { $stillPresent = $true; break }
        }
    }
    Test-Result "Deleted conversation not in list" (-not $stillPresent) "Conversation $convId1 still appears"
    # Verify other two still present
    $c2Found = $false; $c3Found = $false
    if ($a11.Body) {
        foreach ($c in $a11.Body) {
            if ($c.id -eq $convId2) { $c2Found = $true }
            if ($c.id -eq $convId3) { $c3Found = $true }
        }
    }
    if ($convId2) { Test-Result "Second conversation still exists" $c2Found "Missing" }
    if ($convId3) { Test-Result "Third conversation still exists" $c3Found "Missing" }
} else { Log "  [SKIP] No conversation ID"; $skip++ }
Log ""

# --- A12: Cleanup -- delete remaining test conversations ---
Log "A12: Cleanup -- delete remaining test conversations"
$cleanupIds = @($convId2, $convId3) | Where-Object { $_ }
foreach ($id in $cleanupIds) {
    $del = Invoke-Api -Method DELETE -Path "/api/conversations/$id"
    Test-Result "Delete $($id.Substring(0,8))..." ($del.StatusCode -eq 200) "Got $($del.StatusCode)"
}
Log ""


# +====================================================================+
# |  GROUP B: Memory Tier Access -- Cosmos DB memory container          |
# +====================================================================+
Log "===================================================================="
Log "GROUP B: Memory Tier Access -- Cosmos DB memory container"
Log "===================================================================="
Log ""

# --- B1: Memory stats ---
Log "B1: Get memory statistics"
$b1 = Invoke-Api -Method GET -Path "/api/memory/stats" -UserId ""
Test-Result "HTTP 200 returned" ($b1.StatusCode -eq 200) "Got $($b1.StatusCode)"
if ($b1.Success) {
    Log "  -> Stats: $($b1.Raw)"
}
Log ""

# --- B2: List semantic memories ---
Log "B2: List semantic memories"
$b2 = Invoke-Api -Method GET -Path "/api/memory/semantic" -UserId ""
Test-Result "HTTP 200 returned" ($b2.StatusCode -eq 200) "Got $($b2.StatusCode)"
if ($b2.Success) {
    $semCount = 0
    if ($b2.Body) { $semCount = $b2.Body.Count }
    Log "  -> Semantic entries: $semCount"
}
Log ""

# --- B3: List episodic memories ---
Log "B3: List episodic memories"
$b3 = Invoke-Api -Method GET -Path "/api/memory/episodic" -UserId ""
Test-Result "HTTP 200 returned" ($b3.StatusCode -eq 200) "Got $($b3.StatusCode)"
if ($b3.Success) {
    $epCount = 0
    if ($b3.Body) { $epCount = $b3.Body.Count }
    Log "  -> Episodic entries: $epCount"
}
Log ""

# --- B4: List procedural memories ---
Log "B4: List procedural memories"
$b4 = Invoke-Api -Method GET -Path "/api/memory/procedural" -UserId ""
Test-Result "HTTP 200 returned" ($b4.StatusCode -eq 200) "Got $($b4.StatusCode)"
if ($b4.Success) {
    $procCount = 0
    if ($b4.Body) { $procCount = $b4.Body.Count }
    Log "  -> Procedural entries: $procCount"
}
Log ""

# --- B5: Search memories ---
Log "B5: Search semantic memories"
$b5 = Invoke-Api -Method GET -Path "/api/memory/search/semantic?q=test&limit=5" -UserId ""
Test-Result "HTTP 200 returned" ($b5.StatusCode -eq 200) "Got $($b5.StatusCode)"
Log ""

# --- B6: Get non-existent memory (expect 404) ---
Log "B6: Get non-existent memory entry (expect 404)"
$b6 = Invoke-Api -Method GET -Path "/api/memory/semantic/nonexistent-test-id-12345" -UserId ""
Test-Result "HTTP 404 returned" ($b6.StatusCode -eq 404) "Got $($b6.StatusCode)"
Log ""

# --- B7: Delete non-existent memory (expect 404) ---
Log "B7: Delete non-existent memory entry (expect 404)"
$b7 = Invoke-Api -Method DELETE -Path "/api/memory/semantic/nonexistent-test-id-12345" -UserId ""
Test-Result "HTTP 404 returned" ($b7.StatusCode -eq 404) "Got $($b7.StatusCode)"
Log ""


# +====================================================================+
# |  GROUP C: Azure Blob Storage -- Container Accessibility             |
# +====================================================================+
Log "===================================================================="
Log "GROUP C: Azure Blob Storage -- Container Accessibility"
Log "===================================================================="
Log ""

if (-not $hasArmToken) {
    Log "  [SKIP] ARM token unavailable -- cannot verify blob containers directly"
    $skip += 4
} else {
    $blobContainers = @("conversations", "attachments", "memory", "skills")
    
    # C1: List all containers
    Log "C1: Verify all 4 blob containers exist"
    $storageUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Storage/storageAccounts/$StorageAccount/blobServices/default/containers?api-version=2023-05-01"
    try {
        $storageResp = Invoke-RestMethod -Uri $storageUri -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30
        $existingContainers = $storageResp.value | ForEach-Object { $_.name }
        foreach ($container in $blobContainers) {
            Test-Result "Container '$container' exists" ($existingContainers -contains $container) "Not found"
        }
        Log "  -> Total containers: $($existingContainers.Count)"
    } catch {
        Log "  [FAIL] ARM container list failed: $($_.Exception.Message)"
        $fail += 4
    }
    Log ""

    # C2: Check storage account properties
    Log "C2: Verify storage account properties"
    $saUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Storage/storageAccounts/${StorageAccount}?api-version=2023-05-01"
    try {
        $saResp = Invoke-RestMethod -Uri $saUri -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30
        Test-Result "Storage account kind is StorageV2" ($saResp.kind -eq "StorageV2") "Got: $($saResp.kind)"
        Test-Result "TLS version >= 1.2" ($saResp.properties.minimumTlsVersion -match "TLS1_2") "Got: $($saResp.properties.minimumTlsVersion)"
        Test-Result "Encryption enabled" ($saResp.properties.encryption.services.blob.enabled -eq $true) "Off"
        Log "  -> Region: $($saResp.location), SKU: $($saResp.sku.name)"
    } catch {
        Log "  [FAIL] Storage account properties: $($_.Exception.Message)"
        $fail += 3
    }
    Log ""
}


# +====================================================================+
# |  GROUP D: Cosmos DB -- Direct ARM Verification                      |
# +====================================================================+
Log "===================================================================="
Log "GROUP D: Cosmos DB -- Direct ARM Verification"
Log "===================================================================="
Log ""

if (-not $hasArmToken) {
    Log "  [SKIP] ARM token unavailable -- cannot verify Cosmos DB directly"
    $skip += 5
} else {
    # D1: Verify Cosmos DB account
    Log "D1: Verify Cosmos DB account exists and accessible"
    $cosmosUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.DocumentDB/databaseAccounts/${CosmosAccount}?api-version=2024-05-15"
    try {
        $cosmosResp = Invoke-RestMethod -Uri $cosmosUri -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30
        Test-Result "Cosmos account exists" ($cosmosResp.name -eq $CosmosAccount) "Not found"
        Test-Result "Cosmos account online" ($cosmosResp.properties.provisioningState -eq "Succeeded") "State: $($cosmosResp.properties.provisioningState)"
        Log "  -> Endpoint: $($cosmosResp.properties.documentEndpoint)"
        Log "  -> Consistency: $($cosmosResp.properties.consistencyPolicy.defaultConsistencyLevel)"
    } catch {
        Log "  [FAIL] Cosmos account check: $($_.Exception.Message)"
        $fail += 2
    }
    Log ""

    # D2: Verify Cosmos DB database
    Log "D2: Verify Cosmos DB database '$CosmosDatabase'"
    $dbUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.DocumentDB/databaseAccounts/$CosmosAccount/sqlDatabases/${CosmosDatabase}?api-version=2024-05-15"
    try {
        $dbResp = Invoke-RestMethod -Uri $dbUri -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30
        Test-Result "Database exists" ($dbResp.name -eq $CosmosDatabase) "Not found"
    } catch {
        Log "  [FAIL] Cosmos database check: $($_.Exception.Message)"
        $fail++
    }
    Log ""

    # D3: Verify Cosmos containers
    Log "D3: Verify Cosmos DB containers"
    $expectedContainers = @("conversations", "memory", "skills")
    $cosmosContainersUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.DocumentDB/databaseAccounts/$CosmosAccount/sqlDatabases/$CosmosDatabase/containers?api-version=2024-05-15"
    try {
        $containersResp = Invoke-RestMethod -Uri $cosmosContainersUri -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30
        $existingCosmosContainers = $containersResp.value | ForEach-Object { $_.name }
        foreach ($container in $expectedContainers) {
            Test-Result "Cosmos container '$container' exists" ($existingCosmosContainers -contains $container) "Not found"
        }
        Log "  -> All Cosmos containers: $($existingCosmosContainers -join ', ')"
    } catch {
        Log "  [FAIL] Cosmos containers: $($_.Exception.Message)"
        $fail += $expectedContainers.Count
    }
    Log ""
}


# +====================================================================+
# |  GROUP E: Data Isolation -- user-id header enforcement              |
# +====================================================================+
Log "===================================================================="
Log "GROUP E: Data Isolation -- user-id header enforcement"
Log "===================================================================="
Log ""

# --- E1: Missing user-id header -> 422 ---
Log "E1: Request without user-id header -> expect 422"
$uri = "$baseUrl/api/conversations"
try {
    $resp = Invoke-WebRequest -Uri $uri -Method GET -UseBasicParsing -TimeoutSec 15 -Headers @{ "Content-Type" = "application/json" }
    Test-Result "Missing user-id rejected" ($false) "Got HTTP $($resp.StatusCode) instead of 422"
} catch {
    $sc = 0
    if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode }
    Test-Result "Missing user-id rejected (HTTP 422)" ($sc -eq 422) "Got HTTP $sc"
}
Log ""

# --- E2: Path traversal user-id -> 400 ---
Log "E2: Path traversal user-id -> expect 400"
$e2 = Invoke-Api -Method GET -Path "/api/conversations" -UserId "../admin"
Test-Result "Path traversal rejected (HTTP 400)" ($e2.StatusCode -eq 400) "Got HTTP $($e2.StatusCode)"
Log ""

# --- E3: Cross-user isolation ---
Log "E3: Cross-user data isolation"
# Create conversation as user-A
$e3a = Invoke-Api -Method POST -Path "/api/conversations" -Body "{}" -UserId "test-user-alpha"
$alphaId = $null
if ($e3a.Success -and $e3a.Body.id) { $alphaId = $e3a.Body.id }
Test-Result "User-A creates conversation" ([bool]$alphaId) "Create failed"

if ($alphaId) {
    # Try to read it as user-B
    $e3b = Invoke-Api -Method GET -Path "/api/conversations/$alphaId" -UserId "test-user-beta"
    Test-Result "User-B cannot read User-A's data" ($e3b.StatusCode -eq 404) "Got HTTP $($e3b.StatusCode)"

    # Verify user-A can still read it
    $e3c = Invoke-Api -Method GET -Path "/api/conversations/$alphaId" -UserId "test-user-alpha"
    Test-Result "User-A can read own data" ($e3c.StatusCode -eq 200) "Got HTTP $($e3c.StatusCode)"

    # Cleanup
    Invoke-Api -Method DELETE -Path "/api/conversations/$alphaId" -UserId "test-user-alpha" | Out-Null
    Log "  -> Cleaned up test conversation"
}
Log ""


# +====================================================================+
# |  GROUP F: Edge Cases & Error Handling                               |
# +====================================================================+
Log "===================================================================="
Log "GROUP F: Edge Cases & Error Handling"
Log "===================================================================="
Log ""

# --- F1: Get non-existent conversation -> 404 ---
Log "F1: Get non-existent conversation -> expect 404"
$f1 = Invoke-Api -Method GET -Path "/api/conversations/00000000-0000-0000-0000-000000000000"
Test-Result "Non-existent conv returns 404" ($f1.StatusCode -eq 404) "Got $($f1.StatusCode)"
Log ""

# --- F2: Delete non-existent conversation -> 404 ---
Log "F2: Delete non-existent conversation -> expect 404"
$f2 = Invoke-Api -Method DELETE -Path "/api/conversations/00000000-0000-0000-0000-000000000000"
Test-Result "Delete non-existent returns 404" ($f2.StatusCode -eq 404) "Got $($f2.StatusCode)"
Log ""

# --- F3: Health check ---
Log "F3: Health check endpoint"
$f3 = Invoke-Api -Method GET -Path "/health" -UserId ""
Test-Result "Health returns 200" ($f3.StatusCode -eq 200) "Got $($f3.StatusCode)"
Test-Result "Status is 'ok'" ($f3.Body.status -eq "ok") "Got: $($f3.Body.status)"
Log ""

# --- F4: Models endpoint ---
Log "F4: Models endpoint accessible"
$f4 = Invoke-Api -Method GET -Path "/api/models" -UserId ""
Test-Result "Models returns 200" ($f4.StatusCode -eq 200) "Got $($f4.StatusCode)"
if ($f4.Success -and $f4.Body) {
    $modelCount = 0
    if ($f4.Body.council_models) { $modelCount = $f4.Body.council_models.Count }
    Log "  -> Council models: $modelCount"
}
Log ""

# --- F5: Rapid create-delete cycle ---
Log "F5: Rapid create-delete cycle (5 conversations)"
$rapidSuccess = $true
$rapidIds = @()
for ($i = 1; $i -le 5; $i++) {
    $cr = Invoke-Api -Method POST -Path "/api/conversations" -Body "{}"
    if ($cr.Success -and $cr.Body.id) {
        $rapidIds += $cr.Body.id
    } else {
        $rapidSuccess = $false
    }
}
Test-Result "All 5 created successfully" ($rapidIds.Count -eq 5) "Only $($rapidIds.Count) created"

$allDeleted = $true
foreach ($id in $rapidIds) {
    $dr = Invoke-Api -Method DELETE -Path "/api/conversations/$id"
    if ($dr.StatusCode -ne 200) { $allDeleted = $false }
}
Test-Result "All 5 deleted successfully" $allDeleted "Some deletions failed"
Log ""

# --- F6: Double-delete idempotency ---
Log "F6: Double-delete (idempotency check)"
$f6c = Invoke-Api -Method POST -Path "/api/conversations" -Body "{}"
if ($f6c.Success -and $f6c.Body.id) {
    $f6id = $f6c.Body.id
    $d1 = Invoke-Api -Method DELETE -Path "/api/conversations/$f6id"
    Test-Result "First delete succeeds" ($d1.StatusCode -eq 200) "Got $($d1.StatusCode)"
    $d2 = Invoke-Api -Method DELETE -Path "/api/conversations/$f6id"
    Test-Result "Second delete returns 404" ($d2.StatusCode -eq 404) "Got $($d2.StatusCode)"
} else {
    Log "  [SKIP] Create failed"; $skip += 2
}
Log ""


# +====================================================================+
# |  GROUP G: Skills & Kill-Switch Endpoints                            |
# +====================================================================+
Log "===================================================================="
Log "GROUP G: Skills & Kill-Switch Endpoints"
Log "===================================================================="
Log ""

# --- G1: Skills health endpoint ---
Log "G1: Skills health / pipeline status"
$g1 = Invoke-Api -Method GET -Path "/api/health" -UserId ""
Test-Result "HTTP 200 returned" ($g1.StatusCode -eq 200) "Got $($g1.StatusCode)"
Log ""

# --- G2: Kill-switch status ---
Log "G2: Kill-switch status"
$g2 = Invoke-Api -Method GET -Path "/api/kill-switch/status" -UserId ""
Test-Result "HTTP 200 returned" ($g2.StatusCode -eq 200) "Got $($g2.StatusCode)"
if ($g2.Success) {
    Log "  -> Kill-switch: $($g2.Raw)"
}
Log ""


# +====================================================================+
# |  SUMMARY                                                            |
# +====================================================================+
Log ""
Log "============================================================================"
Log "  RESULTS SUMMARY"
Log "============================================================================"
Log "  PASS: $pass"
Log "  FAIL: $fail"
Log "  SKIP: $skip"
Log "  TOTAL: $($pass + $fail + $skip)"
Log ""
if ($fail -eq 0) {
    Log "  ALL TESTS PASSED"
} else {
    Log "  $fail TEST(S) FAILED -- review details above"
}
Log "  Finished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Log "============================================================================"

# --- Write results to file ---
$results -join "`n" | Set-Content -Path $outputFile -Encoding ASCII
Write-Host ""
Write-Host "Results written to: $outputFile"
