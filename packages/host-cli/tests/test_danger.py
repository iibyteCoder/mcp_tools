"""Danger-guard matrix, exercised as a pure function.

Every case here is evaluated in memory. `find_dangers` takes a string and
returns findings; it performs no I/O and must never be validated against a real
host. That rule exists because of the 2026-11-20 incident: this matrix was once
run against a production server and took it down, when the same coverage was
always available offline.
"""

from __future__ import annotations

import pytest

from host_cli.domain.danger import find_dangers
from host_cli.domain.enums import DangerCategory

RECURSIVE_DELETE_CASES = [
    "rm -rf /",
    "rm -fr /",
    "rm -r -f /",
    "rm -Rf /",
    "rm -rf /*",
    "rm -rf /usr",
    "rm -rf /etc",
    "rm -rf /var",
    "rm -rf /root",
    "rm -rf ~",
    "rm -rf /var/",
    "rm --recursive --force /",
    "rm -r --force /var",
    "rm --force -r /var",
]

SAME_COMMAND_DIFFERENT_SPELLING = [
    "/bin/rm -rf /",
    "/usr/bin/rm -rf /",
    "busybox rm -rf /",
    "\\rm -rf /",
    "sudo rm -rf /usr",
    "sudo -u root /usr/bin/rm -fr /etc",
    "doas rm -rf /var",
    "nohup rm -rf /root",
    "env FOO=1 rm -rf /usr",
    "setsid rm -rf /",
    "time rm -rf /var",
    "timeout 30 rm -rf /etc",
    "echo x | xargs rm -rf /",
    "bash -c 'rm -rf /'",
    'sh -c "rm -rf /var"',
    "zsh -c 'rm -rf /etc'",
]

OTHER_DELETE_SHAPES = [
    "find / -delete",
    "find /var -name lost -delete",
    "truncate -s0 /etc/passwd",
    "shred -u /etc/shadow",
    "mv /etc /etc.bak",
    "mv /var /var.old",
]

RECURSIVE_DELETE_CLEAN = [
    "rm -rf /tmp/cache",
    "rm -rf /tmp/*",
    "rm -rf ./build",
    "rm -rf build/",
    "rm -rf /var/log/old",
    "rm -rf /home/app/cache",
    "rm -rf node_modules",
    "rm -f /tmp/x",
    "rm -r /tmp/build",
    "rm --recursive /tmp/build",
    "find /data -name '*.log' -mtime +7 -delete",
    "find /tmp -type f -name '*.tmp' -delete",
    "mv /tmp/a /tmp/b",
    "truncate -s0 /tmp/scratch.log",
]

OTHER_CATEGORY_CASES = [
    ("dd if=/dev/zero of=/dev/sda", DangerCategory.DISK_WRITE),
    ("dd if=/dev/sda of=/tmp/backup.img", None),
    ("mkfs.ext4 /dev/sdb1", DangerCategory.DISK_WRITE),
    ("shutdown -h now", DangerCategory.POWER_STATE),
    ("reboot", DangerCategory.POWER_STATE),
    ("sudo reboot", DangerCategory.POWER_STATE),
    ("chmod 777 /", DangerCategory.PERMISSION_OPEN),
    ("chmod -R 777 /var", DangerCategory.PERMISSION_OPEN),
    ("chmod -R 0777 /usr", DangerCategory.PERMISSION_OPEN),
    ("chmod -R 777 /tmp/x", None),
    ("chown -R nobody /", DangerCategory.PERMISSION_OPEN),
    ("chown -R nobody /var/lib", DangerCategory.PERMISSION_OPEN),
    ("iptables -F", DangerCategory.FIREWALL_FLUSH),
    ("iptables --flush", DangerCategory.FIREWALL_FLUSH),
    ("systemctl stop auditd", DangerCategory.AUDIT_TAMPER),
    ("systemctl disable auditd", DangerCategory.AUDIT_TAMPER),
    ("history -c", DangerCategory.AUDIT_TAMPER),
    ("auditctl -D", DangerCategory.AUDIT_TAMPER),
    ("rm -rf /var/log", DangerCategory.AUDIT_TAMPER),
    ("ps aux", None),
    ("systemctl restart nginx", None),
    ("systemctl stop nginx", None),
    ("tail -100 /var/log/messages", None),
    ("docker ps -a", None),
]

