"""Redis data-type command groups."""

from __future__ import annotations

import click

from redis_cli.cli_support import NONNEGATIVE_INT, run_command
from redis_cli.command_parsing import mapping_arguments
from redis_cli.enums import ErrorCode, RedisCommand
from redis_cli.rendering import CliError


@click.group()
def string() -> None:
    """Operate on Redis string keys."""


@string.command("get")
@click.option("--key", "key_name", required=True)
@click.pass_context
def string_get(ctx: click.Context, key_name: str) -> None:
    run_command(ctx, RedisCommand.GET, (key_name,))


@string.command("set")
@click.option("--key", "key_name", required=True)
@click.option("--value", required=True)
@click.option("--ex", type=NONNEGATIVE_INT)
@click.option("--px", type=NONNEGATIVE_INT)
@click.option("--nx", is_flag=True)
@click.option("--xx", is_flag=True)
@click.pass_context
def string_set(
    ctx: click.Context,
    key_name: str,
    value: str,
    ex: int | None,
    px: int | None,
    nx: bool,
    xx: bool,
) -> None:
    if ex is not None and px is not None:
        raise CliError(ErrorCode.INVALID_ARGUMENT, "--ex and --px cannot be combined")
    if nx and xx:
        raise CliError(ErrorCode.INVALID_ARGUMENT, "--nx and --xx cannot be combined")
    arguments = [key_name, value]
    if ex is not None:
        arguments.extend(("EX", str(ex)))
    if px is not None:
        arguments.extend(("PX", str(px)))
    if nx:
        arguments.append("NX")
    if xx:
        arguments.append("XX")
    run_command(ctx, RedisCommand.SET, tuple(arguments))


@string.command("mget")
@click.option("--key", "keys", multiple=True, required=True)
@click.pass_context
def string_mget(ctx: click.Context, keys: tuple[str, ...]) -> None:
    run_command(ctx, RedisCommand.MGET, keys)


@string.command("mset")
@click.option("--mapping", required=True, help="JSON object mapping keys to values")
@click.pass_context
def string_mset(ctx: click.Context, mapping: str) -> None:
    run_command(ctx, RedisCommand.MSET, mapping_arguments(mapping, numeric=False))


@string.command("incr")
@click.option("--key", "key_name", required=True)
@click.option("--amount", type=int, default=1, show_default=True)
@click.pass_context
def string_incr(ctx: click.Context, key_name: str, amount: int) -> None:
    run_command(ctx, RedisCommand.INCRBY, (key_name, str(amount)))


@string.command("append")
@click.option("--key", "key_name", required=True)
@click.option("--value", required=True)
@click.pass_context
def string_append(ctx: click.Context, key_name: str, value: str) -> None:
    run_command(ctx, RedisCommand.APPEND, (key_name, value))


@string.command("strlen")
@click.option("--key", "key_name", required=True)
@click.pass_context
def string_strlen(ctx: click.Context, key_name: str) -> None:
    run_command(ctx, RedisCommand.STRLEN, (key_name,))


@click.group()
def hash() -> None:
    """Operate on Redis hash keys."""


@hash.command("get")
@click.option("--key", "key_name", required=True)
@click.option("--field", required=True)
@click.pass_context
def hash_get(ctx: click.Context, key_name: str, field: str) -> None:
    run_command(ctx, RedisCommand.HGET, (key_name, field))


@hash.command("set")
@click.option("--key", "key_name", required=True)
@click.option("--mapping", required=True, help="JSON object mapping fields to values")
@click.pass_context
def hash_set(ctx: click.Context, key_name: str, mapping: str) -> None:
    run_command(ctx, RedisCommand.HSET, (key_name, *mapping_arguments(mapping, numeric=False)))


@hash.command("getall")
@click.option("--key", "key_name", required=True)
@click.pass_context
def hash_getall(ctx: click.Context, key_name: str) -> None:
    run_command(ctx, RedisCommand.HGETALL, (key_name,))


@hash.command("delete")
@click.option("--key", "key_name", required=True)
@click.option("--field", "fields", multiple=True, required=True)
@click.pass_context
def hash_delete(ctx: click.Context, key_name: str, fields: tuple[str, ...]) -> None:
    run_command(ctx, RedisCommand.HDEL, (key_name, *fields))


@hash.command("exists")
@click.option("--key", "key_name", required=True)
@click.option("--field", required=True)
@click.pass_context
def hash_exists(ctx: click.Context, key_name: str, field: str) -> None:
    run_command(ctx, RedisCommand.HEXISTS, (key_name, field))


@hash.command("keys")
@click.option("--key", "key_name", required=True)
@click.pass_context
def hash_keys(ctx: click.Context, key_name: str) -> None:
    run_command(ctx, RedisCommand.HKEYS, (key_name,))


@hash.command("values")
@click.option("--key", "key_name", required=True)
@click.pass_context
def hash_values(ctx: click.Context, key_name: str) -> None:
    run_command(ctx, RedisCommand.HVALS, (key_name,))


@hash.command("length")
@click.option("--key", "key_name", required=True)
@click.pass_context
def hash_length(ctx: click.Context, key_name: str) -> None:
    run_command(ctx, RedisCommand.HLEN, (key_name,))


@click.group(name="list")
def list_group() -> None:
    """Operate on Redis list keys."""


@list_group.command("push")
@click.option("--key", "key_name", required=True)
@click.option("--value", "values", multiple=True, required=True)
@click.option("--right", is_flag=True)
@click.pass_context
def list_push(ctx: click.Context, key_name: str, values: tuple[str, ...], right: bool) -> None:
    command = RedisCommand.RPUSH if right else RedisCommand.LPUSH
    run_command(ctx, command, (key_name, *values))


