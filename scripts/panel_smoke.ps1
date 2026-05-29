param(
    [string]$BaseUrl = "http://127.0.0.1:8765"
)

$ErrorActionPreference = "Stop"

Write-Host "GET /workspaces"
$workspaces = Invoke-RestMethod -Uri "$BaseUrl/workspaces"
$workspaces | ConvertTo-Json -Depth 8

if (-not $workspaces.data -or $workspaces.data.Count -eq 0) {
    throw "No workspaces returned."
}

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

$conversationId = $conversation.data.id

Write-Host "`nPOST /conversations/{id}/messages"
$messagePayload = @{
    content = "扫描目录"
} | ConvertTo-Json -Depth 5 -Compress
$messageBody = [System.Text.Encoding]::UTF8.GetBytes($messagePayload)
Invoke-RestMethod `
    -Uri "$BaseUrl/conversations/$conversationId/messages" `
    -Method Post `
    -ContentType "application/json; charset=utf-8" `
    -Body $messageBody |
    ConvertTo-Json -Depth 10