ACCESS_LOCKOUT_CASES = [
    "systemctl stop sshd",
    "systemctl disable sshd",
    "systemctl mask sshd",
    "sudo systemctl stop sshd",
    "systemctl stop sshd.service",
    "systemctl disable firewalld",
    "systemctl stop firewalld",
    "ip link set eth0 down",
    "ifdown eth0",
    "ifconfig eth0 down",
    "iptables -P INPUT DROP",
    "iptables -P FORWARD DROP",
    "kill -9 1",
    "sudo kill -9 1",
    "pkill -9 sshd",
    "killall sshd",
    "swapoff -a",
    "crontab -r",
    "userdel -r deploy",
    "deluser --remove deploy",
]

ACCESS_KEPT_CASES = [
    "systemctl restart nginx",
    "systemctl restart sshd",
    "systemctl reload nginx",
    "systemctl status sshd",
    "systemctl is-active sshd",
    "systemctl start sshd",
    "ip addr show",
    "ip link show",
    "iptables -L",
    "iptables -S",
    "iptables -nvL",
    "crontab -l",
    "kill -9 12345",
    "useradd deploy",
    "systemctl restart firewalld",
]

REDIRECT_TRUNCATE_CASES = [
    "echo x > /etc/passwd",
    "echo '' > /etc/fstab",
    "cat /dev/null > /etc/shadow",
    "echo x > /var/log/messages",
    "echo x > /usr/bin/env",
    "printf '' > /root/.ssh/authorized_keys",
    "> /etc/passwd",
]

REDIRECT_KEPT_CASES = [
    "echo hi > /tmp/x",
    "ps aux > /tmp/out.txt 2>&1",
    "echo done >> /var/log/deploy.log",
    "echo x >> /etc/motd",
    "ls > /dev/null",
    "cmd 2>/tmp/err.log",
    "cmd &> /tmp/all.log",
]

MASS_DESTROY_CASES = [
    "docker system prune -a --volumes",
    "docker system prune -af",
    "docker container prune",
    "rsync -a --delete /empty/ /data/",
    "tar xzf x.tar.gz -C /",
    "tar xzf backup.tar.gz --directory /",
    "unzip backup.zip -d /",
]

MASS_DESTROY_KEPT_CASES = [
    "docker ps",
    "docker images",
    "docker logs web",
    "rsync -av /data/ /backup/",
    "tar czf /backup/x.tar.gz -C /data .",
    "tar xzf x.tar.gz -C /tmp/restore",
    "unzip backup.zip -d /tmp/restore",
]


@pytest.mark.parametrize("command", RECURSIVE_DELETE_CASES)
def test_forced_recursive_delete_of_a_protected_tree_is_caught(command: str) -> None:
    categories = {finding.category for finding in find_dangers(command)}

    assert DangerCategory.RECURSIVE_DELETE in categories


@pytest.mark.parametrize("command", SAME_COMMAND_DIFFERENT_SPELLING)
def test_the_same_act_is_caught_however_it_is_spelled(command: str) -> None:
    """The reason this guard parses instead of matching text.

    An absolute path, a wrapper, a pipe into ``xargs`` and a nested shell are all
    the same act; each one defeated the previous text-matching implementation.
    """

    categories = {finding.category for finding in find_dangers(command)}

    assert categories, f"not caught: {command}"


@pytest.mark.parametrize("command", OTHER_DELETE_SHAPES)
def test_deletion_via_another_command_is_caught(command: str) -> None:
    """``find -delete``, ``truncate``, ``shred`` and ``mv`` all destroy data.

    Knowing only ``rm`` was the gap that let a real wipe through on 2026-11-20.
    """

    categories = {finding.category for finding in find_dangers(command)}

    assert DangerCategory.RECURSIVE_DELETE in categories


@pytest.mark.parametrize("command", RECURSIVE_DELETE_CLEAN)
def test_ordinary_deletes_are_not_flagged(command: str) -> None:
    categories = {finding.category for finding in find_dangers(command)}

    assert DangerCategory.RECURSIVE_DELETE not in categories
    assert DangerCategory.AUDIT_TAMPER not in categories


@pytest.mark.parametrize(("command", "expected"), OTHER_CATEGORY_CASES)
def test_each_category_matches_its_own_shapes(command: str, expected: DangerCategory | None) -> None:
    categories = {finding.category for finding in find_dangers(command)}

    if expected is None:
        assert not categories, f"unexpectedly flagged: {categories}"
    else:
        assert expected in categories


