"""Print exact installed third-party versions for a reproducible advisory query.

Only this unpublished, dependency-free local project is excluded. Its code is
reviewed and scanned separately; every external distribution stays in the audit.
Run with the development virtualenv's Python interpreter.
"""

import re
from importlib.metadata import distributions


def requirements() -> list[str]:
    packages: dict[str, str] = {}
    for distribution in distributions():
        name = distribution.metadata["Name"]
        if not name:
            raise RuntimeError("Installed distribution has no package name")
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        if normalized != "winusb-forge":
            packages[normalized] = distribution.version
    return [f"{name}=={version}" for name, version in sorted(packages.items())]


if __name__ == "__main__":
    print("\n".join(requirements()))
