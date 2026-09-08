# 扫描 192.168.137.2-254 的 ping 响应 + 22 端口开放检测
param([string]$Subnet = "192.168.137")
$results = @()
$ping = New-Object System.Net.NetworkInformation.Ping
$tasks = @()
for ($i = 2; $i -lt 255; $i++) {
    $ip = "$Subnet.$i"
    $task = $ping.SendPingAsync($ip, 800)
    $tasks += , @{ ip = $ip; task = $task }
}
[System.Threading.Tasks.Task]::WaitAll(($tasks | ForEach-Object { $_.task }))
foreach ($t in $tasks) {
    if ($t.task.Result.Status -eq [System.Net.NetworkInformation.IPStatus]::Success) {
        # 快速测 22 端口
        $tcp = New-Object System.Net.Sockets.TcpClient
        try {
            $iar = $tcp.BeginConnect($t.ip, 22, $null, $null)
            $ok = $iar.AsyncWaitHandle.WaitOne(500)
            if ($ok -and $tcp.Connected) { $results += "$($t.ip):22-OPEN" }
            else { $results += "$($t.ip):ping-only" }
            $tcp.Close()
        } catch {
            $results += "$($t.ip):ping-only"
        }
    }
}
"SCAN_RESULT: " + ($results -join ' | ')
