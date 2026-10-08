from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from bodyrig import photoreal_exavatar_workspace_wsl as workspace_wsl


def test_workspace_v1_accepts_numeric_one() -> None:
    assert workspace_wsl._is_v1(1)
    assert workspace_wsl._is_v1(1.0)


def test_workspace_v1_rejects_boolean_and_non_v1_values() -> None:
    assert not workspace_wsl._is_v1(True)
    assert not workspace_wsl._is_v1(False)
    assert not workspace_wsl._is_v1("1")
    assert not workspace_wsl._is_v1(0)
    assert not workspace_wsl._is_v1(2)


def test_workspace_frame_count_requires_exact_integer() -> None:
    assert workspace_wsl._is_exact_count(1, 1)
    assert not workspace_wsl._is_exact_count(True, 1)
    assert not workspace_wsl._is_exact_count(1.0, 1)
    assert not workspace_wsl._is_exact_count("1", 1)


def _fitting_gender_patch() -> dict[str, object]:
    return {
        "destination": workspace_wsl._FITTING_SMPLX_GENDER_RELATIVE,
        "source_sha256": "3" * 64,
        "replaced_sha256": "4" * 64,
        "patched_sha256": "f" * 64,
    }


def _code_receipt() -> dict[str, object]:
    return {
        "repository_commits": {
            name: commit for name, _url, commit in workspace_wsl.REPOSITORIES
        },
        "injected_patch_files": [
            {
                "destination": "repos/DECA/run_deca.py",
                "source_sha256": "1" * 64,
                "replaced_sha256": "2" * 64,
                "patched_sha256": "a" * 64,
            },
            _fitting_gender_patch(),
        ],
        "fitting_config_sha256": "b" * 64,
        "avatar_config_patch": {
            "relative_path": "avatar/main/config.py",
            "before_sha256": "d" * 64,
            "after_sha256": "c" * 64,
            "dataset": "Custom",
            "smplx_gender": "female",
        },
    }


def test_remove_workspace_requires_validated_build_only_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = {
        "build_only": True,
        "runtime_dependency": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    calls: list[list[str]] = []
    validate_kwargs: dict[str, object] = {}

    def fake_validate(**kwargs):
        validate_kwargs.update(kwargs)
        return dict(receipt)

    monkeypatch.setattr(
        workspace_wsl,
        "validate_exavatar_workspace_wsl",
        fake_validate,
    )
    monkeypatch.setattr(
        workspace_wsl,
        "_run",
        lambda invocation, *, label: calls.append(invocation)
        or SimpleNamespace(stdout="", returncode=0),
    )

    observed = workspace_wsl.remove_exavatar_workspace_wsl(
        materialization_receipt_path="materialization.json",
        strict_preflight_path="preflight.json",
        linux_workspace_root="/opt/bodyrig-exavatar/workspaces/bodyrig-42-test",
        smplx_gender="female",
    )

    assert observed == receipt
    assert validate_kwargs["validate_code_provenance"] is False
    assert any(
        call[-4:]
        == ["/bin/rm", "-rf", "--", "/opt/bodyrig-exavatar/workspaces/bodyrig-42-test"]
        for call in calls
    )


def test_remove_workspace_rejects_non_build_only_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workspace_wsl,
        "validate_exavatar_workspace_wsl",
        lambda **_kwargs: {
            "build_only": False,
            "runtime_dependency": False,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        },
    )

    with pytest.raises(
        workspace_wsl.PhotorealExAvatarWorkspaceWslError,
        match="not build-only",
    ):
        workspace_wsl.remove_exavatar_workspace_wsl(
            materialization_receipt_path="materialization.json",
            strict_preflight_path="preflight.json",
            linux_workspace_root="/opt/bodyrig-exavatar/workspaces/bodyrig-42-test",
            smplx_gender="female",
        )


