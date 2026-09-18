"""Static profile command execution over the typed profile service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mysql_cli.command_model import CommandAction, CommandGroup, CommandRequest, CommandStatus
from mysql_cli.output_model import BindingView, ProfileCommandData, ProfileView
from mysql_cli.profile_models import DirectoryBinding, ProfileName, ProfileRecord, ProfileSetRequest

if TYPE_CHECKING:
    from mysql_cli.profile_service import ProfileService


async def execute_profile_command(request: CommandRequest, service: ProfileService) -> ProfileCommandData:
    """Execute one parsed profile command without touching a database except validate."""

    action = request.action
    if action is CommandAction.LIST:
        return ProfileCommandData(
            status=CommandStatus.COMPLETED,
            command_group=CommandGroup.PROFILE,
            action=action,
            profiles=tuple(_profile_view(profile) for profile in service.list_profiles()),
        )
    if action is CommandAction.SHOW:
        profile = service.require(_required_name(request))
        return _with_profile(action, profile)
    if action is CommandAction.SET:
        settings = request.profile_settings
        if settings is None:
            raise ValueError("profile set settings are missing")
        profile = service.set(
            ProfileSetRequest(
                name=_required_name(request),
                settings=settings,
                password=request.profile_password,
                clear_password=request.profile_clear_password,
            )
        )
        return _with_profile(action, profile)
    if action is CommandAction.VALIDATE:
        profile = await service.validate(_required_name(request))
        return ProfileCommandData(
            status=CommandStatus.COMPLETED,
            command_group=CommandGroup.PROFILE,
            action=action,
            profile=_profile_view(profile),
            validated=True,
            connection_attempted=True,
        )
    if action is CommandAction.BIND:
        binding = service.bind(_required_name(request), request.profile_path)
        return ProfileCommandData(
            status=CommandStatus.COMPLETED,
            command_group=CommandGroup.PROFILE,
            action=action,
            binding=_binding_view(binding),
        )
    if action is CommandAction.UNBIND:
        removed_binding: DirectoryBinding | None = service.unbind(request.profile_path)
        return ProfileCommandData(
            status=CommandStatus.COMPLETED,
            command_group=CommandGroup.PROFILE,
            action=action,
            binding=None if removed_binding is None else _binding_view(removed_binding),
            unbound=removed_binding is not None,
        )
    if action is CommandAction.RENAME:
        renamed = service.rename(_required_name(request), _required_new_name(request))
        return _with_profile(action, renamed)
    if action is CommandAction.REMOVE:
        removed_bindings = service.remove(_required_name(request))
        return ProfileCommandData(
            status=CommandStatus.COMPLETED,
            command_group=CommandGroup.PROFILE,
            action=action,
            removed_bindings=removed_bindings,
        )
    raise ValueError("unsupported profile action")


def _profile_view(profile: ProfileRecord) -> ProfileView:
    settings = profile.settings
    return ProfileView(
        name=profile.name.value,
        host=settings.host,
        port=settings.port,
        user=settings.user,
        database=settings.database,
        charset=settings.charset,
        connect_timeout=settings.connect_timeout,
        read_timeout=settings.read_timeout,
        password_present=profile.password_present,
    )


def _binding_view(binding: DirectoryBinding) -> BindingView:
    return BindingView(path=binding.path, profile=binding.profile.value)


def _with_profile(action: CommandAction, profile: ProfileRecord) -> ProfileCommandData:
    return ProfileCommandData(
        status=CommandStatus.COMPLETED,
        command_group=CommandGroup.PROFILE,
        action=action,
        profile=_profile_view(profile),
    )


def _required_name(request: CommandRequest) -> ProfileName:
    if request.profile_name is None:
        raise ValueError("profile name is required")
    return request.profile_name


def _required_new_name(request: CommandRequest) -> ProfileName:
    if request.profile_new_name is None:
        raise ValueError("new profile name is required")
    return request.profile_new_name


__all__ = ["execute_profile_command"]
