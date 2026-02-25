#!/usr/bin/env pwsh
# ============================================================
# LLM Council MGA - Azure Data Provisioning Script
# Cosmos DB + Azure Blob Storage in the same resource group
# ============================================================
# Reference: https://learn.microsoft.com/en-us/cli/azure/cosmosdb
#            https://learn.microsoft.com/en-us/cli/azure/storage
#
# Usage:
#   .\deploy\setup_cosmos.ps1                          # uses defaults
#   .\deploy\setup_cosmos.ps1 -AccountName myaccount   # custom name
#   .\deploy\setup_cosmos.ps1 -Teardown                # delete everything
# ============================================================

[CmdletBinding()]
param(
    [string]$ResourceGroup   = "rg-llmcouncil",
    [string]$Location        = "eastus",
    [string]$AccountName     = "llmcouncil-cosmos",
    [string]$DatabaseName    = "llm-council",
    [string]$ConversationsCtr = "conversations",
    [string]$MemoryCtr       = "memory",
    [string]$SkillsCtr       = "skills",
    [string]$StorageAccount  = "llmcouncilmga",
    [string]$BlobConversations = "conversations",
    [string]$BlobAttachments  = "attachments",
    [string]$BlobMemory       = "memory",
    [string]$BlobSkills       = "skills",
    [int]   $MaxThroughput   = 1000,
    [switch]$FreeTier,
    [switch]$Teardown,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# -- Helpers ---------------------------------------------------
function Write-Step  { param([string]$msg) Write-Host ("`n>> " + $msg) -ForegroundColor Cyan }
function Write-OK    { param([string]$msg) Write-Host ("  [OK] " + $msg) -ForegroundColor Green }
function Write-Warn  { param([string]$msg) Write-Host ("  [WARN] " + $msg) -ForegroundColor Yellow }
function Write-Cmd   { param([string]$msg) Write-Host ("    " + $msg) -ForegroundColor DarkGray }

# -- Teardown --------------------------------------------------
if ($Teardown) {
    Write-Step "Tearing down Cosmos DB resources"

    Write-Cmd "az cosmosdb sql container delete -a $AccountName -g $ResourceGroup -d $DatabaseName -n $ConversationsCtr --yes"
    if (-not $DryRun) { az cosmosdb sql container delete -a $AccountName -g $ResourceGroup -d $DatabaseName -n $ConversationsCtr --yes 2>$null }

    Write-Cmd "az cosmosdb sql container delete -a $AccountName -g $ResourceGroup -d $DatabaseName -n $MemoryCtr --yes"
    if (-not $DryRun) { az cosmosdb sql container delete -a $AccountName -g $ResourceGroup -d $DatabaseName -n $MemoryCtr --yes 2>$null }

    Write-Cmd "az cosmosdb sql container delete -a $AccountName -g $ResourceGroup -d $DatabaseName -n $SkillsCtr --yes"
    if (-not $DryRun) { az cosmosdb sql container delete -a $AccountName -g $ResourceGroup -d $DatabaseName -n $SkillsCtr --yes 2>$null }

    Write-Cmd "az cosmosdb sql database delete -a $AccountName -g $ResourceGroup -n $DatabaseName --yes"
    if (-not $DryRun) { az cosmosdb sql database delete -a $AccountName -g $ResourceGroup -n $DatabaseName --yes 2>$null }

    Write-Cmd "az cosmosdb delete -n $AccountName -g $ResourceGroup --yes"
    if (-not $DryRun) { az cosmosdb delete -n $AccountName -g $ResourceGroup --yes 2>$null }

    Write-Step "Tearing down Storage Account"
    Write-Cmd "az storage account delete -n $StorageAccount -g $ResourceGroup --yes"
    if (-not $DryRun) { az storage account delete -n $StorageAccount -g $ResourceGroup --yes 2>$null }

    Write-OK "Teardown complete"
    return
}

# -- Pre-flight ------------------------------------------------
Write-Step "Pre-flight checks"

$azVersion = az version --output json 2>$null | ConvertFrom-Json
if (-not $azVersion) {
    Write-Error "Azure CLI not found. Install with: winget install -e --id Microsoft.AzureCLI"
}
Write-OK ("Azure CLI " + $azVersion.'azure-cli')

$account = az account show --output json 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Error "Not logged in. Run: az login"
}
Write-OK ("Subscription: " + $account.name + " (" + $account.id + ")")

