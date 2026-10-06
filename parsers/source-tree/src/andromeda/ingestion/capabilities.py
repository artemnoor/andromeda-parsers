"""Runtime capability inventory for ingestion and deployment preflight."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
import importlib.util
import logging
import shutil
from typing import Callable


logger = logging.getLogger("andromeda.ingestion.capabilities")


@dataclass(frozen=True, slots=True)
class CapabilityStatus:
    name: str
    kind: str
    available: bool
    version: str | None
    required_profiles: tuple[str, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    profile: str
    capabilities: tuple[CapabilityStatus, ...]

    @property
    def missing_required(self) -> tuple[CapabilityStatus, ...]:
        return tuple(
            item
            for item in self.capabilities
            if self.profile in item.required_profiles and not item.available
        )

    @property
    def ready(self) -> bool:
        return not self.missing_required

    def as_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "ready": self.ready,
            "missingRequired": [asdict(item) for item in self.missing_required],
            "capabilities": [asdict(item) for item in self.capabilities],
        }


class CapabilityPreflightError(RuntimeError):
    def __init__(self, report: CapabilityReport) -> None:
        self.report = report
        missing = ", ".join(item.name for item in report.missing_required)
        super().__init__(f"INGESTION_CAPABILITY_MISSING profile={report.profile} capabilities={missing}")


_MODULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("beautifulsoup4", "bs4", ("bmstu", "hse")),
    ("PyMuPDF", "fitz", ("bmstu", "hse")),
    ("pypdf", "pypdf", ("bmstu", "hse")),
    ("pdfplumber", "pdfplumber", ("bmstu", "hse")),
)


def discover_capabilities(
    *,
    module_finder: Callable[[str], object | None] = importlib.util.find_spec,
    executable_finder: Callable[[str], str | None] = shutil.which,
) -> tuple[CapabilityStatus, ...]:
    statuses: list[CapabilityStatus] = []
    for package_name, module_name, profiles in _MODULES:
        try:
            available = module_finder(module_name) is not None
        except (ImportError, ValueError):
            available = False
        statuses.append(
            CapabilityStatus(
                name=package_name,
                kind="python",
                available=available,
                version=_package_version(package_name) if available else None,
                required_profiles=profiles,
                detail="importable" if available else f"module {module_name!r} is unavailable",
            )
        )
    poppler_path = executable_finder("pdftotext")
    statuses.append(
        CapabilityStatus(
            name="Poppler pdftotext",
            kind="system",
            available=poppler_path is not None,
            version=None,
            required_profiles=("bmstu",),
            detail=poppler_path or "pdftotext is not on PATH",
        )
    )
    try:
        browser_available = module_finder("playwright") is not None
    except (ImportError, ValueError):
        browser_available = False
    statuses.append(
        CapabilityStatus(
            name="Playwright browser fallback",
            kind="optional-python",
            available=browser_available,
            version=_package_version("playwright") if browser_available else None,
            required_profiles=(),
            detail="optional BMSTU anti-bot fallback" if browser_available else "optional; HTTP path remains available",
        )
    )
    return tuple(statuses)


def preflight(profile: str, *, log: bool = True) -> CapabilityReport:
    report = CapabilityReport(profile=profile, capabilities=discover_capabilities())
    if log:
        for item in report.capabilities:
            logger.info(
                "ingestion_capability profile=%s name=%s kind=%s available=%s version=%s detail=%s",
                profile,
                item.name,
                item.kind,
                item.available,
                item.version or "unknown",
                item.detail,
            )
    if not report.ready:
        raise CapabilityPreflightError(report)
    return report


def _package_version(package_name: str) -> str | None:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None


__all__ = [
    "CapabilityPreflightError",
    "CapabilityReport",
    "CapabilityStatus",
    "discover_capabilities",
    "preflight",
]
