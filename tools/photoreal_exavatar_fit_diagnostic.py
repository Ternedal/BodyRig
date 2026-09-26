from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


class ExAvatarFitDiagnosticError(ValueError):
    pass


LOSS_MARKER = """                loss = {k:loss[k].mean() for k in loss}
                
                # backward
                sum(loss[k] for k in loss).backward()
                trainer.optimizer.step()
"""
LOSS_PATCH = """                loss = {k:loss[k].mean() for k in loss}

                nonfinite_loss = [
                    k for k, value in loss.items()
                    if not bool(torch.isfinite(value.detach()).all())
                ]
                if nonfinite_loss:
                    raise RuntimeError(
                        'BodyRig fitting non-finite loss at epoch={} itr_data={} itr_opt={}: {}'.format(
                            epoch, itr_data, itr_opt, ','.join(sorted(nonfinite_loss))
                        )
                    )

                # backward
                sum(loss[k] for k in loss).backward()

                bodyrig_named_params = {
                    id(smplx_shape): 'smplx_shape',
                    id(flame_shape): 'flame_shape',
                    id(face_offset): 'face_offset',
                    id(joint_offset): 'joint_offset',
                    id(locator_offset): 'locator_offset',
                }
                for bodyrig_frame_idx, bodyrig_values in smplx_params.items():
                    for bodyrig_key, bodyrig_param in bodyrig_values.items():
                        bodyrig_named_params.setdefault(
                            id(bodyrig_param),
                            'smplx_params[{}].{}'.format(bodyrig_frame_idx, bodyrig_key),
                        )
                for bodyrig_frame_idx, bodyrig_values in flame_params.items():
                    for bodyrig_key, bodyrig_param in bodyrig_values.items():
                        bodyrig_named_params.setdefault(
                            id(bodyrig_param),
                            'flame_params[{}].{}'.format(bodyrig_frame_idx, bodyrig_key),
                        )

                nonfinite_grad = []
                for group_idx, group in enumerate(trainer.optimizer.param_groups):
                    for param_idx, param in enumerate(group['params']):
                        if param.grad is not None and not bool(torch.isfinite(param.grad).all()):
                            nonfinite_grad.append(
                                bodyrig_named_params.get(
                                    id(param),
                                    'group{}[{}]'.format(group_idx, param_idx),
                                )
                            )
                if nonfinite_grad:
                    raise RuntimeError(
                        'BodyRig fitting non-finite gradient at epoch={} itr_data={} itr_opt={}: {}'.format(
                            epoch, itr_data, itr_opt, ','.join(nonfinite_grad[:32])
                        )
                    )

                trainer.optimizer.step()

                nonfinite_param = []
                for group_idx, group in enumerate(trainer.optimizer.param_groups):
                    for param_idx, param in enumerate(group['params']):
                        if not bool(torch.isfinite(param.detach()).all()):
                            nonfinite_param.append(
                                bodyrig_named_params.get(
                                    id(param),
                                    'group{}[{}]'.format(group_idx, param_idx),
                                )
                            )
                if nonfinite_param:
                    raise RuntimeError(
                        'BodyRig fitting non-finite parameter after step at epoch={} itr_data={} itr_opt={}: {}'.format(
                            epoch, itr_data, itr_opt, ','.join(nonfinite_param[:32])
                        )
                    )
"""

FIT_IMPORT_MARKER = "from pytorch3d.io import save_ply\n"

SET_ARGS_MARKER = """    cfg.set_args(args.subject_id)
    
    trainer = Trainer()
"""
SET_ARGS_PATCH = """    cfg.set_args(args.subject_id)
    cfg.result_dir = osp.join(cfg.output_dir, 'bodyrig-fit-diagnostic', args.subject_id)
    os.makedirs(cfg.result_dir, exist_ok=True)
    torch.autograd.set_detect_anomaly(True)
    
    trainer = Trainer()
"""

