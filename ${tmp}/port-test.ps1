$targets = @(
  @{ Host = 'git.temporiss.com'; Port = 443; Label = '443 https (public)' },
  @{ Host = '173.249.26.86'; Port = 3022; Label = '3022 gitea-ssh' },
  @{ Host = '173.249.26.86'; Port = 3020; Label = '3020 gitea-http' }
)
foreach ($t in $targets) {
  $r = Test-NetConnection -ComputerName $t.Host -Port $t.Port -WarningAction SilentlyContinue
  Write-Output ("{0} -> TCP reachable: {1}" -f $t.Label, $r.TcpTestSucceeded)
}
