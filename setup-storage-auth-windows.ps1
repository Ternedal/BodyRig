param(
    [string]$StorageHost = "",
    [string]$UserName = "",
    [switch]$ReplaceExisting
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig storage credential bootstrap is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required." }

$configDir = Join-Path $env:LOCALAPPDATA "BodyRig\config"
$stashConfigPath = Join-Path $configDir "stash.json"
$storageConfigPath = Join-Path $configDir "storage.json"
New-Item -ItemType Directory -Path $configDir -Force | Out-Null

function Resolve-StorageHost {
    param([string]$Explicit)
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) {
        $candidate = $Explicit.Trim().TrimStart('\\').Split('\\')[0]
        if ($candidate -notmatch '^[A-Za-z0-9._:-]+$') { throw "Storage host contains unsupported characters." }
        return $candidate
    }
    if (-not (Test-Path -LiteralPath $stashConfigPath -PathType Leaf)) {
        throw "Storage host was not supplied and saved Stash configuration is missing."
    }
    try { $stash = Get-Content -LiteralPath $stashConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "Saved Stash configuration is unreadable JSON." }
    if ([string]$stash.format -ne "bodyrig-local-stash-config" -or [int]$stash.version -ne 1) {
        throw "Saved Stash configuration has an unexpected format/version."
    }
    try { $uri = [Uri]([string]$stash.url) }
    catch { throw "Saved Stash URL is invalid." }
    if ([string]::IsNullOrWhiteSpace($uri.Host)) { throw "Saved Stash URL has no host." }
    return [string]$uri.Host
}

$StorageHost = Resolve-StorageHost -Explicit $StorageHost
$target = $StorageHost.ToLowerInvariant()

if (-not ("BodyRig.NativeCredentialStore" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace BodyRig {
    public static class NativeCredentialStore {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct CREDENTIAL {
            public UInt32 Flags;
            public UInt32 Type;
            public string TargetName;
            public string Comment;
            public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
            public UInt32 CredentialBlobSize;
            public IntPtr CredentialBlob;
            public UInt32 Persist;
            public UInt32 AttributeCount;
            public IntPtr Attributes;
            public string TargetAlias;
            public string UserName;
        }

        [DllImport("advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool CredWrite([In] ref CREDENTIAL credential, UInt32 flags);

        [DllImport("advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool CredRead(string target, UInt32 type, UInt32 flags, out IntPtr credentialPtr);

        [DllImport("advapi32.dll", EntryPoint = "CredFree", SetLastError = false)]
        private static extern void CredFree(IntPtr buffer);

        public static bool Exists(string target) {
            IntPtr ptr;
            if (!CredRead(target, 2, 0, out ptr)) return false;
            CredFree(ptr);
            return true;
        }

        public static void WriteDomainPassword(string target, string userName, string password) {
            if (String.IsNullOrWhiteSpace(target)) throw new ArgumentException("target");
            if (String.IsNullOrWhiteSpace(userName)) throw new ArgumentException("userName");
            if (password == null) throw new ArgumentNullException("password");
            byte[] bytes = System.Text.Encoding.Unicode.GetBytes(password);
            IntPtr blob = Marshal.AllocCoTaskMem(bytes.Length);
            try {
                Marshal.Copy(bytes, 0, blob, bytes.Length);
                CREDENTIAL credential = new CREDENTIAL();
                credential.Type = 2;       // CRED_TYPE_DOMAIN_PASSWORD
                credential.TargetName = target;
                credential.CredentialBlobSize = (UInt32)bytes.Length;
                credential.CredentialBlob = blob;
                credential.Persist = 2;    // CRED_PERSIST_LOCAL_MACHINE
                credential.UserName = userName;
                if (!CredWrite(ref credential, 0)) {
                    throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                }
            }
            finally {
                byte[] zeros = new byte[bytes.Length];
                Marshal.Copy(zeros, 0, blob, zeros.Length);
                Array.Clear(bytes, 0, bytes.Length);
                Marshal.FreeCoTaskMem(blob);
            }
        }
    }
}
'@
}

$alreadyExists = [BodyRig.NativeCredentialStore]::Exists($target)
if ($alreadyExists -and -not $ReplaceExisting) {
    throw "A Windows domain credential already exists for '$target'. Re-run with -ReplaceExisting only if you intend to replace it."
}

if ([string]::IsNullOrWhiteSpace($UserName)) {
    $credential = Get-Credential -Message "BodyRig SMB login for \\$StorageHost"
} else {
    $credential = Get-Credential -UserName $UserName -Message "BodyRig SMB login for \\$StorageHost"
}
if ($null -eq $credential) { throw "Storage credential entry was cancelled." }

$plainPassword = $null
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($credential.Password)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if ([string]::IsNullOrEmpty($plainPassword)) { throw "Storage password is empty." }
    [BodyRig.NativeCredentialStore]::WriteDomainPassword($target, $credential.UserName, $plainPassword)
} finally {
    $plainPassword = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

$config = [ordered]@{
    format = "bodyrig-local-storage-config"
    version = 1
    host = $StorageHost
    credential_target = $target
    username = $credential.UserName
    credential_store = "windows-credential-manager-domain-password"
    password_persisted_in_config = $false
    updated_utc = [DateTime]::UtcNow.ToString("o")
}
$temp = "$storageConfigPath.tmp-$([Guid]::NewGuid().ToString('N'))"
[IO.File]::WriteAllText($temp, (($config | ConvertTo-Json -Depth 4) + "`n"), [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temp -Destination $storageConfigPath -Force

if (-not [BodyRig.NativeCredentialStore]::Exists($target)) {
    throw "Windows Credential Manager did not retain the SMB credential."
}

Write-Host "BodyRig storage credential: SAVED"
Write-Host "Host:              $StorageHost"
Write-Host "Credential target: $target"
Write-Host "Secret in config:  FALSE"
Write-Host "Next: run .\test-storage-auth-windows.ps1 -PerformerId <id> -ResetConnections -MarkPreReboot to prove a fresh SMB session before reboot."
