#Requires -Version 5.1
param([string]$Draft,[string]$OutputDirectory,[string]$OwnerFile,
      [ValidateSet('pdf','preview','cleanup')][string]$Mode='pdf')
$ErrorActionPreference='Stop'
if ($Mode -eq 'cleanup') {
    $owner=Get-Content -LiteralPath $OwnerFile -Raw | ConvertFrom-Json
    $proc=Get-Process -Id $owner.pid -ErrorAction SilentlyContinue
    if ($proc -and $proc.ProcessName -eq 'WINWORD' -and $proc.StartTime.ToUniversalTime().Ticks.ToString() -eq $owner.start_ticks) {
        Stop-Process -Id $proc.Id
    }
    exit
}
if (Test-Path -LiteralPath $OutputDirectory) {throw 'Use a new attempt directory.'}
$dest=New-Item -ItemType Directory -Path $OutputDirectory
$docPath=Join-Path $dest.FullName 'report.docx'
Copy-Item -LiteralPath (Resolve-Path -LiteralPath $Draft).Path -Destination $docPath
$existing=@(Get-Process WINWORD -ErrorAction SilentlyContinue | ForEach-Object {$_.Id})
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class WordOwner { [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId); }'
$word=$null;$doc=$null;$probeDoc=$null;$owned=$false
try {
    $word=New-Object -ComObject Word.Application
    if ($word.Documents.Count -ne 0) {throw 'Word session already contains documents.'}
    # Word exposes Hwnd on Window, not Application. Create only our blank
    # probe document, associate its window to the process, then close it.
    $probeDoc=$word.Documents.Add()
    [uint32]$wordProcessId=0
    [void][WordOwner]::GetWindowThreadProcessId([IntPtr]$probeDoc.ActiveWindow.Hwnd,[ref]$wordProcessId)
    if ($wordProcessId -eq 0 -or $existing -contains $wordProcessId) {throw 'Dedicated Word ownership not established; existing session left untouched.'}
    $proc=Get-Process -Id $wordProcessId
    $owned=$true
    @{pid=$wordProcessId;start_ticks=$proc.StartTime.ToUniversalTime().Ticks.ToString()} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dest.FullName 'owned-word.json') -Encoding UTF8
    $probeDoc.Close($false);$probeDoc=$null
    $word.Visible=$false;$word.DisplayAlerts=0
    $doc=$word.Documents.Open($docPath,$false,$false,$false)
    $doc.Fields.Update() | Out-Null
    foreach ($section in $doc.Sections) {
        foreach ($header in $section.Headers) {$header.Range.Fields.Update() | Out-Null}
        foreach ($footer in $section.Footers) {$footer.Range.Fields.Update() | Out-Null}
    }
    for ($i=0;$i -lt 2;$i++) {
        $doc.Repaginate()
        foreach ($toc in $doc.TablesOfContents) {$toc.Update()}
    }
    # Word emits an empty field-end paragraph after the TOC. A full TOC can
    # push that paragraph alone onto a page before the chapter page break.
    # Compact only this empty structural paragraph, never the TOC entries.
    foreach ($toc in $doc.TablesOfContents) {
        $tail=$doc.Range($toc.Range.End,[Math]::Min($toc.Range.End+1,$doc.Content.End)).Paragraphs.Item(1).Range
        if (($tail.Text -replace '[\s\x13\x14\x15]','').Length -eq 0) {
            $tail.Font.Size=1
            $tail.ParagraphFormat.SpaceBefore=0
            $tail.ParagraphFormat.SpaceAfter=0
            $tail.ParagraphFormat.LineSpacingRule=4
            $tail.ParagraphFormat.LineSpacing=1
        }
    }
    $doc.Repaginate()
    foreach ($toc in $doc.TablesOfContents) {$toc.UpdatePageNumbers()}
    # Update page totals after TOC/layout changes, not only before pagination.
    foreach ($section in $doc.Sections) {
        foreach ($header in $section.Headers) {$header.Range.Fields.Update() | Out-Null}
        foreach ($footer in $section.Footers) {$footer.Range.Fields.Update() | Out-Null}
    }
    $doc.Save();$doc.Close($false);$doc=$null
    # Reopen the saved copy: preview must correspond to the actual delivered file.
    $doc=$word.Documents.Open($docPath,$false,$true,$false)
    $pageCount=$doc.ComputeStatistics(2)
    $fieldChecks=@()
    foreach ($section in $doc.Sections) {
        foreach ($footer in $section.Footers) {
            foreach ($field in $footer.Range.Fields) {
                if ($field.Code.Text.Trim() -eq 'NUMPAGES') {
                    $value=$field.Result.Text.Trim()
                    $fieldChecks+=@{field='NUMPAGES';value=$value}
                    if ($value -ne $pageCount.ToString()) {throw 'Cached total page count differs from layout; retain draft for repair.'}
                }
            }
        }
    }
    @{page_count=$pageCount;fields=$fieldChecks;dpi=150} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $dest.FullName 'render_details.json') -Encoding UTF8
    if ($Mode -eq 'pdf') {$doc.ExportAsFixedFormat((Join-Path $dest.FullName 'report.pdf'),17)}
    else {
        Add-Type -AssemblyName System.Drawing
        $doc.ActiveWindow.View.Type=3
        $pages=$doc.ActiveWindow.Panes.Item(1).Pages
        $maxWidth=0;$maxHeight=0
        foreach ($section in $doc.Sections) {
            $maxWidth=[Math]::Max($maxWidth,$section.PageSetup.PageWidth)
            $maxHeight=[Math]::Max($maxHeight,$section.PageSetup.PageHeight)
        }
        $width=[int][Math]::Ceiling($maxWidth*150/72);$height=[int][Math]::Ceiling($maxHeight*150/72)
        if ([long]$width*$height -gt 12000000) {throw 'Page exceeds pixel budget.'}
        for ($i=1;$i -le $pages.Count;$i++) {
            $stream=$null;$image=$null;$bitmap=$null;$graphics=$null
            try {
                [byte[]]$bits=$pages.Item($i).EnhMetaFileBits
                $stream=New-Object System.IO.MemoryStream(,$bits)
                $image=[System.Drawing.Image]::FromStream($stream)
                $bitmap=New-Object System.Drawing.Bitmap($width,$height)
                $bitmap.SetResolution(150,150)
                $graphics=[System.Drawing.Graphics]::FromImage($bitmap)
                $graphics.Clear([System.Drawing.Color]::White)
                $graphics.DrawImage($image,0,0,$width,$height)
                $bitmap.Save((Join-Path $dest.FullName ('page{0:D2}.png' -f $i)),[System.Drawing.Imaging.ImageFormat]::Png)
            } finally {
                if ($graphics) {$graphics.Dispose()};if ($bitmap) {$bitmap.Dispose()}
                if ($image) {$image.Dispose()};if ($stream) {$stream.Dispose()}
            }
        }
    }
} finally {
    if ($probeDoc) {$probeDoc.Close($false)}
    if ($owned) {
        if ($doc) {$doc.Close($false)}
        if ($word) {$word.Quit()}
    }
    if ($word) {[void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)}
}
