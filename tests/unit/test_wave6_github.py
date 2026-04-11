from __future__ import annotations

import json

from scoped_control.integrations.github import load_remote_edit_request


def test_load_remote_edit_request_from_workflow_dispatch_payload(tmp_path) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "inputs": {
                    "role": "maintainer",
                    "request": "change return 1 to return 10",
                    "executor": "fake",
                    "top_k": "2",
                }
            }
        ),
        encoding="utf-8",
    )

    request = load_remote_edit_request(event_path)

    assert request.role_name == "maintainer"
    assert request.request == "change return 1 to return 10"
    assert request.executor == "fake"
    assert request.top_k == 2
