from __future__ import annotations

from runtime.model_providers.client import extract_direct_stream_event, extract_stream_event


def test_extract_stream_event_accepts_legacy_function_call() -> None:
    event = extract_stream_event({
        "choices": [
            {
                "delta": {
                    "function_call": {
                        "name": "filesystem__scan_folder",
                        "arguments": '{"path":"."}',
                    }
                }
            }
        ]
    })

    assert event["tool_calls"] == [
        {
            "index": 0,
            "id": None,
            "type": "function",
            "function": {
                "name": "filesystem__scan_folder",
                "arguments": '{"path":"."}',
            },
        }
    ]


def test_extract_direct_stream_event_accepts_legacy_function_call() -> None:
    event = extract_direct_stream_event({
        "function_call": {
            "name": "filesystem__scan_folder",
            "arguments": '{"path":"."}',
        }
    })

    assert event["tool_calls"][0]["function"]["name"] == "filesystem__scan_folder"
    assert event["tool_calls"][0]["function"]["arguments"] == '{"path":"."}'