def test_remove_workspace_rejects_non_bodyrig_leaf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_validate(**_kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(
        workspace_wsl,
        "validate_exavatar_workspace_wsl",
        fake_validate,
    )

    with pytest.raises(
        workspace_wsl.PhotorealExAvatarWorkspaceWslError,
        match="non-BodyRig workspace root",
    ):
        workspace_wsl.remove_exavatar_workspace_wsl(
            materialization_receipt_path="materialization.json",
            strict_preflight_path="preflight.json",
            linux_workspace_root="/opt/bodyrig-exavatar/workspaces/not-bodyrig",
            smplx_gender="female",
        )

    assert called is False


def test_workspace_code_provenance_rejects_pre_gender_authority_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _code_receipt()
    receipt["injected_patch_files"] = [
        item
        for item in receipt["injected_patch_files"]
        if item["destination"] != workspace_wsl._FITTING_SMPLX_GENDER_RELATIVE
    ]

    with pytest.raises(
        workspace_wsl.PhotorealExAvatarWorkspaceWslError,
        match="predates explicit fitting SMPL-X gender authority",
    ):
        workspace_wsl._validate_workspace_code_provenance(
            receipt,
            workspace_root="/opt/bodyrig-exavatar/workspaces/bodyrig-42",
            distribution="Ubuntu-22.04",
            wsl_exe="wsl.exe",
        )


def test_workspace_code_provenance_revalidates_heads_and_patch_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _code_receipt()
    git_calls: list[list[str]] = []

    def fake_run(invocation, *, label):
        git_calls.append(invocation)
        repo_path = invocation[invocation.index("-C") + 1]
        name = next(
            name
            for name, relative in workspace_wsl.PUBLIC_TOOL_LAYOUT.items()
            if repo_path.endswith("/" + relative)
        )
        if "rev-parse" in invocation:
            expected = dict(
                (repo_name, commit)
                for repo_name, _url, commit in workspace_wsl.REPOSITORIES
            )[name]
            return SimpleNamespace(stdout=expected + "\n")
        assert invocation[-3:] == ["submodule", "status", "--recursive"]
        return SimpleNamespace(
            stdout=(" " + ("1" * 40) + " third_party/glm\n")
            if name == "diff-gaussian-rasterization-depth"
            else ""
        )

    def fake_sha(*, path, **_kwargs):
        if path.endswith("/repos/DECA/run_deca.py"):
            return "a" * 64
        if path.endswith("/" + workspace_wsl._FITTING_SMPLX_GENDER_RELATIVE):
            return "f" * 64
        if path.endswith("/repos/ExAvatar_RELEASE/fitting/main/config.py"):
            return "b" * 64
        if path.endswith("/repos/ExAvatar_RELEASE/avatar/main/config.py"):
            return "c" * 64
        raise AssertionError(path)

    monkeypatch.setattr(workspace_wsl, "_run", fake_run)
    monkeypatch.setattr(workspace_wsl, "_wsl_file_sha256", fake_sha)

    workspace_wsl._validate_workspace_code_provenance(
        receipt,
        workspace_root="/opt/bodyrig-exavatar/workspaces/bodyrig-42",
        distribution="Ubuntu-22.04",
        wsl_exe="wsl.exe",
    )

    assert len(git_calls) == 2 * len(workspace_wsl.REPOSITORIES)
    assert all("safe.directory=" in " ".join(call) for call in git_calls)
    assert sum("submodule" in call for call in git_calls) == len(workspace_wsl.REPOSITORIES)


def test_workspace_code_provenance_accepts_exact_teacher_runtime_checkpoint_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = (
        "prefix\n"
        + workspace_wsl._TEACHER_CHECKPOINT_LOAD_ORIGINAL
        + "between\n"
        + workspace_wsl._TEACHER_TESTER_CHECKPOINT_LOAD_ORIGINAL
        + "suffix\n"
    )
    patched = (
        original.replace(
            workspace_wsl._TEACHER_CHECKPOINT_LOAD_ORIGINAL,
            workspace_wsl._TEACHER_CHECKPOINT_LOAD_PATCHED,
            1,
        ).replace(
            workspace_wsl._TEACHER_TESTER_CHECKPOINT_LOAD_ORIGINAL,
            workspace_wsl._TEACHER_TESTER_CHECKPOINT_LOAD_PATCHED,
            1,
        )
    )
    expected = hashlib.sha256(original.encode("utf-8")).hexdigest()
    observed = hashlib.sha256(patched.encode("utf-8")).hexdigest()
    receipt = _code_receipt()
    receipt["injected_patch_files"] = [
        {
            "destination": workspace_wsl._TEACHER_RUNTIME_BASE_RELATIVE,
            "source_sha256": "1" * 64,
            "replaced_sha256": "2" * 64,
            "patched_sha256": expected,
        },
        _fitting_gender_patch(),
    ]

    def fake_run(invocation, *, label):
        if "/bin/cat" in invocation:
            return SimpleNamespace(stdout=patched, returncode=0)
        repo_path = invocation[invocation.index("-C") + 1]
        name = next(
            name
            for name, relative in workspace_wsl.PUBLIC_TOOL_LAYOUT.items()
            if repo_path.endswith("/" + relative)
        )
        if "rev-parse" in invocation:
            expected_commit = dict(
                (repo_name, commit)
                for repo_name, _url, commit in workspace_wsl.REPOSITORIES
            )[name]
            return SimpleNamespace(stdout=expected_commit + "\n", returncode=0)
        return SimpleNamespace(stdout="", returncode=0)

    def fake_sha(*, path, **_kwargs):
        if path.endswith("/" + workspace_wsl._TEACHER_RUNTIME_BASE_RELATIVE):
            return observed
        if path.endswith("/" + workspace_wsl._FITTING_SMPLX_GENDER_RELATIVE):
            return "f" * 64
        if path.endswith("/repos/ExAvatar_RELEASE/fitting/main/config.py"):
            return "b" * 64
        if path.endswith("/repos/ExAvatar_RELEASE/avatar/main/config.py"):
            return "c" * 64
        raise AssertionError(path)

    monkeypatch.setattr(workspace_wsl, "_run", fake_run)
    monkeypatch.setattr(workspace_wsl, "_wsl_file_sha256", fake_sha)

    workspace_wsl._validate_workspace_code_provenance(
        receipt,
        workspace_root="/opt/bodyrig-exavatar/workspaces/bodyrig-42",
        distribution="Ubuntu-22.04",
        wsl_exe="wsl.exe",
    )


def test_workspace_runtime_checkpoint_guard_normalizer_accepts_pre_pytorch26_patch() -> None:
    original = (
        "prefix\n"
        + workspace_wsl._TEACHER_CHECKPOINT_LOAD_ORIGINAL
        + "between\n"
        + workspace_wsl._TEACHER_TESTER_CHECKPOINT_LOAD_ORIGINAL
        + "suffix\n"
    )
    patched_v1 = (
        original.replace(
            workspace_wsl._TEACHER_CHECKPOINT_LOAD_ORIGINAL,
            workspace_wsl._TEACHER_CHECKPOINT_LOAD_PATCHED_V1,
            1,
        ).replace(
            workspace_wsl._TEACHER_TESTER_CHECKPOINT_LOAD_ORIGINAL,
            workspace_wsl._TEACHER_TESTER_CHECKPOINT_LOAD_PATCHED_V1,
            1,
        )
    )

    assert workspace_wsl._normalize_known_teacher_runtime_base_patch(patched_v1) == original


def test_workspace_runtime_checkpoint_guard_normalizer_accepts_pytorch26_patch() -> None:
    original = (
        "prefix\n"
        + workspace_wsl._TEACHER_CHECKPOINT_LOAD_ORIGINAL
        + "between\n"
        + workspace_wsl._TEACHER_TESTER_CHECKPOINT_LOAD_ORIGINAL
        + "suffix\n"
    )
    patched = (
        original.replace(
            workspace_wsl._TEACHER_CHECKPOINT_LOAD_ORIGINAL,
            workspace_wsl._TEACHER_CHECKPOINT_LOAD_PATCHED,
            1,
        ).replace(
            workspace_wsl._TEACHER_TESTER_CHECKPOINT_LOAD_ORIGINAL,
            workspace_wsl._TEACHER_TESTER_CHECKPOINT_LOAD_PATCHED,
            1,
        )
    )

    assert workspace_wsl._normalize_known_teacher_runtime_base_patch(patched) == original


def test_workspace_runtime_checkpoint_guard_normalizer_rejects_unrelated_drift() -> None:
    assert workspace_wsl._normalize_known_teacher_runtime_base_patch(
        "arbitrary modified base.py"
    ) is None


def test_workspace_code_provenance_rejects_unsafe_patch_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _code_receipt()
    receipt["injected_patch_files"][0]["destination"] = "/tmp/escape.py"

    def fake_run(invocation, *, label):
        repo_path = invocation[invocation.index("-C") + 1]
        name = next(
            name
            for name, relative in workspace_wsl.PUBLIC_TOOL_LAYOUT.items()
            if repo_path.endswith("/" + relative)
        )
        expected = dict(
            (repo_name, commit)
            for repo_name, _url, commit in workspace_wsl.REPOSITORIES
        )[name]
        return SimpleNamespace(stdout=expected + "\n")

    monkeypatch.setattr(workspace_wsl, "_run", fake_run)

    with pytest.raises(
        workspace_wsl.PhotorealExAvatarWorkspaceWslError,
        match="destination is unsafe",
    ):
        workspace_wsl._validate_workspace_code_provenance(
            receipt,
            workspace_root="/opt/bodyrig-exavatar/workspaces/bodyrig-42",
            distribution="Ubuntu-22.04",
            wsl_exe="wsl.exe",
        )


def test_workspace_code_provenance_rejects_repository_head_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _code_receipt()

    def fake_run(invocation, *, label):
        return SimpleNamespace(stdout=("f" * 40) + "\n")

    monkeypatch.setattr(workspace_wsl, "_run", fake_run)

    with pytest.raises(
        workspace_wsl.PhotorealExAvatarWorkspaceWslError,
        match="repository HEAD drifted",
    ):
        workspace_wsl._validate_workspace_code_provenance(
            receipt,
            workspace_root="/opt/bodyrig-exavatar/workspaces/bodyrig-42",
            distribution="Ubuntu-22.04",
            wsl_exe="wsl.exe",
        )



def test_workspace_code_provenance_rejects_uninitialized_submodule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _code_receipt()

    def fake_run(invocation, *, label):
        repo_path = invocation[invocation.index("-C") + 1]
        name = next(
            name
            for name, relative in workspace_wsl.PUBLIC_TOOL_LAYOUT.items()
            if repo_path.endswith("/" + relative)
        )
        if "rev-parse" in invocation:
            expected = dict(
                (repo_name, commit)
                for repo_name, _url, commit in workspace_wsl.REPOSITORIES
            )[name]
            return SimpleNamespace(stdout=expected + "\n")
        if name == "diff-gaussian-rasterization-depth":
            return SimpleNamespace(stdout="-" + ("1" * 40) + " third_party/glm\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(workspace_wsl, "_run", fake_run)

    with pytest.raises(
        workspace_wsl.PhotorealExAvatarWorkspaceWslError,
        match="submodule drifted/uninitialized",
    ):
        workspace_wsl._validate_workspace_code_provenance(
            receipt,
            workspace_root="/opt/bodyrig-exavatar/workspaces/bodyrig-42",
            distribution="Ubuntu-22.04",
            wsl_exe="wsl.exe",
        )
