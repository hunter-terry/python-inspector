from pathlib import Path
from inspector_app.backend.real_backend import RealBackend


def test_workspace_root_is_cleaned_up_on_end_session():
    backend = RealBackend()
    workspace_root = backend._workspace_root
    assert workspace_root.exists()
    backend.end_session()
    assert not workspace_root.exists()