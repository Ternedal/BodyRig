Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig native storage credential helper is Windows-only."
}

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

        [DllImport("advapi32.dll", EntryPoint = "CredGetSessionTypes", SetLastError = true)]
        private static extern bool CredGetSessionTypes(UInt32 maximumPersistCount, [Out] UInt32[] maximumPersist);

        public static bool Exists(string target) {
            IntPtr ptr;
            if (!CredRead(target, 2, 0, out ptr)) return false;
            CredFree(ptr);
            return true;
        }

        public static UInt32 MaxDomainPasswordPersist() {
            UInt32[] values = new UInt32[7];
            if (!CredGetSessionTypes((UInt32)values.Length, values)) {
                throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            }
            return values[2];
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

function Test-BodyRigDomainCredential {
    param([Parameter(Mandatory = $true)][string]$Target)
    return [BodyRig.NativeCredentialStore]::Exists($Target)
}

function Get-BodyRigDomainCredentialMaxPersist {
    return [BodyRig.NativeCredentialStore]::MaxDomainPasswordPersist()
}

function Set-BodyRigDomainCredential {
    param(
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$UserName,
        [Parameter(Mandatory = $true)][securestring]$Password
    )
    $plain = $null
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password)
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        if ([string]::IsNullOrEmpty($plain)) { throw "Storage password is empty." }
        [BodyRig.NativeCredentialStore]::WriteDomainPassword($Target, $UserName, $plain)
    } finally {
        $plain = $null
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}