@list_group.command("pop")
@click.option("--key", "key_name", required=True)
@click.option("--count", type=click.IntRange(min=1), default=1, show_default=True)
@click.option("--right", is_flag=True)
@click.pass_context
def list_pop(ctx: click.Context, key_name: str, count: int, right: bool) -> None:
    arguments = (key_name,) if count == 1 else (key_name, str(count))
    run_command(ctx, RedisCommand.RPOP if right else RedisCommand.LPOP, arguments)


@list_group.command("range")
@click.option("--key", "key_name", required=True)
@click.option("--start", type=int, required=True)
@click.option("--stop", type=int, required=True)
@click.pass_context
def list_range(ctx: click.Context, key_name: str, start: int, stop: int) -> None:
    run_command(ctx, RedisCommand.LRANGE, (key_name, str(start), str(stop)))


@list_group.command("length")
@click.option("--key", "key_name", required=True)
@click.pass_context
def list_length(ctx: click.Context, key_name: str) -> None:
    run_command(ctx, RedisCommand.LLEN, (key_name,))


@list_group.command("index")
@click.option("--key", "key_name", required=True)
@click.option("--index", type=int, required=True)
@click.pass_context
def list_index(ctx: click.Context, key_name: str, index: int) -> None:
    run_command(ctx, RedisCommand.LINDEX, (key_name, str(index)))


@list_group.command("trim")
@click.option("--key", "key_name", required=True)
@click.option("--start", type=int, required=True)
@click.option("--stop", type=int, required=True)
@click.pass_context
def list_trim(ctx: click.Context, key_name: str, start: int, stop: int) -> None:
    run_command(ctx, RedisCommand.LTRIM, (key_name, str(start), str(stop)))


@click.group(name="set")
def set_group() -> None:
    """Operate on Redis set keys."""


@set_group.command("add")
@click.option("--key", "key_name", required=True)
@click.option("--member", "members", multiple=True, required=True)
@click.pass_context
def set_add(ctx: click.Context, key_name: str, members: tuple[str, ...]) -> None:
    run_command(ctx, RedisCommand.SADD, (key_name, *members))


@set_group.command("remove")
@click.option("--key", "key_name", required=True)
@click.option("--member", "members", multiple=True, required=True)
@click.pass_context
def set_remove(ctx: click.Context, key_name: str, members: tuple[str, ...]) -> None:
    run_command(ctx, RedisCommand.SREM, (key_name, *members))


@set_group.command("members")
@click.option("--key", "key_name", required=True)
@click.pass_context
def set_members(ctx: click.Context, key_name: str) -> None:
    run_command(ctx, RedisCommand.SMEMBERS, (key_name,))


@set_group.command("card")
@click.option("--key", "key_name", required=True)
@click.pass_context
def set_card(ctx: click.Context, key_name: str) -> None:
    run_command(ctx, RedisCommand.SCARD, (key_name,))


@set_group.command("is-member")
@click.option("--key", "key_name", required=True)
@click.option("--member", required=True)
@click.pass_context
def set_is_member(ctx: click.Context, key_name: str, member: str) -> None:
    run_command(ctx, RedisCommand.SISMEMBER, (key_name, member))


@click.group()
def zset() -> None:
    """Operate on Redis sorted-set keys."""


@zset.command("add")
@click.option("--key", "key_name", required=True)
@click.option("--mapping", required=True, help="JSON object mapping members to scores")
@click.pass_context
def zset_add(ctx: click.Context, key_name: str, mapping: str) -> None:
    run_command(ctx, RedisCommand.ZADD, (key_name, *mapping_arguments(mapping, numeric=True)))


@zset.command("remove")
@click.option("--key", "key_name", required=True)
@click.option("--member", "members", multiple=True, required=True)
@click.pass_context
def zset_remove(ctx: click.Context, key_name: str, members: tuple[str, ...]) -> None:
    run_command(ctx, RedisCommand.ZREM, (key_name, *members))


@zset.command("range")
@click.option("--key", "key_name", required=True)
@click.option("--start", type=int, required=True)
@click.option("--stop", type=int, required=True)
@click.option("--with-scores", is_flag=True)
@click.option("--reverse", is_flag=True)
@click.pass_context
def zset_range(
    ctx: click.Context,
    key_name: str,
    start: int,
    stop: int,
    with_scores: bool,
    reverse: bool,
) -> None:
    arguments = [key_name, str(start), str(stop)]
    if with_scores:
        arguments.append("WITHSCORES")
    run_command(ctx, RedisCommand.ZREVRANGE if reverse else RedisCommand.ZRANGE, tuple(arguments))


@zset.command("card")
@click.option("--key", "key_name", required=True)
@click.pass_context
def zset_card(ctx: click.Context, key_name: str) -> None:
    run_command(ctx, RedisCommand.ZCARD, (key_name,))


@zset.command("score")
@click.option("--key", "key_name", required=True)
@click.option("--member", required=True)
@click.pass_context
def zset_score(ctx: click.Context, key_name: str, member: str) -> None:
    run_command(ctx, RedisCommand.ZSCORE, (key_name, member))


@zset.command("rank")
@click.option("--key", "key_name", required=True)
@click.option("--member", required=True)
@click.option("--reverse", is_flag=True)
@click.pass_context
def zset_rank(ctx: click.Context, key_name: str, member: str, reverse: bool) -> None:
    run_command(ctx, RedisCommand.ZREVRANK if reverse else RedisCommand.ZRANK, (key_name, member))


__all__ = ["hash", "list_group", "set_group", "string", "zset"]
