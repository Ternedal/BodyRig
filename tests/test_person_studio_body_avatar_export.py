from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_app.js").read_text(encoding="utf-8")
APP = (ROOT / "bodyrig" / "app.py").read_text(encoding="utf-8")

def test_body_workspace_exposes_revision_bound_vrm_download() -> None:
    assert 'id="bodyAvatarDownload"' in HTML
    assert 'download="avatar.vrm"' in HTML
    assert '/body/avatar?revision=${encodeURIComponent(body.revision_id)}' in JS
    assert 'avatarDownload.download = `${body.revision_id}.vrm`;' in JS

def test_avatar_export_uses_existing_read_only_validated_route() -> None:
    assert '@app.get("/api/v1/people/{person_id}/body/avatar")' in APP
    assert 'package = _body_bytes_match(item)' in APP
    assert 'archive.read("avatar.vrm")' in APP
    section = JS.split('const avatarDownload = $("bodyAvatarDownload");', 1)[1].split("const personality =", 1)[0]
    assert 'method: "POST"' not in section
