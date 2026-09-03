import json
from datetime import date, datetime
from io import StringIO

from rich.console import Console

import harvest.cli as cli
from harvest.models import (
    DailyRecord,
    NetworkTrace,
    ProjectItem,
    ProjectMemory,
    Usage,
)
from harvest.providers.responses import _safe_error_detail
from harvest.render import render_daily
from harvest.storage import Storage
from harvest.text_safety import REPLACEMENT_CHARACTER, escape_markdown_text, sanitize_untrusted_text
from tests.test_models_render import sample_harvest


ATTACK = "safe\x1b]52;c;SGVsbG8=\x07\x1b[2J\u202eevil"


def _terminal_console() -> tuple[Console, StringIO]:
    stream = StringIO()
    return Console(file=stream, force_terminal=True, markup=False, width=120), stream


def test_sanitizer_removes_terminal_and_direction_controls() -> None:
    safe = sanitize_untrusted_text("a\r\nb\rc\t\x1b\x07\x9b\u202ed")

    assert safe == f"a\nb\nc{REPLACEMENT_CHARACTER * 5}d"
    assert all(character == "\n" or character.isprintable() for character in safe)


def test_structured_model_sanitizes_untrusted_text() -> None:
    item = ProjectItem(
        name=ATTACK,
        status="active",
        last_seen=date(2026, 9, 3),
    )

    assert "\x1b" not in item.name
    assert "\x07" not in item.name
    assert "\u202e" not in item.name


def test_markdown_data_cannot_create_structure_links_or_html() -> None:
    escaped = escape_markdown_text(
        "<script>hidden</script>\n# fake heading\n[click](https://evil.test)\n- fake item\n"
        "    fake code\n===\n&NewLine;hidden"
    )

    assert r"\<script\>hidden\</script\>" in escaped
    assert r"\# fake heading" in escaped
    assert r"\[click\](https://evil.test)" in escaped
    assert r"\- fake item" in escaped
    assert "\N{NO-BREAK SPACE}" * 4 + "fake code" in escaped
    assert r"\===" in escaped
    assert r"\&NewLine;hidden" in escaped


def test_rendered_markdown_escapes_model_syntax() -> None:
    report = sample_harvest().model_copy(
        update={"overview": "<script>hidden</script>\n# fake heading"}
    )
    record = DailyRecord(
        date=date(2026, 9, 3),
        generated_at=datetime.now(),
        provider="deepseek",
        model="test",
        usage=Usage(),
        report=report,
    )

    markdown = render_daily(record)

    assert r"\<script\>hidden\</script\>" in markdown
    assert r"\# fake heading" in markdown


def test_daily_preview_cannot_emit_model_control_sequences(monkeypatch) -> None:
    report = sample_harvest().model_copy(
        update={"overview": ATTACK + " [link=https://evil.test]click[/link]"}
    )
    record = DailyRecord(
        date=date(2026, 9, 3),
        generated_at=datetime.now(),
        provider="deepseek",
        model="test",
        usage=Usage(),
        report=report,
    )
    console, stream = _terminal_console()
    monkeypatch.setattr(cli, "console", console)

    cli._show_daily(record)

    output = stream.getvalue()
    assert "\x1b]52;" not in output
    assert "\x1b[2J" not in output
    assert "\x1b]8;" not in output


def test_project_list_treats_rich_markup_as_plain_text(tmp_path, monkeypatch) -> None:
    storage = Storage(tmp_path / "data")
    storage.ensure()
    storage.save_project_memory(
        ProjectMemory(
            projects=[
                ProjectItem(
                    name="[link=https://evil.test]click[/link]",
                    status="active",
                    last_seen=date(2026, 9, 3),
                )
            ]
        )
    )
    monkeypatch.setattr(cli, "_context", lambda: (None, storage))
    console, stream = _terminal_console()
    monkeypatch.setattr(cli, "console", console)

    cli.project_list(False)

    output = stream.getvalue()
    assert "[link=https://evil.test]click[/link]" in output
    assert "\x1b]8;" not in output


def test_doctor_details_uses_plain_sanitized_json(monkeypatch) -> None:
    trace = NetworkTrace(
        endpoint="https://example.test",
        provider="deepseek",
        model="test",
        schema_name="test",
        status_code=200,
        elapsed_ms=1,
        request_payload={"input": ATTACK + " [link=https://evil.test]click[/link]"},
        response_payload={"output": ATTACK},
        usage=Usage(),
    )
    console, stream = _terminal_console()
    monkeypatch.setattr(cli, "console", console)

    cli._show_trace_details(trace)

    output = stream.getvalue()
    assert "\x1b]52;" not in output
    assert "\x1b[2J" not in output
    assert "\x1b]8;" not in output
    assert "[link=https://evil.test]click[/link]" in output


def test_provider_error_removes_terminal_controls() -> None:
    import httpx

    response = httpx.Response(400, json={"error": {"message": ATTACK}})

    detail = _safe_error_detail(response)

    assert "\x1b" not in detail
    assert "\x07" not in detail
    assert "\u202e" not in detail


def test_existing_generated_markdown_is_sanitized_once(tmp_path) -> None:
    storage = Storage(tmp_path / "data")
    storage.ensure()
    markdown_path = storage.root / "daily" / "2026" / "09" / "2026-09-03.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(ATTACK, encoding="utf-8")
    storage.calibration_path().write_text(
        json.dumps({
            "schema_version": 1,
            "onboarding_version": 1,
            "onboarding_completed": True,
            "first_daily_date": None,
            "five_report_status": "pending",
            "feedback_events": [],
        }),
        encoding="utf-8",
    )

    storage.ensure()

    migrated = markdown_path.read_text(encoding="utf-8")
    assert "\x1b" not in migrated
    assert "\x07" not in migrated
    assert storage.load_calibration().terminal_safety_version == 1
