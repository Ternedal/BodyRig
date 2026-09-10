# Persistent storage authentication

BodyRig must not treat an SMB login as fixed merely because the current Windows session can read a share.

## Authority model

The saved Stash API credential and the SMB storage credential are separate authorities:

- Stash API: `%LOCALAPPDATA%\BodyRig\config\stash.json`, API key protected with Windows DPAPI.
- Storage SMB: Windows Credential Manager `CRED_TYPE_DOMAIN_PASSWORD` for the **exact host used by the saved Stash URL**.
- `storage.json` contains only non-secret metadata. The SMB password is never written to the repository, BodyRig JSON evidence, command-line arguments, or logs.
- Every storage credential bootstrap creates a new `credential_generation`. Session, pre-reboot and cold-boot proofs must all bind that exact generation.

BodyRig deliberately refuses host alias drift. If Stash uses `192.168.1.21`, the SMB credential target and generated UNC roots also use `192.168.1.21`. If Stash later changes to a hostname, re-bootstrap storage authentication for that exact host.

Replacing a credential invalidates all existing storage qualification proofs, even when the hostname and username remain unchanged. A password change therefore always starts a new reboot-qualification cycle.

## One-time bootstrap

Run from a clean BodyRig checkout on Windows:

```powershell
.\setup-storage-auth-windows.ps1
```

The operator opens Windows' secure credential prompt. Enter the storage account used for the Stash server's SMB shares. No password is passed through `cmdkey`, `net use`, Git, JSON, or process arguments. BodyRig also asks Windows for the maximum persistence allowed for domain-password credentials and refuses to claim reboot persistence unless `LOCAL_MACHINE` (2) or stronger is supported.

Then prove that the credential works after removing the current SMB session and reading a real Stash-referenced source:

```powershell
.\test-storage-auth-windows.ps1 `
  -PerformerId '42' `
  -ResetConnections `
  -MarkPreReboot
```

PASS requires all of the following:

1. the Windows Credential Manager domain-password entry exists for the exact Stash host;
2. the credential generation is canonical and current;
3. existing SMB connections to that host are removed;
4. `configure-stash-path-map.ps1` can rediscover readable SMB mappings without a credential prompt;
5. `bodyrig.stash_cli probe` can FFmpeg-decode a real source belonging to the requested Stash performer;
6. no secret is persisted in the proof files.

Starting a new `-MarkPreReboot` baseline resets any previous cold-boot counter.

## Reboot qualification

A pre-reboot PASS does **not** close the problem. Reboot Windows and, without opening Explorer or manually entering a storage password, run:

```powershell
.\verify-storage-auth-after-reboot.ps1 -PerformerId '42'
```

The verifier checks that Windows has genuinely booted since the pre-reboot proof, that the current `storage.json`, pre-reboot receipt and new session receipt all bind the same credential generation, then performs the real Stash-source test with no credential prompt and records that unique Windows boot.

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

The canonical performer preflight also enforces this state:

```powershell
.\bodyrig-status.ps1 -PerformerId '42' -BodyId 'performer-42'
```

Fresh performer/source work remains blocked until storage authentication is `QUALIFIED`.

## Definition of done

Persistent storage authentication is **not solved** until `storage-auth-status.ps1` reports `QUALIFIED` after two distinct Windows boots for the **current credential generation**. A current-session share login, a readable Explorer window, a cached SMB session, a successful Credential Manager write, or a 2/2 receipt from an older password generation is insufficient evidence.