# -- 1. Resource Group -----------------------------------------
Write-Step "1/12 - Resource Group"
$rgExists = az group exists --name $ResourceGroup 2>$null
if ($rgExists -eq "true") {
    Write-OK "Resource group '$ResourceGroup' already exists"
} else {
    Write-Cmd "az group create --name $ResourceGroup --location $Location"
    if (-not $DryRun) {
        az group create --name $ResourceGroup --location $Location --output none
        if ($LASTEXITCODE -ne 0) { throw "Failed to create resource group" }
    }
    Write-OK "Created resource group '$ResourceGroup' in $Location"
}

# -- 2. Cosmos DB Account --------------------------------------
Write-Step "2/12 - Cosmos DB Account"

$nameExists = az cosmosdb check-name-exists --name $AccountName 2>$null
if ($nameExists -eq "true") {
    Write-OK "Account '$AccountName' already exists"
} else {
    $createArgs = @(
        "cosmosdb", "create",
        "--name", $AccountName,
        "--resource-group", $ResourceGroup,
        "--kind", "GlobalDocumentDB",
        "--default-consistency-level", "Session",
        "--locations", "regionName=$Location", "failoverPriority=0", "isZoneRedundant=False",
        "--backup-policy-type", "Continuous",
        "--continuous-tier", "Continuous7Days",
        "--enable-automatic-failover", "true",
        "--minimal-tls-version", "Tls12",
        "--public-network-access", "ENABLED",
        "--tags", "project=llm-council"
    )
    if ($FreeTier) {
        $createArgs += @("--enable-free-tier", "true")
    }

    Write-Cmd ("az " + ($createArgs -join " "))
    if (-not $DryRun) {
        az @createArgs --output none
        if ($LASTEXITCODE -ne 0) { throw "Failed to create Cosmos DB account" }
    }
    Write-OK "Created Cosmos DB account '$AccountName' - this may take 5-10 minutes"
}

# -- 3. SQL Database -------------------------------------------
Write-Step "3/12 - SQL Database"

$dbExists = az cosmosdb sql database exists `
    --account-name $AccountName `
    --resource-group $ResourceGroup `
    --name $DatabaseName 2>$null
if ($dbExists -eq "true") {
    Write-OK "Database '$DatabaseName' already exists"
} else {
    Write-Cmd "az cosmosdb sql database create -a $AccountName -g $ResourceGroup -n $DatabaseName"
    if (-not $DryRun) {
        az cosmosdb sql database create `
            --account-name $AccountName `
            --resource-group $ResourceGroup `
            --name $DatabaseName `
            --output none
        if ($LASTEXITCODE -ne 0) { throw "Failed to create database" }
    }
    Write-OK "Created database '$DatabaseName'"
}

# -- 4. Conversations Container --------------------------------
Write-Step "4/12 - Conversations Container"

$ctrExists = az cosmosdb sql container exists `
    --account-name $AccountName `
    --resource-group $ResourceGroup `
    --database-name $DatabaseName `
    --name $ConversationsCtr 2>$null
if ($ctrExists -eq "true") {
    Write-OK "Container '$ConversationsCtr' already exists"
} else {
    Write-Cmd "az cosmosdb sql container create ... --partition-key-path /user_id --max-throughput $MaxThroughput"
    if (-not $DryRun) {
        az cosmosdb sql container create `
            --account-name $AccountName `
            --resource-group $ResourceGroup `
            --database-name $DatabaseName `
            --name $ConversationsCtr `
            --partition-key-path "/user_id" `
            --max-throughput $MaxThroughput `
            --output none
        if ($LASTEXITCODE -ne 0) { throw "Failed to create conversations container" }
    }
    $minRU = [int]($MaxThroughput * 0.1)
    $okMsg = "Created container '$ConversationsCtr' [partition: /user_id, autoscale $minRU-$MaxThroughput RU/s]"
    Write-OK $okMsg
}

# -- 5. Memory Container ---------------------------------------
Write-Step "5/12 - Memory Container"

$memExists = az cosmosdb sql container exists `
    --account-name $AccountName `
    --resource-group $ResourceGroup `
    --database-name $DatabaseName `
    --name $MemoryCtr 2>$null
