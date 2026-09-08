# tools/review_opencode.ps1
# Cross-model review via opencode-go-anthropic channel (Anthropic Messages).
# ASCII-only source (PowerShell 5.1 lacks BOM tolerance). Uses a prebuilt prompt file.
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools/review_opencode.ps1 \
#     -PromptFile <path> -Out <path> [-MaxTokens N] [-Log <path>]
param(
  [Parameter(Mandatory=$true)][string]$PromptFile,
  [string]$Out = "verifier-reports/cross-model-review.md",
  [int]$MaxTokens = 4000,
  [string]$Log = ""
)

$ErrorActionPreference = "Stop"
$endpoint = "https://opencode.ai/zen/go/v1/messages"
$model = "minimax-m3"

function Write-Line($m) { Write-Host $m; if ($Log) { Add-Content -Path $Log -Value $m } }

# --- load key from Reasonix .env (Select-String pattern, verified working) ---
$key = ""
$envFile = Join-Path $env:APPDATA "reasonix\.env"
if (Test-Path -LiteralPath $envFile) {
  $m = Select-String -LiteralPath $envFile -Pattern "OPENCODE_GO_API_KEY=(.+)" -ErrorAction SilentlyContinue
  if ($m) { $key = $m[0].Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'") }
}
if (-not $key) { Write-Line "ERROR: OPENCODE_GO_API_KEY not found in $envFile"; exit 1 }

Write-Line "[review] loaded key (len=$($key.Length))"
$absPrompt = if ([System.IO.Path]::IsPathRooted($PromptFile)) { $PromptFile } else { Join-Path (Get-Location) $PromptFile }
Write-Line "[review] prompt file abs: $absPrompt"
$prompt = Get-Content -Raw -LiteralPath $absPrompt
Write-Line "[review] prompt chars: $($prompt.Length)"

function Json-Esc($s) {
  $sb = New-Object System.Text.StringBuilder
  foreach ($ch in $s.ToCharArray()) {
    switch ($ch) {
      '\\' { [void]$sb.Append('\\') }
      '"'  { [void]$sb.Append('\"') }
      ([char]10) { [void]$sb.Append('\n') }
      ([char]13) { [void]$sb.Append('\r') }
      ([char]9)  { [void]$sb.Append('\t') }
      default { [void]$sb.Append($ch) }
    }
  }
  return $sb.ToString()
}

$escContent = Json-Esc $prompt
$body = '{"model":"' + $model + '","max_tokens":' + $MaxTokens + ',"temperature":0.1,"messages":[{"role":"user","content":"' + $escContent + '"}]}'
Write-Line "[review] body bytes: $([Text.Encoding]::UTF8.GetByteCount($body))"

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$resp = $null
try {
  $resp = Invoke-RestMethod -Uri $endpoint -Method Post -Headers @{
    "x-api-key" = $key
    "Content-Type" = "application/json"
    "anthropic-version" = "2023-06-01"
  } -Body $body -TimeoutSec 180
} catch {
  Write-Line "FAIL: $($_.Exception.Message)"
  if ($_.ErrorDetails) { Write-Line $_.ErrorDetails.Message }
  exit 1
}
$sw.Stop()

$text = ""
if ($resp -and $resp.content) {
  $text = ($resp.content | Where-Object { $_.type -eq "text" } | ForEach-Object { $_.text }) -join "`n"
}
Write-Line "[review] done in $([math]::Round($sw.Elapsed.TotalSeconds,1))s, reply chars: $($text.Length)"
if (-not $text) { Write-Line "ERROR: empty text in response"; exit 1 }

# --- parse verdicts ---
$verdicts = @{}
$curDim = $null; $curV = $null; $curR = @()
foreach ($line in $text -split "`n") {
  $t = $line.Trim()
  if ($t -match '^DIMENSION:\s*(.+)$') {
    if ($curDim -and $curV) { $verdicts[$curDim] = @{ verdict = $curV; reasoning = ($curR -join "`n") } }
    $curDim = $matches[1].Trim(); $curV = $null; $curR = @()
  } elseif ($t -match '^VERDICT:\s*([A-Za-z]+)\s*$') {
    $v = $matches[1].ToUpper()
    $curV = if ($v -in @("PASS","WARN","FAIL")) { $v } else { "WARN" }
  } elseif ($t -match '^REASONING:\s*(.+)$') {
    $curR += $matches[1].Trim()
  } elseif ($curDim -and $curV) {
    $curR += $t
  }
}
if ($curDim -and $curV) { $verdicts[$curDim] = @{ verdict = $curV; reasoning = ($curR -join "`n") } }

$names = @( "Connection correctness","Bias soundness","Sizing consistency","Topology risks","Spec achievability" )
$lines = @()
$lines += ("# Cross-Model Review  -  " + [System.IO.Path]::GetFileNameWithoutExtension($PromptFile) + "  -  " + (Get-Date -Format 'yyyy-MM-dd'))
$lines += ""
$lines += "## Reviewer Status"
$lines += "| Reviewer | Status | Latency |"
$lines += "|----------|--------|---------|"
$lines += "| minimax (minimax-m3) | ok | $([math]::Round($sw.Elapsed.TotalSeconds,1))s |"
$lines += ""
$lines += "## Consensus Matrix"
$lines += "| Check | minimax-m3 | Consensus |"
$lines += "|-------|-----------|-----------|"
foreach ($d in $names) {
  $v = if ($verdicts[$d]) { $verdicts[$d].verdict } else { "N/A" }
  $lines += "| $d | $v | $v |"
}
$lines += ""
$lines += "## Verdict Details"
$lines += ""
foreach ($d in $names) {
  if ($verdicts[$d]) {
    $lines += ("### $d  --  " + $verdicts[$d].verdict)
    $lines += ""
    $lines += $verdicts[$d].reasoning
    $lines += ""
  } else {
    $lines += ("### $d  --  N/A (no verdict parsed)")
    $lines += ""
  }
}

$reportText = ($lines -join "`n")
$absOut = if ([System.IO.Path]::IsPathRooted($Out)) { $Out } else { Join-Path (Get-Location) $Out }
$op = Split-Path $absOut -Parent
if ($op -and -not (Test-Path $op)) { New-Item -ItemType Directory -Force -Path $op | Out-Null }
Set-Content -LiteralPath $absOut -Value $reportText -Encoding UTF8
Write-Line "Report written to $absOut"
