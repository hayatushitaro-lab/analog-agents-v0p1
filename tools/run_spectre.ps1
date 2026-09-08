# run_spectre.ps1 — 远程驱动虚拟机 Spectre 的通用脚本（WA 项目工具）
# 用法:
#   .\tools\run_spectre.ps1 -Netlist .\testbench\tb_xxx.scs [-RemoteDir /home/IC/wa_sim] [-OutDir .\sim_raw] [-NoDownload]
# 行为:
#   1) SCP 网表 + wrapper .sh 到虚拟机
#   2) 以 IC 用户运行: spectre -format psfascii <name>.scs (模型 include + corner 由网表内指定)
#   3) 取回 stdout 日志到 $OutDir/<name>.log, PSF 目录到 $OutDir/<name>/
# 依赖: 本机 ssh.exe + 私钥(~\.ssh\analog_eda) 免密登录 root@192.168.16.128
param(
  [Parameter(Mandatory=$true)][string]$Netlist,
  [string]$RemoteDir = "/home/IC/wa_sim",
  [string]$OutDir,
  [switch]$NoDownload
)
$ErrorActionPreference = "Continue"

$waRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $waRoot "sim_raw" }

# ---- 读取 servers.yml runtime 段 ----
$serversYml = Get-Content (Join-Path $waRoot "servers.yml") -Raw
function YamlVal([string]$yml, [string]$key) {
  foreach ($line in ($yml -split "`n")) {
    if ($line -match "^\s*${key}:\s*(.*)$") {
      $val = $Matches[1] -replace '\s*#.*$',''
      return $val.Trim().Trim('"').Replace('\\','\')
    }
  }
  return $null
}
$sshHost    = YamlVal $serversYml "ssh_host"
$sshKey     = YamlVal $serversYml "ssh_key"
$spectre    = YamlVal $serversYml "remote_spectre"
$remoteUser = YamlVal $serversYml "run_as_user"
if (-not $sshHost -or -not $sshKey) { throw "servers.yml runtime misses ssh_host/ssh_key" }

# ---- 路径 ----
$Netlist    = (Resolve-Path $Netlist).Path
$name       = [System.IO.Path]::GetFileNameWithoutExtension($Netlist)
$remoteFile = "$RemoteDir/${name}.scs"
$wrapper    = "$RemoteDir/_run_${name}.sh"
$logLocal   = Join-Path $OutDir "${name}.log"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# ---- wrapper (remote, IC user, ASCII only) ----
$wrapBody = "#!/bin/bash`nset +e`nmkdir -p $RemoteDir`ncd $RemoteDir`n$spectre -format psfascii ${name}.scs`necho WRAPPER_EXIT=`$?`n"
$wrapLocal = Join-Path $env:TEMP "_run_${name}.sh"
[System.IO.File]::WriteAllText($wrapLocal, $wrapBody)

# ---- prepare remote dir (owned by IC so spectre can write output) ----
& ssh -i $sshKey -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $sshHost "mkdir -p $RemoteDir && chown -R ${remoteUser}:${remoteUser} $RemoteDir" 2>&1 | Out-Null

# ---- upload netlist + wrapper (+ circuit dir so relative includes resolve) ----
Write-Host "[run_spectre] upload $Netlist -> ${sshHost}:${remoteFile}"
& scp -i $sshKey -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $Netlist "${sshHost}:${remoteFile}" 2>&1 | Out-Null
& scp -i $sshKey -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $wrapLocal "${sshHost}:${wrapper}" 2>&1 | Out-Null
$localCircuit = Join-Path $waRoot "circuit"
if (Test-Path $localCircuit) {
  Write-Host "[run_spectre] upload circuit/ -> ${RemoteDir}/circuit"
  & scp -i $sshKey -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -r "$localCircuit" "${sshHost}:${RemoteDir}/" 2>&1 | Out-Null
}

# ---- run spectre via su (load IC login env) ----
Write-Host "[run_spectre] run spectre ${name} as $remoteUser @ $sshHost"
$runOut = @(& ssh -i $sshKey -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $sshHost "su - ${remoteUser} -c 'bash ${wrapper}'" 2>&1)
$runOut | Tee-Object -FilePath $logLocal

# ---- download results ----
if (-not $NoDownload) {
  $candidates = @("$RemoteDir/$name.raw", "$RemoteDir/$name.scs.raw")
  $remoteOut = $null
  foreach ($c in $candidates) {
    $isDir = ((& ssh -i $sshKey -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $sshHost "test -d '$c' && echo YES || echo NO" 2>&1) -join "`n").Contains('YES')
    if ($isDir) { $remoteOut = $c; break }
  }
  if ($remoteOut) {
    $localOut = Join-Path $OutDir $name
    New-Item -ItemType Directory -Force -Path $localOut | Out-Null
    Write-Host "[run_spectre] download psf -> $localOut"
    & scp -i $sshKey -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -r "${sshHost}:${remoteOut}/." "$localOut/" 2>&1 | Out-Null
  } else {
    Write-Host "[run_spectre] no result dir found for $name (sim may have failed)"
  }
}

$runExit = 0
if (($runOut -join "`n") -match 'WRAPPER_EXIT=(\d+)') { $runExit = [int]$Matches[1] }
Write-Host "[run_spectre] done. log=$logLocal spectre-exit=$runExit"
exit $runExit