if ($memExists -eq "true") {
    Write-OK "Container '$MemoryCtr' already exists"
} else {
    Write-Cmd "az cosmosdb sql container create ... --partition-key-path /collection --max-throughput $MaxThroughput"
    if (-not $DryRun) {
        az cosmosdb sql container create `
            --account-name $AccountName `
            --resource-group $ResourceGroup `
            --database-name $DatabaseName `
            --name $MemoryCtr `
            --partition-key-path "/collection" `
            --max-throughput $MaxThroughput `
            --output none
        if ($LASTEXITCODE -ne 0) { throw "Failed to create memory container" }
    }
    $minRU = [int]($MaxThroughput * 0.1)
    $okMsg = "Created container '$MemoryCtr' [partition: /collection, autoscale $minRU-$MaxThroughput RU/s]"
    Write-OK $okMsg
}

# -- 6. Skills Container ----------------------------------------
Write-Step "6/12 - Skills Container"

$skillsExists = az cosmosdb sql container exists `
    --account-name $AccountName `
    --resource-group $ResourceGroup `
    --database-name $DatabaseName `
    --name $SkillsCtr 2>$null
if ($skillsExists -eq "true") {
    Write-OK "Container '$SkillsCtr' already exists"
} else {
    Write-Cmd "az cosmosdb sql container create ... --partition-key-path /skill_name --max-throughput $MaxThroughput"
    if (-not $DryRun) {
        az cosmosdb sql container create `
            --account-name $AccountName `
            --resource-group $ResourceGroup `
            --database-name $DatabaseName `
            --name $SkillsCtr `
            --partition-key-path "/skill_name" `
            --max-throughput $MaxThroughput `
            --output none
        if ($LASTEXITCODE -ne 0) { throw "Failed to create skills container" }
    }
    $minRU = [int]($MaxThroughput * 0.1)
    $okMsg = "Created container '$SkillsCtr' [partition: /skill_name, autoscale $minRU-$MaxThroughput RU/s]"
    Write-OK $okMsg
}

# -- 7. Storage Account ----------------------------------------
Write-Step "7/12 - Storage Account"

$storageExists = az storage account check-name --name $StorageAccount --output json 2>$null | ConvertFrom-Json
if ($storageExists.nameAvailable -eq $false -and $storageExists.reason -eq "AlreadyExists") {
    # Verify it is in our RG
    $stInfo = az storage account show --name $StorageAccount --resource-group $ResourceGroup --output json 2>$null | ConvertFrom-Json
    if ($stInfo) {
        Write-OK "Storage account '$StorageAccount' already exists in $ResourceGroup"
    } else {
        Write-Warn "Storage account '$StorageAccount' exists globally but not in $ResourceGroup - name taken"
    }
} else {
    Write-Cmd "az storage account create --name $StorageAccount --sku Standard_LRS --kind StorageV2"
    if (-not $DryRun) {
        az storage account create `
            --name $StorageAccount `
            --resource-group $ResourceGroup `
            --location $Location `
            --sku Standard_LRS `
            --kind StorageV2 `
            --min-tls-version TLS1_2 `
            --allow-blob-public-access false `
            --output none
        if ($LASTEXITCODE -ne 0) { throw "Failed to create storage account" }
    }
    Write-OK "Created storage account '$StorageAccount' [Standard_LRS, StorageV2, TLS 1.2]"
}

# -- 8. Blob Container (conversations) -------------------------
Write-Step "8/12 - Blob Container ($BlobConversations)"

$blobExists = az storage container exists `
    --name $BlobConversations `
    --account-name $StorageAccount `
    --auth-mode login `
    --output json 2>$null | ConvertFrom-Json
if ($blobExists.exists -eq $true) {
    Write-OK "Blob container '$BlobConversations' already exists"
} else {
    Write-Cmd "az storage container create --name $BlobConversations --account-name $StorageAccount"
    if (-not $DryRun) {
        az storage container create `
            --name $BlobConversations `
            --account-name $StorageAccount `
            --auth-mode login `
            --output none
        if ($LASTEXITCODE -ne 0) { throw "Failed to create blob container '$BlobConversations'" }
    }
    Write-OK "Created blob container '$BlobConversations'"
}

# -- 9. Blob Container (attachments) ----------------------------
Write-Step "9/12 - Blob Container ($BlobAttachments)"

$blobExists = az storage container exists `
    --name $BlobAttachments `
    --account-name $StorageAccount `
    --auth-mode login `
    --output json 2>$null | ConvertFrom-Json
