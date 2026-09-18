from pathlib import Path

from db_cli_core.enums import ConnectionSource, DatabaseKind
from db_cli_core.profiles import ConnectionProfileManager, ProfileStore
from db_cli_core.secrets import VolatileSecretStore


def test_nearest_parent_binding_wins(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "connections.json", VolatileSecretStore())
    manager = ConnectionProfileManager(DatabaseKind.MYSQL, store)
    parent = tmp_path / "workspace"
    child = parent / "service"
    nested = child / "src"
    nested.mkdir(parents=True)
    manager.set("shared", {"host": "shared.local"}, parent)
    manager.set("service", {"host": "service.local"}, child)

    selection = manager.resolve(directory=nested)

    assert selection is not None
    assert selection.profile.name == "service"
    assert selection.source is ConnectionSource.DIRECTORY
    assert selection.bound_directory == child.resolve()


def test_removing_profile_also_removes_its_bindings(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "connections.json", VolatileSecretStore())
    manager = ConnectionProfileManager(DatabaseKind.REDIS, store)
    project = tmp_path / "project"
    project.mkdir()
    manager.set("cache", {"host": "cache.local", "database": 4}, project)

    manager.remove("cache")

    assert manager.resolve(directory=project) is None


def test_first_command_creates_missing_config_directory(tmp_path: Path) -> None:
    manager = ConnectionProfileManager(
        DatabaseKind.MYSQL,
        ProfileStore(tmp_path / "missing" / "connections.json", VolatileSecretStore()),
    )

    manager.set("local", {"host": "localhost"})

    assert manager.store.path.is_file()


def test_select_validates_and_binds_under_one_store_transaction(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "connections.json", VolatileSecretStore())
    manager = ConnectionProfileManager(DatabaseKind.REDIS, store)
    project = tmp_path / "project"
    project.mkdir()

    try:
        manager.select("missing", project)
    except ValueError as exc:
        assert "不存在" in str(exc)
    else:
        raise AssertionError("missing profile was bound")

    assert store.nearest_binding(DatabaseKind.REDIS, project) is None
