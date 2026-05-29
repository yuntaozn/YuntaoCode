param(
    [string]$BaseUrl = "http://127.0.0.1:8765",

    [string]$Path = (Resolve-Path ".").Path
)

$ErrorActionPreference = "Stop"

try {
    $uri = [Uri]$BaseUrl
    $client = New-Object System.Net.Sockets.TcpClient
    $asyncResult = $client.BeginConnect($uri.Host, $uri.Port, $null, $null)
    if (-not $asyncResult.AsyncWaitHandle.WaitOne(1000, $false)) {
        $client.Close()
        throw "timeout"
    }
    $client.EndConnect($asyncResult)
    $client.Close()
}
catch {
    throw "Cannot connect to $BaseUrl. Start runtime.app in another PowerShell window first: python -m runtime.app --host 127.0.0.1 --port 8765 --workspace D:\code"
}

Write-Host "GET /health"
Invoke-RestMethod -Uri "$BaseUrl/health" | ConvertTo-Json -Depth 5

Write-Host "`nGET /tools"
Invoke-RestMethod -Uri "$BaseUrl/tools" | ConvertTo-Json -Depth 8

Write-Host "`nPOST /tasks filesystem.scan_folder"
$payload = @{
    tool = "filesystem.scan_folder"
    input = @{
        path = $Path
        max_depth = 1
    }
    wait = $true
}
$json = $payload | ConvertTo-Json -Depth 8 -Compress
$body = [System.Text.Encoding]::UTF8.GetBytes($json)

Invoke-RestMethod `
    -Uri "$BaseUrl/tasks" `
    -Method Post `
    -ContentType "application/json; charset=utf-8" `
    -Body $body |
    ConvertTo-Json -Depth 8
