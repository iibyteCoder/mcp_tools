"""Read-only profiles must refuse mutations and allow inspection.

Read-only inverts the usual question: not "is this irreversible" but "could this
change anything". The tests below check both directions, because a read-only mode
that lets a mutation through is worthless and one that blocks ``ps aux`` would be
switched off within a day.
"""

from __future__ import annotations

import pytest

from host_cli.domain.enums import CommandIntent
from host_cli.domain.intent import classify_intent

INSPECTION_CASES = [
    "ps aux",
    "ps aux | grep nginx",
    "df -h",
    "free -m",
    "uptime",
    "uname -a",
    "whoami",
    "id",
    "hostname",
    "date",
    "tail -100 /var/log/messages",
    "tail -f /var/log/nginx/access.log",
    "head -20 /etc/passwd",
    "cat /etc/os-release",
    "cat /proc/meminfo",
    "grep error /var/log/messages",
    "grep -r foo /etc/nginx/",
    "awk '{print $1}' access.log",
    "sed -n '1,10p' /etc/hosts",
    "sort /tmp/list",
    "uniq -c",
    "wc -l /var/log/messages",
    "journalctl -u nginx -n 50",
    "journalctl --since '1 hour ago'",
    "systemctl status nginx",
    "systemctl is-active sshd",
    "systemctl is-failed nginx",
    "systemctl list-units --failed",
    "systemctl cat nginx",
    "docker ps",
    "docker ps -a",
    "docker images",
    "docker logs web",
    "docker inspect web",
    "ip addr show",
    "ip route",
    "ss -lntp",
    "netstat -tunlp",
    "ifconfig -a",
    "ls -la /etc",
    "lsblk",
    "lsof -i :80",
    "find /tmp -name '*.log'",
    "du -sh /var/log",
    "stat /etc/passwd",
    "ps aux > /dev/null",
    "df -h 2>/dev/null",
    "echo done",
    "true",
    "which python3",
]

MUTATION_CASES = [
    "systemctl restart nginx",
    "systemctl stop nginx",
    "systemctl start nginx",
    "systemctl enable nginx",
    "systemctl disable nginx",
    "systemctl daemon-reload",
    "rm -rf /tmp/x",
    "rm /tmp/x",
    "mkdir /tmp/x",
    "touch /tmp/x",
    "chmod 777 /tmp/x",
    "chown nobody /tmp/x",
    "useradd deploy",
    "userdel deploy",
    "passwd deploy",
    "yum install -y nginx",
    "yum update",
    "apt install nginx",
    "rpm -ivh package.rpm",
    "docker rm web",
    "docker restart web",
    "docker stop web",
    "docker run nginx",
    "docker pull nginx",
    "sed -i 's/a/b/' /etc/hosts",
    "sed --in-place 's/a/b/' /etc/hosts",
    "find /tmp -delete",
    "find /tmp -exec rm {} \\;",
    "echo x > /etc/passwd",
    "echo x > /tmp/out",
    "echo x >> /tmp/out",
    "cat /dev/null > /etc/shadow",
    "tar czf /tmp/x.tar.gz /data",
    "tar xzf x.tar.gz",
    "cp /etc/passwd /tmp/",
    "mv /etc/hosts /tmp/",
    "dd if=/dev/zero of=/dev/sda",
    "kill -9 1234",
    "reboot",
    "shutdown -h now",
    "crontab -r",
    "git commit -m x",
    "git push",
    "python3 script.py",
    "bash -c 'rm -rf /'",
    "$X --help",
]

UNKNOWN_COMMAND_CASES = [
    "some-unknown-tool --flag",
    "/opt/vendor/bin/status",
    "myapp health-check",
]
"""Anything not recognised is a mutation.

The list exists to make the trade explicit: a read-only profile will refuse a
genuinely read-only tool it has never heard of. That is the price of failing
closed, and knowing it is better than discovering it at 3am.
"""


@pytest.mark.parametrize("command", INSPECTION_CASES)
def test_inspection_commands_are_allowed(command: str) -> None:
    assert classify_intent(command) is CommandIntent.INSPECTION


@pytest.mark.parametrize("command", MUTATION_CASES)
def test_mutating_commands_are_refused(command: str) -> None:
    assert classify_intent(command) is CommandIntent.MUTATION


@pytest.mark.parametrize("command", UNKNOWN_COMMAND_CASES)
def test_an_unrecognised_command_is_treated_as_a_mutation(command: str) -> None:
    """Failing closed is the whole reason read-only mode is worth having."""

    assert classify_intent(command) is CommandIntent.MUTATION


def test_one_mutation_makes_the_whole_line_a_mutation() -> None:
    """The shell would run both halves, so inspecting the first is not enough."""

    assert classify_intent("ps aux && systemctl restart nginx") is CommandIntent.MUTATION


def test_a_pipeline_of_inspections_is_allowed() -> None:
    assert classify_intent("ps aux | grep nginx | wc -l") is CommandIntent.INSPECTION


def test_a_redirect_into_a_real_file_is_a_mutation() -> None:
    assert classify_intent("echo x > /tmp/out") is CommandIntent.MUTATION


def test_discarding_output_is_not_a_mutation() -> None:
    """``> /dev/null`` is how read-only commands silence noise."""

    assert classify_intent("ps aux > /dev/null") is CommandIntent.INSPECTION


def test_an_empty_command_is_a_mutation() -> None:
    assert classify_intent("") is CommandIntent.MUTATION
