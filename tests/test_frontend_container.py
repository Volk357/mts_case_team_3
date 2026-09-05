"""Static acceptance checks for the production frontend image."""

import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
DOCKERFILE = REPOSITORY / "apps" / "web" / "Dockerfile"
NGINX_TEMPLATE = REPOSITORY / "apps" / "web" / "nginx" / "default.conf.template"


class FrontendContainerTests(unittest.TestCase):
    def test_locked_multistage_production_build(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("FROM node:${NODE_VERSION}-alpine AS builder", dockerfile)
        self.assertIn("npm ci --prefix /build/contracts", dockerfile)
        self.assertIn("npm ci --prefix /build/apps/web", dockerfile)
        self.assertIn("VITE_APP_ENV=production", dockerfile)
        self.assertIn("nginxinc/nginx-unprivileged", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)

    def test_api_upstream_is_runtime_configurable(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        nginx = NGINX_TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("DOCREVIEW_API_UPSTREAM=http://api:8000", dockerfile)
        self.assertIn("proxy_pass ${DOCREVIEW_API_UPSTREAM};", nginx)
        self.assertIn("location /api/", nginx)

    def test_spa_routes_fall_back_to_index(self) -> None:
        nginx = NGINX_TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("try_files $uri $uri/ /index.html;", nginx)
        self.assertIn("location = /healthz", nginx)
        self.assertIn("return 200", nginx)


if __name__ == "__main__":
    unittest.main()
