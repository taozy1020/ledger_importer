"""Composition root: build components, run the pipeline, expose entry points."""

from bean_import.app.factory import (
    Components,
    build_advisor,
    build_classifier,
    build_components,
    build_journal,
)
from bean_import.app.pipeline import import_files

__all__ = [
    "Components",
    "build_advisor",
    "build_classifier",
    "build_components",
    "build_journal",
    "import_files",
]
