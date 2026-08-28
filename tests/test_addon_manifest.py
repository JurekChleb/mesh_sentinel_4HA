"""Validate the app manifest the way the Supervisor does.

A config.yaml the Supervisor rejects does not produce an error in the UI: the
store logs a warning and skips the app, so the repository shows up with nothing
in it. That failure is invisible from the outside, which is exactly why it needs
a test.

The rules below are transcribed from the Supervisor source
(``supervisor/apps/validate.py``, ``supervisor/apps/options.py`` and
``supervisor/apps/const.py``) rather than guessed at.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "addon" / "config.yaml"
REPOSITORY = ROOT / "repository.yaml"

# supervisor/apps/const.py: RE_SLUG
RE_SLUG = re.compile(r"^[-_.A-Za-z0-9]+$")
# supervisor/apps/validate.py: RE_SERVICE
RE_SERVICE = re.compile(r"^(?:mqtt|mysql):(?:provide|want|need)$")
# supervisor/apps/options.py: RE_SCHEMA_ELEMENT
RE_SCHEMA_ELEMENT = re.compile(
    r"^(?:"
    r"|bool"
    r"|email"
    r"|url"
    r"|port"
    r"|device(?:\((?:subsystem=[a-z]+)\))?"
    r"|str(?:\((?:\d+)?,(?:\d+)?\))?"
    r"|password(?:\((?:\d+)?,(?:\d+)?\))?"
    r"|int(?:\((?:-?\d+)?,(?:-?\d+)?\))?"
    r"|float(?:\((?:-?\d*\.?\d+)?,(?:-?\d*\.?\d+)?\))?"
    r"|match\((?:.*)\)"
    r"|list\((?:.+)\)"
    r")\??$"
)
# supervisor/const.py: ARCH_ALL + ARCH_DEPRECATED
VALID_ARCH = {"amd64", "aarch64", "armhf", "armv7", "i386"}
REQUIRED = ("name", "version", "slug", "description", "arch")


@pytest.fixture(scope="module")
def config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def test_required_keys_are_present(config: dict):
    missing = [key for key in REQUIRED if key not in config]
    assert not missing, f"config.yaml is missing required keys: {missing}"


def test_no_key_is_explicitly_null(config: dict):
    """An explicit null is the trap that made the app vanish from the store.

    `image: null` reads as "no prebuilt image, build locally", but the Supervisor
    runs every present key through its validator, and docker_image() rejects
    None. Omit the key instead.
    """

    nulls = [key for key, value in config.items() if value is None]
    assert not nulls, (
        f"keys set to null in config.yaml: {nulls}. The Supervisor validates "
        "every key that is present; omit the key instead of nulling it."
    )


def test_slug_and_version(config: dict):
    assert RE_SLUG.match(config["slug"]), f"invalid slug: {config['slug']!r}"
    assert isinstance(config["version"], str), (
        "version must be quoted in YAML, otherwise 0.1 parses as a float"
    )


def test_architectures_are_real(config: dict):
    unknown = set(config["arch"]) - VALID_ARCH
    assert not unknown, f"unknown architectures: {unknown}"


def test_url_is_absolute(config: dict):
    assert config["url"].startswith(("http://", "https://"))


def test_ingress_port_is_usable(config: dict):
    if config.get("ingress"):
        port = config.get("ingress_port", 8099)
        assert 1 <= port <= 65535, f"ingress is on but the port is {port}"


def test_declared_services_are_valid(config: dict):
    for service in config.get("services", []):
        assert RE_SERVICE.match(service), f"invalid service declaration: {service!r}"


def test_every_option_has_a_schema_entry(config: dict):
    options = set(config.get("options", {}))
    schema = set(config.get("schema", {}))
    assert options - schema == set(), f"options with no schema entry: {options - schema}"
    assert schema - options == set(), (
        f"schema entries with no default in options: {schema - options}"
    )


def test_schema_elements_are_valid(config: dict):
    for key, element in config.get("schema", {}).items():
        assert isinstance(element, str), f"{key}: nested schemas are not used here"
        assert RE_SCHEMA_ELEMENT.match(element), f"invalid schema element {key}: {element!r}"


def test_version_matches_the_package(config: dict):
    from mesh_sentinel import __version__

    assert config["version"] == __version__, (
        "config.yaml and mesh_sentinel.__version__ disagree; the store shows the "
        "manifest version, so they must not drift"
    )


def test_dockerfile_label_matches(config: dict):
    dockerfile = (ROOT / "addon" / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r'io\.hass\.version="([^"]+)"', dockerfile)
    assert match, "the Dockerfile lost its io.hass.version label"
    assert match.group(1) == config["version"]


def test_repository_manifest_is_valid():
    data = yaml.safe_load(REPOSITORY.read_text(encoding="utf-8"))
    assert data.get("name"), "repository.yaml needs a name; it is the store heading"
    assert data.get("url", "").startswith("https://")


def test_the_app_directory_is_where_the_supervisor_looks():
    """The Supervisor scans repository subdirectories for config.yaml."""

    assert CONFIG.is_file()
    assert (CONFIG.parent / "Dockerfile").is_file()
    assert (CONFIG.parent / "run.sh").is_file()