def test_the_matched_excerpt_is_reported_for_review() -> None:
    findings = find_dangers("sudo rm -rf /usr")

    assert findings
    assert findings[0].excerpt
    assert "rm -rf /usr" in findings[0].excerpt


@pytest.mark.parametrize("command", ACCESS_LOCKOUT_CASES)
def test_losing_the_way_back_in_is_caught(command: str) -> None:
    """The guard protects reachability, not only data.

    A host that lost `/etc` can still be logged into; a host whose sshd was
    masked cannot. That difference is why these have their own category: the
    mistake is recoverable only from a console.
    """

    categories = {finding.category for finding in find_dangers(command)}

    assert DangerCategory.ACCESS_LOCKOUT in categories


@pytest.mark.parametrize("command", ACCESS_KEPT_CASES)
def test_ordinary_service_and_network_commands_stay_allowed(command: str) -> None:
    """A ``restart`` is not a lockout, and flagging it would be corrosive.

    If restarting a service required ``--force``, the operator would learn to pass
    ``--force`` by reflex, and the guard's signal would be gone for the commands
    that genuinely need it.
    """

    categories = {finding.category for finding in find_dangers(command)}

    assert DangerCategory.ACCESS_LOCKOUT not in categories


@pytest.mark.parametrize("command", REDIRECT_TRUNCATE_CASES)
def test_a_truncating_redirect_over_a_system_file_is_caught(command: str) -> None:
    """The destructive act can be the redirect alone.

    ``echo x > /etc/passwd`` empties the file while the command name stays
    innocent, so no command-name rule can see it.
    """

    categories = {finding.category for finding in find_dangers(command)}

    assert DangerCategory.REDIRECT_TRUNCATE in categories


@pytest.mark.parametrize("command", REDIRECT_KEPT_CASES)
def test_ordinary_redirection_is_not_flagged(command: str) -> None:
    """``>>`` appends and never destroys, and ``2>&1`` names no path at all."""

    categories = {finding.category for finding in find_dangers(command)}

    assert DangerCategory.REDIRECT_TRUNCATE not in categories
    assert DangerCategory.RECURSIVE_DELETE not in categories


@pytest.mark.parametrize("command", MASS_DESTROY_CASES)
def test_one_command_that_wipes_many_things_is_caught(command: str) -> None:
    """``docker prune`` and ``rsync --delete`` destroy more than any ``rm``.

    Neither names a path the guard could reason about, so the command shape is
    what has to be recognised.
    """

    categories = {finding.category for finding in find_dangers(command)}

    assert categories


@pytest.mark.parametrize("command", MASS_DESTROY_KEPT_CASES)
def test_read_only_and_restoring_uses_of_the_same_tools_stay_allowed(command: str) -> None:
    """Unpacking into a scratch directory is not the same as unpacking over ``/``."""

    categories = {finding.category for finding in find_dangers(command)}

    assert not categories, f"unexpectedly flagged: {categories}"


def test_a_harmless_command_yields_no_findings() -> None:
    assert find_dangers("df -h && free -m") == ()


def test_an_unresolvable_command_is_reported_rather_than_allowed() -> None:
    """Blindness must be visible: an unknown command name is not a clean result.

    A guard that returns "nothing found" for ``$X -rf /`` reports the same answer
    as for ``ps aux``, which is exactly the wrong signal.
    """

    findings = find_dangers("$X -rf /")

    assert any(finding.category is DangerCategory.UNRESOLVED for finding in findings)


def test_a_command_substitution_name_is_reported() -> None:
    findings = find_dangers("$(echo rm) -rf /")

    assert any(finding.category is DangerCategory.UNRESOLVED for finding in findings)


def test_a_destructive_command_with_an_unknowable_target_is_reported() -> None:
    """``rm -rf $TARGET`` cannot be proven safe, so it is not treated as safe.

    This is a deliberate false positive: the alternative is letting any variable
    name walk past the guard.
    """

    findings = find_dangers("rm -rf $BUILD_DIR")

    assert any(finding.category is DangerCategory.UNRESOLVED for finding in findings)


def test_a_non_destructive_command_with_a_variable_is_not_reported() -> None:
    """The advisory is scoped to destructive commands, so daily work stays clean."""

    assert find_dangers("tail -100 $LOG_FILE") == ()
