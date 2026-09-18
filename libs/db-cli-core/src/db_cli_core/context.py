"""Explicit Click context state."""

from dataclasses import dataclass
from typing import Any

from db_cli_core.contracts import DatabaseBackend
from db_cli_core.enums import ConnectionSource, OutputMode
from db_cli_core.profile_models import ConnectionSelection
from db_cli_core.profiles import ConnectionProfileManager


@dataclass
class CommandContext:
    backend: DatabaseBackend
    output_mode: OutputMode = OutputMode.HUMAN
    profile_manager: ConnectionProfileManager | None = None
    selection: ConnectionSelection | None = None
    connection_source: ConnectionSource = ConnectionSource.DEFAULT
    connection_initialized: bool = False

    def activate(self, selection: ConnectionSelection | None) -> None:
        self.selection = selection
        if selection is None:
            self.backend.reset_configuration()
            self.connection_source = ConnectionSource.DEFAULT
            self.connection_initialized = True
            return
        self.backend.configure(**selection.profile.settings)
        self.connection_source = selection.source
        self.connection_initialized = True

    def mark_explicit(self) -> None:
        self.connection_source = ConnectionSource.EXPLICIT

    @property
    def profile_name(self) -> str | None:
        """Identify a saved configuration only while its settings still match."""
        if self.selection is None:
            return None
        saved = self.selection.profile.settings
        active = self.backend.build_profile()
        if any(value != saved.get(key, "" if key == "password" else None) for key, value in active.items()):
            return None
        return self.selection.profile.name

    def connection_info(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "profile": self.selection.profile.name if self.selection else None,
            "source": self.connection_source.value,
            "bound_directory": str(self.selection.bound_directory)
            if self.selection and self.selection.bound_directory
            else None,
        }
        return metadata | self.backend.connection_info
