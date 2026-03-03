$ErrorActionPreference = "Continue"
$env:AZURE_CLI_DISABLE_CONNECTION_VERIFICATION = "1"

$projectRoot = "C:\Users\EOVBK\Django\Architect\LLMCouncilMGA-Azure"
$stagingDir = "$env:TEMP\llmcouncil-be-quick"
$zipPath = "$env:TEMP\llmcouncil-be-quick.zip"

# Clean staging
if (Test-Path $stagingDir) { Remove-Item $stagingDir -Recurse -Force }
New-Item -ItemType Directory -Path $stagingDir | Out-Null

# Copy backend module
Copy-Item "$projectRoot\backend" "$stagingDir\backend" -Recurse
# Remove __pycache__
Get-ChildItem "$stagingDir" -Directory -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force

# Copy root files
Copy-Item "$projectRoot\run_server.py" "$stagingDir\run_server.py"
Copy-Item "$projectRoot\requirements.txt" "$stagingDir\requirements.txt"
Copy-Item "$projectRoot\startup.sh" "$stagingDir\startup.sh"

Write-Host "Backend staging ready"

# Create ZIP with forward slashes
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, 'Create')
Get-ChildItem $stagingDir -Recurse -File | ForEach-Object {
    $relPath = $_.FullName.Substring($stagingDir.Length + 1).Replace('\', '/')
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, $relPath, 'Optimal') | Out-Null
}
$zip.Dispose()
$zipSize = [math]::Round((Get-Item $zipPath).Length / 1KB, 1)
Write-Host "Backend ZIP: $zipSize KB"

# Deploy
Write-Host "Deploying backend..."
az webapp deploy --name llmcouncil-backend --resource-group rg-llmcouncil --src-path $zipPath --type zip 2>&1 | Select-Object -Last 8

# Cleanup
Remove-Item $stagingDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Backend deployment complete!"
