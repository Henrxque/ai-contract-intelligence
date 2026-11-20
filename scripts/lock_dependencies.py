"""Freeze the installed runtime dependency graph; run after deliberate upgrades."""

from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]
pending = [
    "fastapi",
    "uvicorn",
    "python-multipart",
    "pydantic",
    "pydantic-settings",
    "pypdf",
    "openai",
    "openpyxl",
]
seen = {}
while pending:
    package = distribution(pending.pop())
    name = package.metadata["Name"].lower()
    if name in seen:
        continue
    seen[name] = package.version
    for raw in package.requires or []:
        requirement = Requirement(raw)
        if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
            pending.append(requirement.name)

(ROOT / "requirements.lock").write_text(
    "# Pinned runtime dependency versions. Regenerate after deliberate upgrades.\n"
    + "\n".join(f"{name}=={version}" for name, version in sorted(seen.items()))
    + "\n",
    encoding="utf-8",
)
print(f"Pinned {len(seen)} runtime packages.")
