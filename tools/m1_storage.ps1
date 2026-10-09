[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('Initialize', 'Inspect', 'DeleteRequest')][string]$Mode = 'Inspect',
    [string]$RequestId
)
$ErrorActionPreference = 'Stop'
$workspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$storageRoot = [System.IO.Path]::GetFullPath((Join-Path $workspaceRoot 'storage/m1'))
if (-not $storageRoot.StartsWith($workspaceRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Storage path escapes the project workspace'
}
if ($Mode -eq 'Initialize') {
    New-Item -ItemType Directory -Path $storageRoot -Force | Out-Null
    $acl = Get-Acl -LiteralPath $storageRoot
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.Access)) { [void]$acl.RemoveAccessRuleSpecific($rule) }
    $sids = @([System.Security.Principal.WindowsIdentity]::GetCurrent().User,
        [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18'),
        [System.Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    foreach ($sid in $sids) {
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new($sid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            [System.Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit',
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow)
        $acl.AddAccessRule($rule)
    }
    if ($PSCmdlet.ShouldProcess($storageRoot, 'Restrict access to current user, SYSTEM and Administrators')) {
        Set-Acl -LiteralPath $storageRoot -AclObject $acl
    }
}
elseif ($Mode -eq 'DeleteRequest') {
    $parsedId = [guid]::Empty
    if (-not [guid]::TryParseExact($RequestId, 'D', [ref]$parsedId)) { throw 'RequestId must be a canonical UUID' }
    $requestsRoot = [System.IO.Path]::GetFullPath((Join-Path $storageRoot 'requests'))
    $requestPath = [System.IO.Path]::GetFullPath((Join-Path $requestsRoot $parsedId.ToString('D')))
    if (-not $requestPath.StartsWith($requestsRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Delete target escapes the requests directory' }
    if (Test-Path -LiteralPath $requestPath) {
        $target = Get-Item -LiteralPath $requestPath
        if ($target.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { throw 'Refuse deletion of a reparse-point request' }
        if (Get-ChildItem -LiteralPath $requestPath -Recurse -Force | Where-Object { $_.Attributes -band [System.IO.FileAttributes]::ReparsePoint }) { throw 'Refuse deletion with nested reparse points' }
        if ($PSCmdlet.ShouldProcess($requestPath, 'Delete controlled request files')) { Remove-Item -LiteralPath $requestPath -Recurse -Force }
    }
}
$currentAcl = Get-Acl -LiteralPath $storageRoot
[pscustomobject]@{storage=$storageRoot; inherited_access_disabled=$currentAcl.AreAccessRulesProtected;
    allowed_principal_count=@($currentAcl.Access).Count; scope='local M1 only; no product authentication'; mode=$Mode} | ConvertTo-Json