if ($blobExists.exists -eq $true) {
    Write-OK "Blob container '$BlobAttachments' already exists"
} else {
    Write-Cmd "az storage container create --name $BlobAttachments --account-name $StorageAccount"
    if (-not $DryRun) {
        az storage container create `
            --name $BlobAttachments `
            --account-name $StorageAccount `
            --auth-mode login `
            --output none
        if ($LASTEXITCODE -ne 0) { throw "Failed to create blob container '$BlobAttachments'" }
    }
    Write-OK "Created blob container '$BlobAttachments'"
}

# -- 10. Blob Container (memory) --------------------------------
Write-Step "10/12 - Blob Container ($BlobMemory)"

$blobExists = az storage container exists `
    --name $BlobMemory `
    --account-name $StorageAccount `
    --auth-mode login `
    --output json 2>$null | ConvertFrom-Json
if ($blobExists.exists -eq $true) {
    Write-OK "Blob container '$BlobMemory' already exists"
} else {
    Write-Cmd "az storage container create --name $BlobMemory --account-name $StorageAccount"
    if (-not $DryRun) {
        az storage container create `
            --name $BlobMemory `
            --account-name $StorageAccount `
            --auth-mode login `
            --output none
        if ($LASTEXITCODE -ne 0) { throw "Failed to create blob container '$BlobMemory'" }
    }
    Write-OK "Created blob container '$BlobMemory'"
}

# -- 11. Blob Container (skills) --------------------------------
Write-Step "11/12 - Blob Container ($BlobSkills)"

$blobExists = az storage container exists `
    --name $BlobSkills `
    --account-name $StorageAccount `
    --auth-mode login `
    --output json 2>$null | ConvertFrom-Json
if ($blobExists.exists -eq $true) {
    Write-OK "Blob container '$BlobSkills' already exists"
} else {
    Write-Cmd "az storage container create --name $BlobSkills --account-name $StorageAccount"
    if (-not $DryRun) {
        az storage container create `
            --name $BlobSkills `
            --account-name $StorageAccount `
            --auth-mode login `
            --output none
        if ($LASTEXITCODE -ne 0) { throw "Failed to create blob container '$BlobSkills'" }
    }
    Write-OK "Created blob container '$BlobSkills'"
}

# -- 12. Retrieve Keys -----------------------------------------
Write-Step "12/12 - Connection Details"

if (-not $DryRun) {
    $keys = az cosmosdb keys list `
        --name $AccountName `
        --resource-group $ResourceGroup `
        --output json 2>$null | ConvertFrom-Json

    $acctInfo = az cosmosdb show `
        --name $AccountName `
        --resource-group $ResourceGroup `
        --output json 2>$null | ConvertFrom-Json

    $endpoint = $acctInfo.documentEndpoint

    Write-Host ""
    Write-Host "  ==========================================================" -ForegroundColor Green
    Write-Host "  |  Add these to your .env file:                          |" -ForegroundColor Green
    Write-Host "  ==========================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  COSMOS_ENDPOINT=$endpoint" -ForegroundColor White
    Write-Host ("  COSMOS_KEY=" + $keys.primaryMasterKey) -ForegroundColor White
    Write-Host "  COSMOS_DATABASE=$DatabaseName" -ForegroundColor White
    Write-Host "  COSMOS_CONVERSATIONS_CONTAINER=$ConversationsCtr" -ForegroundColor White
    Write-Host "  COSMOS_MEMORY_CONTAINER=$MemoryCtr" -ForegroundColor White
    Write-Host "  COSMOS_SKILLS_CONTAINER=$SkillsCtr" -ForegroundColor White
    Write-Host ""

    # Storage Account connection string
    $storageConn = az storage account show-connection-string `
        --name $StorageAccount `
        --resource-group $ResourceGroup `
        --output tsv 2>$null

    Write-Host "  AZURE_STORAGE_CONNECTION_STRING=$storageConn" -ForegroundColor White
    Write-Host "  AZURE_BLOB_CONVERSATIONS_CONTAINER=$BlobConversations" -ForegroundColor White
    Write-Host "  AZURE_BLOB_ATTACHMENTS_CONTAINER=$BlobAttachments" -ForegroundColor White
    Write-Host "  AZURE_BLOB_MEMORY_CONTAINER=$BlobMemory" -ForegroundColor White
    Write-Host "  AZURE_BLOB_SKILLS_CONTAINER=$BlobSkills" -ForegroundColor White
    Write-Host ""
} else {
    Write-Warn "DryRun - skipping key retrieval"
}

Write-Host ""
Write-Host "[DONE] Cosmos DB + Storage Account provisioning complete!" -ForegroundColor Green
