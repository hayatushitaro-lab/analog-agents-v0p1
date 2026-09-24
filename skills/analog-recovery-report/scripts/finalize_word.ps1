#Requires -Version 7.0
param([Parameter(Mandatory=$true)][string]$Draft,
      [Parameter(Mandatory=$true)][string]$OutputDirectory,
      [ValidateRange(10,600)][int]$TimeoutSeconds=120,
      [switch]$Worker)
$ErrorActionPreference = 'Stop'
if (-not $Worker) {
    # Use the already selected PowerShell 7 host, never Windows powershell.exe.
    # A hung COM activation cannot leave an unbounded shell wait. Only this
    # child is terminated on timeout; existing Word processes are never killed.
    if (Test-Path -LiteralPath $OutputDirectory) { throw 'Use a new output directory.' }
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = Join-Path $PSHOME 'pwsh.exe'
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $start.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
    foreach ($arg in @('-NoProfile','-File',$PSCommandPath,'-Draft',$Draft,'-OutputDirectory',$OutputDirectory,'-Worker')) {
        $start.ArgumentList.Add($arg)
    }
    $child = [System.Diagnostics.Process]::new()
    $child.StartInfo = $start
    $null = $child.Start()
    $stdout = $child.StandardOutput.ReadToEndAsync()
    $stderr = $child.StandardError.ReadToEndAsync()
    if (-not $child.WaitForExit($TimeoutSeconds * 1000)) {
        $child.Kill()
        $null = $child.WaitForExit(5000)
        $message = 'Word export timed out. Draft only; do not retry automatically or terminate existing Word processes.'
        if (Test-Path -LiteralPath $OutputDirectory) {
            @{status='failed'; reason=$message; worker_pid=$child.Id} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputDirectory 'render_status.json') -Encoding utf8
        }
        throw $message
    }
    $resultOut = $stdout.GetAwaiter().GetResult()
    $resultErr = $stderr.GetAwaiter().GetResult()
    if ($child.ExitCode -ne 0) { throw "Word export failed: $resultErr" }
    Write-Output $resultOut
    return
}
$source = (Resolve-Path -LiteralPath $Draft).Path
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Use a new output directory; never mix preview versions.' }
$dest = New-Item -ItemType Directory -Path $OutputDirectory
$docPath = Join-Path $dest.FullName 'report.docx'
$pdfPath = Join-Path $dest.FullName 'report.pdf'
Copy-Item -LiteralPath $source -Destination $docPath
$word = New-Object -ComObject Word.Application
if ($word.Documents.Count -ne 0) {
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
    throw 'Word returned an application with existing documents. Do not reuse this session.'
}
$word.Visible = $false
$word.DisplayAlerts = 0
$doc = $null
try {
    $doc = $word.Documents.Open($docPath, $false, $false, $false)
    $doc.Fields.Update() | Out-Null
    for ($pass=0; $pass -lt 2; $pass++) {
        $doc.Repaginate()
        foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
    }
    $doc.Save()
    $doc.ExportAsFixedFormat($pdfPath, 17)
    $doc.Close($false)
    $doc = $null
} finally {
    if ($null -ne $doc) { $doc.Close($false) }
    $word.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
}
@{status='exported_requires_visual_review'; docx=$docPath; pdf=$pdfPath} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dest.FullName 'render_status.json') -Encoding utf8
Write-Output $pdfPath
