"""Acceptance checks for PostgreSQL orchestration and guarded demo seed."""

import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
COMPOSE = REPOSITORY / "compose.yaml"
ENV_EXAMPLE = REPOSITORY / ".env.example"
SEED = REPOSITORY / "apps" / "api" / "scripts" / "seed_demo.py"


class PostgresComposeTests(unittest.TestCase):
    def test_postgres_is_persistent_and_health_checked(self) -> None:
        compose = COMPOSE.read_text(encoding="utf-8")

        self.assertIn("postgres:17.6-alpine", compose)
        self.assertIn("postgres_data:/var/lib/postgresql/data", compose)
        self.assertIn("pg_isready", compose)
        self.assertIn("condition: service_healthy", compose)

    def test_password_is_required_without_a_default(self) -> None:
        compose = COMPOSE.read_text(encoding="utf-8")
        example = ENV_EXAMPLE.read_text(encoding="utf-8")

        self.assertIn("DOCREVIEW_POSTGRES_PASSWORD:?", compose)
        self.assertIn("DOCREVIEW_POSTGRES_PASSWORD=", example)
        self.assertNotIn("DOCREVIEW_POSTGRES_PASSWORD=docreview", example)

    def test_migrations_gate_backend_and_demo_seed_is_explicit(self) -> None:
        compose = COMPOSE.read_text(encoding="utf-8")
        seed = SEED.read_text(encoding="utf-8")

        self.assertIn("condition: service_completed_successfully", compose)
        self.assertIn('profiles: ["demo", "mock", "real"]', compose)
        self.assertIn("DOCREVIEW_ALLOW_DEMO_SEED", seed)
        self.assertIn('settings.environment != "demo"', seed)
        self.assertIn("discover_review_pack_manifests", seed)
        self.assertIn("DOCREVIEW_DEMO_PACK_LOCATOR", compose)


if __name__ == "__main__":
    unittest.main()
