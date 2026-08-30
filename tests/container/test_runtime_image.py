"""What the production runtime image is allowed to contain.

Trivy reports one code-scanning alert per affected *binary package*, so a tool
that is in the image only to answer a HEALTHCHECK is not one alert — `curl` and
the libraries it drags in account for roughly forty. The cheapest reduction in
the container attack surface is not to patch those packages but to stop
installing them.

These tests build the `runtime` stage and assert on the result. They are marked
``container`` and skip when Docker is unavailable, so they stay out of the normal
suite; run them with ``-m container``.
"""

import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

pytestmark = [pytest.mark.container, pytest.mark.slow]

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_TAG = "fraiseql:pytest-runtime"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0


requires_docker = pytest.mark.skipif(not _docker_available(), reason="Docker is not available")


@pytest.fixture(scope="module")
def runtime_image() -> str:
    """Build the runtime stage. Warm layer cache makes this cheap after the first run."""
    build = subprocess.run(
        ["docker", "build", "--target", "runtime", "-t", IMAGE_TAG, "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if build.returncode != 0:
        pytest.fail(f"docker build failed:\n{build.stdout[-4000:]}\n{build.stderr[-4000:]}")
    return IMAGE_TAG


def _run(image: str, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "", image, *argv],
        capture_output=True,
        text=True,
        check=False,
    )


@requires_docker
class TestAttackSurface:
    def test_curl_is_not_installed(self, runtime_image: str) -> None:
        """`curl` existed only for the HEALTHCHECK. It and libcurl carry ~40 alerts."""
        assert _run(runtime_image, "sh", "-c", "command -v curl").returncode != 0

    def test_libcurl_and_libssh2_are_gone_with_it(self, runtime_image: str) -> None:
        """libssh2 is a libcurl dependency; nothing else in the image pulls either."""
        installed = _run(runtime_image, "dpkg-query", "-f", "${Package}\n", "-W").stdout
        packages = set(installed.split())
        assert not {p for p in packages if p.startswith(("curl", "libcurl", "libssh2"))}

    def test_libpq5_and_its_dependencies_are_still_present(self, runtime_image: str) -> None:
        """The floor: krb5 and openldap are *libpq5's* dependencies, not curl's.

        They stay, and so do their alerts — dropping curl does not touch them.
        Asserting it here keeps a future "cut more packages" change from breaking
        PostgreSQL connectivity in pursuit of a lower alert count.
        """
        installed = _run(runtime_image, "dpkg-query", "-f", "${Package}\n", "-W").stdout
        packages = set(installed.split())
        assert "libpq5" in packages
        assert any(p.startswith("libgssapi-krb5") for p in packages)
        assert any(p.startswith("libldap") for p in packages)

    def test_pip_is_not_installed(self, runtime_image: str) -> None:
        """The wheel is already installed and the entrypoint is gunicorn.

        pip is also the *only* source of the msgpack alert — the image has no
        msgpack distribution, just `pip/_vendor/msgpack`.
        """
        assert _run(runtime_image, "python", "-c", "import pip").returncode != 0

    def test_setuptools_is_not_installed(self, runtime_image: str) -> None:
        assert _run(runtime_image, "python", "-c", "import setuptools").returncode != 0

    def test_no_vendored_msgpack_remains(self, runtime_image: str) -> None:
        found = _run(
            runtime_image, "sh", "-c", 'find / -iname "msgpack*" -maxdepth 8 2>/dev/null'
        ).stdout.strip()
        assert found == "", f"msgpack still present at: {found}"

    def test_fraiseql_still_imports(self, runtime_image: str) -> None:
        """Removing build tooling must not remove the package it installed."""
        result = _run(runtime_image, "python", "-c", "import fraiseql; print(fraiseql.__version__)")
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip()

    def test_runs_as_a_non_root_user(self, runtime_image: str) -> None:
        assert _run(runtime_image, "id", "-un").stdout.strip() == "fraiseql"


@requires_docker
class TestHealthcheck:
    def test_healthcheck_command_does_not_use_curl(self, runtime_image: str) -> None:
        inspect = subprocess.run(
            ["docker", "inspect", "--format", "{{json .Config.Healthcheck}}", runtime_image],
            capture_output=True,
            text=True,
            check=True,
        )
        healthcheck = json.loads(inspect.stdout)
        assert healthcheck is not None, "the image must still declare a HEALTHCHECK"
        command = " ".join(healthcheck["Test"])
        assert "curl" not in command
        assert "python" in command

    def test_healthcheck_reports_healthy_against_a_running_server(
        self, runtime_image: str
    ) -> None:
        """The only functional change in this phase: prove it against a live container.

        A HEALTHCHECK that cannot run is indistinguishable from one that always
        fails, and both look the same in a build.
        """
        name = f"fraiseql-health-{uuid.uuid4().hex[:8]}"
        started = subprocess.run(
            [
                "docker", "run", "-d", "--name", name, "--entrypoint", "python", runtime_image,
                "-c",
                "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
                "class H(BaseHTTPRequestHandler):\n"
                "    def do_GET(self):\n"
                "        ok = self.path == '/health'\n"
                "        self.send_response(200 if ok else 404)\n"
                "        self.end_headers()\n"
                "        self.wfile.write(b'{\"status\":\"ok\"}' if ok else b'')\n"
                "    def log_message(self, *a): pass\n"
                "HTTPServer(('0.0.0.0', 8000), H).serve_forever()\n",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert started.returncode == 0, started.stderr
        try:
            deadline = time.time() + 90
            status = None
            while time.time() < deadline:
                status = subprocess.run(
                    ["docker", "inspect", "--format", "{{.State.Health.Status}}", name],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout.strip()
                if status == "healthy":
                    break
                if status == "unhealthy":
                    logs = subprocess.run(
                        ["docker", "inspect", "--format", "{{json .State.Health}}", name],
                        capture_output=True,
                        text=True,
                        check=False,
                    ).stdout
                    pytest.fail(f"HEALTHCHECK reported unhealthy: {logs}")
                time.sleep(2)
            assert status == "healthy", f"health status stuck at {status!r}"
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
