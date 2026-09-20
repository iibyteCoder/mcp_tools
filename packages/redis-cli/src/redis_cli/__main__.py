"""Run the ``db-redis`` command as a module."""

from redis_cli.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