EDGE_LENGTH_MONKEYPATCH = """
from nets.loss import EdgeLengthLoss as _BodyRigEdgeLengthLoss

def _bodyrig_stable_edge_length_forward(self, coord_out, coord_gt, valid):
    face = torch.as_tensor(self.face, dtype=torch.long, device=coord_out.device)
    eps = 1e-12

    def edge_length(coord, a, b):
        delta = coord[:, face[:,a], :] - coord[:, face[:,b], :]
        return torch.sqrt(torch.sum(delta * delta, dim=2, keepdim=True) + eps)

    d1_out = edge_length(coord_out, 0, 1)
    d2_out = edge_length(coord_out, 0, 2)
    d3_out = edge_length(coord_out, 1, 2)
    d1_gt = edge_length(coord_gt, 0, 1)
    d2_gt = edge_length(coord_gt, 0, 2)
    d3_gt = edge_length(coord_gt, 1, 2)

    valid_mask_1 = valid[:,face[:,0],:] * valid[:,face[:,1],:]
    valid_mask_2 = valid[:,face[:,0],:] * valid[:,face[:,2],:]
    valid_mask_3 = valid[:,face[:,1],:] * valid[:,face[:,2],:]

    diff1 = torch.abs(d1_out - d1_gt) * valid_mask_1
    diff2 = torch.abs(d2_out - d2_gt) * valid_mask_2
    diff3 = torch.abs(d3_out - d3_gt) * valid_mask_3
    return torch.cat((diff1, diff2, diff3), 1)

_BodyRigEdgeLengthLoss.forward = _bodyrig_stable_edge_length_forward
"""


def _patch_fit_source(source: str, *, main_dir: Path) -> str:
    if (
        source.count(LOSS_MARKER) != 1
        or source.count(SET_ARGS_MARKER) != 1
        or source.count(FIT_IMPORT_MARKER) != 1
    ):
        raise ExAvatarFitDiagnosticError("pinned ExAvatar fit.py markers changed")
    prefix = (
        "import sys as _bodyrig_sys\n"
        f"_bodyrig_sys.path.insert(0, {str(main_dir)!r})\n"
    )
    patched = source.replace(
        FIT_IMPORT_MARKER,
        FIT_IMPORT_MARKER + "\n" + EDGE_LENGTH_MONKEYPATCH.strip() + "\n\n",
        1,
    )
    patched = patched.replace(LOSS_MARKER, LOSS_PATCH, 1)
    patched = patched.replace(SET_ARGS_MARKER, SET_ARGS_PATCH, 1)
    return prefix + patched


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run isolated ExAvatar SMPL-X fitting with first-nonfinite diagnostics."
    )
    parser.add_argument("--workspace-root", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.workspace_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ExAvatarFitDiagnosticError(f"workspace root is missing or unsafe: {root}")

    receipt_path = root / "workspace-receipt.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExAvatarFitDiagnosticError("workspace receipt is unreadable") from exc
    subject = str(receipt.get("subject_id") or "").strip()
    if not subject:
        raise ExAvatarFitDiagnosticError("workspace receipt subject_id is missing")

    main_dir = root / "repos" / "ExAvatar_RELEASE" / "fitting" / "main"
    source_path = main_dir / "fit.py"
    if not source_path.is_file() or source_path.is_symlink():
        raise ExAvatarFitDiagnosticError("pinned ExAvatar fit.py is missing or unsafe")
    source = source_path.read_text(encoding="utf-8")
    patched = _patch_fit_source(source, main_dir=main_dir)

    diagnostic_dir = root / "diagnostics" / "smplx-fit"
    if diagnostic_dir.is_symlink():
        raise ExAvatarFitDiagnosticError("diagnostic directory may not be a symlink")
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    script = diagnostic_dir / "fit-diagnostic.py"
    script.write_text(patched, encoding="utf-8")

    output_root = (
        root
        / "repos"
        / "ExAvatar_RELEASE"
        / "fitting"
        / "output"
        / "bodyrig-fit-diagnostic"
        / subject
    )
    if output_root.is_symlink():
        raise ExAvatarFitDiagnosticError("diagnostic output may not be a symlink")
    if output_root.exists():
        if not output_root.is_dir():
            raise ExAvatarFitDiagnosticError("diagnostic output is not a directory")
        shutil.rmtree(output_root)

    log_path = root / "logs" / "preprocess" / "05-smplx-fit-diagnostic.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "0"
    env["PYOPENGL_PLATFORM"] = "egl"
    env["PYTHONNOUSERSITE"] = "1"

    print(f"BodyRig ExAvatar fit diagnostic: {subject}", flush=True)
    print(f"Log: {log_path}", flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.Popen(
            [sys.executable, str(script), "--subject_id", subject],
            cwd=str(main_dir),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert completed.stdout is not None
        for line in completed.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log.write(line)
            log.flush()
        return int(completed.wait())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ExAvatarFitDiagnosticError) as exc:
        print(f"BodyRig ExAvatar fit diagnostic: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
