# OTA 远程仿真脚本(run_remote):上传网表 -> ssh spectre -> 下载 psfascii 结果
# 复用 pump 项目链路:ssh IC@192.168.137.129 (免密)
# 用法:
#   powershell -File run_remote.ps1 -Netlist tb.scs -RemoteDir /home/IC/project/sim/ota
param(
    [string]$Netlist = "tb.scs",
    [string]$RemoteDir = "/home/IC/project/sim/ota",
    [string]$SshHost = "IC@192.168.137.130"
)

$ErrorActionPreference = "Stop"

$localName = Split-Path -Leaf $Netlist
$baseName = [System.IO.Path]::GetFileNameWithoutExtension($localName)

Write-Host "[run_remote] 上传 $Netlist -> ${SshHost}:${RemoteDir}/"
ssh $SshHost "mkdir -p $RemoteDir" 2>&1 | Out-Null
scp $Netlist "${SshHost}:${RemoteDir}/${localName}" 2>&1 | Out-Null

Write-Host "[run_remote] 远程 spectre 仿真..."
$cmd = "cd $RemoteDir && spectre $localName -format psfascii +log ${baseName}.log 2>&1 | tail -20"
ssh $SshHost $cmd

Write-Host "[run_remote] 下载 psfascii 结果..."
scp -r "${SshHost}:${RemoteDir}/${baseName}.raw" . 2>&1 | Out-Null

Write-Host "[run_remote] 完成。结果目录: ./${baseName}.raw"
Write-Host "[run_remote] 下一步: python parse_margin.py ./${baseName}.raw spec.yml -o margin-report.md"
