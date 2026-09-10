# Persistent storage authentication

BodyRig must not treat an SMB login as fixed merely because the current Windows session can read a share.

## Authority model

The saved Stash API credential and the SMB storage credential are separate authorities:

- Stash API: `%LOCALAPPDATA%\BodyRig\config\stash.json`, API key protected with Windows DPAPI.
- Storage SMB: Windows Credential Manager `CRED_TYPE_DOMAIN_PASSWORD` for the **exact host used by the saved Stash URL**.
- `storage.json` contains only non-secret metadata. The SMB password is never written to the repository, BodyRig JSON evidence, command-line arguments, or logs.

BodyRig deliberately refuses host alias drift. If Stash uses `192.168.1.21`, the SMB credential target and generated UNC roots also use `192.168.1.21`. If Stash later changes to a hostname, re-bootstrap storage authentication for that exact host.

## One-time bootstrap

Run from a clean BodyRig checkout on Windows:

```powershell
.\setup-storage-auth-windows.ps1
```

The operator opens Windows' secure credential prompt. Enter the storage account used for the Stash server's SMB shares. No password is passed through `cmdkey`, `net use`, Git, JSON, or process arguments.

Then prove that the credential works after removing the current SMB session and reading a real Stash-referenced source:

```powershell
.\test-storage-auth-windows.ps1 `
  -PerformerId '42' `
  -ResetConnections `
  -MarkPreReboot
```

PASS requires all of the following:

1. the Windows Credential Manager domain-password entry exists for the exact Stash host;
2. existing SMB connections to that host are removed;
3. `configure-stash-path-map.ps1` can rediscover readable SMB mappings without a credential prompt;
4. `bodyrig.stash_cli probe` can FFmpeg-decode a real source belonging to the requested Stash performer;
5. no secret is persisted in the proof files.

## Reboot qualification

A pre-reboot PASS does **not** close the problem. Reboot Windows and, without opening Explorer or manually entering a storage password, run:

```powershell
.\verify-storage-auth-after-reboot.ps1 -PerformerId '42'
```

The verifier checks that Windows has genuinely booted since the pre-reboot proof, performs the real Stash-source test with no credential prompt, and records that unique Windows boot.

After the first successful reboot the state is only `PARTIAL (1/2)`. Reboot Windows a second time and run the same verifier again. Only two distinct successful post-bootstrap boots produce:

```text
BodyRig persistent storage authentication: QUALIFIED
Cold boots passed:    2/2
Credential prompts:   0
Real Stash decode:    PASS
```

Check progress at any time:

```powershell
.\storage-auth-status.ps1 -PerformerId '42'
```

## Definition of done

Persistent storage authentication is **not solved** until `storage-auth-status.ps1` reports `QUALIFIED` after two distinct Windows boots. A current-session share login, a readable Explorer window, a cached SMB session, or a successful Credential Manager write alone is insufficient evidence.
