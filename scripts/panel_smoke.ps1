param(
    [string]$BaseUrl = "http://127.0.0.1:8765",

    [string]$Path = (Resolve-Path ".").Path
)

$ErrorActionPreference = "Stop"

Write-Host "GET /"
$homeResponse = Invoke-WebRequest -Uri "$BaseUrl/" -UseBasicParsing
if ($homeResponse.StatusCode -ne 200) {
    throw "GET / returned HTTP $($homeResponse.StatusCode)"
}

Write-Host "`nGET /settings-page"
$settingsPage = Invoke-WebRequest -Uri "$BaseUrl/settings-page" -UseBasicParsing
if ($settingsPage.StatusCode -ne 200) {
    throw "GET /settings-page returned HTTP $($settingsPage.StatusCode)"
}

Write-Host "GET /workspaces"
$workspaces = Invoke-RestMethod -Uri "$BaseUrl/workspaces"
$workspaces | ConvertTo-Json -Depth 8

if (-not $workspaces.data -or $workspaces.data.Count -eq 0) {
    Write-Host "`nPOST /workspaces"
    $workspacePayload = @{
        path = $Path
    } | ConvertTo-Json -Depth 5 -Compress
    $workspaceBody = [System.Text.Encoding]::UTF8.GetBytes($workspacePayload)
    $createdWorkspace = Invoke-RestMethod `
        -Uri "$BaseUrl/workspaces" `
        -Method Post `
        -ContentType "application/json; charset=utf-8" `
        -Body $workspaceBody
    $createdWorkspace | ConvertTo-Json -Depth 8
    $workspaces = Invoke-RestMethod -Uri "$BaseUrl/workspaces"
}

if (-not $workspaces.data -or $workspaces.data.Count -eq 0) {
    throw "No workspaces available after create."
}

Write-Host "`nGET /settings"
$settings = Invoke-RestMethod -Uri "$BaseUrl/settings"
$settings | ConvertTo-Json -Depth 8

$workspaceId = $workspaces.data[0].id

Write-Host "`nPOST /conversations"
$conversationPayload = @{
    workspace_id = $workspaceId
    title = "Panel smoke"
} | ConvertTo-Json -Depth 5 -Compress
$conversationBody = [System.Text.Encoding]::UTF8.GetBytes($conversationPayload)
$conversation = Invoke-RestMethod `
    -Uri "$BaseUrl/conversations" `
    -Method Post `
    -ContentType "application/json; charset=utf-8" `
    -Body $conversationBody
$conversation | ConvertTo-Json -Depth 8

if (-not $conversation.data.id) {
    throw "Conversation was not created."
}
