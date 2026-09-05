from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "docker-compose-runbook.md"


def test_root_readme_links_compose_runbook() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/docker-compose-runbook.md" in readme
    assert "docker compose --profile mock up --build --wait" in readme


def test_runbook_covers_stage_seven_operations() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    required_fragments = (
        "Copy-Item .env.example .env",
        "docker compose --profile mock up --build --wait",
        "docker compose --profile real up --build --wait",
        "docker compose --profile mock down",
        "docker compose --profile mock logs --follow",
        "docker compose run --rm migrate",
        "docker compose --profile real run --rm model-preflight",
        "host.docker.internal",
        "/api/chat",
        "http://127.0.0.1:8080/healthz",
        "http://127.0.0.1:8080/api/health",
        "docker compose --profile mock build --no-cache",
    )

    for fragment in required_fragments:
        assert fragment in runbook


def test_runbook_warns_against_mixed_profiles_and_destructive_reset() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")

    assert "Не запускайте `mock` и `real` одновременно" in runbook
    assert "down --volumes" in runbook
    assert "удаляет" in runbook
