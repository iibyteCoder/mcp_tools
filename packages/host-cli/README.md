# host-cli

把一条命令发到远端主机，把结果原样取回来。

```powershell
host-cli profile set app01 --host app01.example.internal --user ops --description "应用服务器"
host-cli profile set-password app01 --password-stdin
host-cli run 'ps aux | head' --profile app01
```

输出永远是单个 JSON 文档：`{"ok": …,"data": …,"error": …}`。

## 命令

```text
profile  list | show | set | rename | remove | set-password | clear-password | validate
run      <COMMAND> --profile NAME [--timeout S] [--force] [--dry-run]
                    [--request-approval | --approve TOKEN]
audit    summary | show [--limit N] [--status S]
skill    打印 Skill 文档的安装位置
```

- `run` 的命令是**一个**参数，原样交给远端 shell。引号、管道、重定向由调用者负责，工具不解析、不包装、不注入。
- 密码只进操作系统凭据库（本机为 Windows Credential Manager），凭据库的账号就是 profile 名；改 host/user 不影响已存密码。密码**只能**经 stdin 传入，从不接受命令行参数。
- 没有默认 profile，也没有目录绑定：每次必须显式 `--profile`，避免命令发错机器。
- `profile set` 是 upsert，省略的字段保持原值。代价是名字打错会静默建出第二个 profile，加完机器请 `profile list` 确认。

## 四道门禁

不是一道。任何单一黑名单都不够，因为「危险」有很多种形态。

| 门禁 | 配置 | 拒绝什么 | 能否绕过 |
|---|---|---|---|
| **危险检测** | 内置 10 类 | 不可逆操作（见下） | `--force` |
| **只读模式** | `profile set NAME --read-only` | 任何非查询操作 | **不能**，`--force` 无效 |
| **审批** | `profile set NAME --requires-approval` | 无 token 的每次调用 | 需 `--approve TOKEN` |
| **速率** | `profile set NAME --max-commands-per-minute N` | 超过每分钟上限 | 等窗口过去 |

四者顺序是「危险 → 只读 → 审批 → 速率」。**前一门拒绝时不消耗速率额度**，所以永远跑不了的命令不会挤占正常调用的配额。

### 危险检测的 10 类

匹配用语法树而非正则，所以 `/bin/rm -rf /`、`busybox rm -rf /`、`sudo -u root /usr/bin/rm -fr /etc`、`sh -c 'rm -rf /'` 视为同一件事。

| 类别 | 例子 |
|---|---|
| `recursive_delete` | `rm -rf /`、`find / -delete`、`truncate -s0 /etc/passwd`、`mv /etc /etc.bak`、`docker system prune -a --volumes`、`rsync --delete`、`tar -C /` |
| `access_lockout` | `systemctl stop sshd`、`systemctl disable firewalld`、`ip link set eth0 down`、`iptables -P INPUT DROP`、`crontab -r`、`userdel -r`、`kill -9 1` |
| `redirect_truncate` | `echo x > /etc/passwd`、`cat /dev/null > /etc/shadow`、`> /etc/fstab` |
| `permission_open` | `chmod -R 777 /var`、`chown -R nobody /` |
| `disk_write` | `dd of=/dev/sda`、`mkfs.ext4 /dev/sdb1` |
| `power_state` | `shutdown`、`reboot`、`halt` |
| `firewall_flush` | `iptables -F` |
| `audit_tamper` | `systemctl stop auditd`、`history -c`、`rm -rf /var/log` |
| `fork_bomb` | `:(){ :\|:& };:` |
| `unresolved` | `rm -rf $TARGET`、`rm -rf $(cat path)` |

`access_lockout` 保护的是**可达性**而非数据：丢了 `/etc` 还能登录，`sshd` 被 mask 就只能去控制台。`systemctl restart` 刻意不拦——重启服务是日常操作，拦了会训练操作者闭眼按 `--force`。

`unresolved` 不是「干净」：它表示目标在运行时才决定，工具看不见。`rm -rf $BUILD_DIR` 会命中它，确认值安全后加 `--force`。

**这道门禁是安全带，不是刹车。** `eval`、`base64 | sh`、`python -c '...'` 都绕得过去。真正的边界是主机权限。

### 只读模式

反转判定方向：不是「这是不是不可逆」，而是「这会不会改动任何东西」。没被识别的命令一律视为变更。

```powershell
host-cli profile set prod01 --read-only
host-cli profile set prod01 --writable
```

放行 `ps`、`df`、`tail`、`grep`、`journalctl -u x -n`、`systemctl status`、`docker ps`、`ip addr show` 等；拒绝 `systemctl restart`、`rm`、`sed -i`、`echo x > /tmp/out` 以及**任何不认识的工具**。

代价是明确的：一个真正只读但没被收录的工具也会被拒。这是 fail-closed 的代价，不是 bug。

### 审批

```powershell
host-cli run 'systemctl restart nginx' --profile prod01 --request-approval
# → {"token":"3f9a2c1d","expires_at":"..."}   什么都没执行

host-cli run 'systemctl restart nginx' --profile prod01 --approve 3f9a2c1d
```

token 绑定到**具体命令的摘要** + **具体 profile** + **10 分钟有效期**，用于别的命令会明确报 `issued for a different command`。审批文件只存命令的 SHA-256，不存命令本身。

## 结果如何分类

每次调用恰好落在一种 `outcome` 上。判断依据是 ssh 的调试日志（`-E` 单独落盘，不污染远端 stderr），而不是猜。

| `outcome` | 含义 |
|---|---|
| `success` | 远端命令退出 0 |
| `remote_nonzero_exit` | 远端命令退出非 0，`data.remote_exit_code` 是它真实的退出码 |
| `remote_killed_by_signal` | 远端进程被信号终止 |
| `timeout` | 本地超时，`remote_state` 为 `unknown` |
| `authentication_failed` | 凭据被拒绝 |
| `host_key_untrusted` | 主机密钥未知或与记录不符 |
| `connection_failed` | DNS、拒绝、中断等 |
| `credential_store_unavailable` | 系统凭据库读写失败 |
| `ssh_client_unavailable` | 找不到 ssh 客户端 |

`error.code` 与 `outcome` 同名，消费方按 `code` 分支，**不要解析 `message`**。门禁另有 `dangerous_command`、`read_only_violation`、`approval_required`、`rate_limited`。

## 审计

每次调用都会追加一行到本地日志，**包括被拒绝和 dry-run 的调用**：

```text
%LOCALAPPDATA%\host-cli\host-cli\Logs\audit.jsonl
```

```powershell
host-cli audit summary                    # 按状态和危险类别计数
host-cli audit show --status blocked --limit 10
```

类别计数是有用的观测：从不触发的规则可能是废规则，天天触发的规则是在训练操作者闭眼按 `--force`。

## 六件必须知道的事

1. **不是交互式终端。** 不分配 pty，`vim`、`top`、`less` 和需要终端的 `sudo` 不可用。需要提权用 `sudo -n`。
2. **远端命令等价于 `ssh user@host '<cmd>'`。** 登录 shell、home 起手、不继承本地环境变量，工具零注入。远端 `PATH` 有问题时工具不会替你修 —— 用 `run 'echo $PATH'` 自己核对。
3. **后台任务不会自动放手。** 远端还有子进程把持 stdout/stderr 时会一直等到超时；要立即返回就自己摘掉输出：`nohup cmd >/dev/null 2>&1 &`。
4. **超时后远端状态未知。** 本地断开不等于远端停止，`remote_state` 会是 `unknown`；重试前请先确认。
5. **进程退出码不是远端退出码。** 工具只用 0/1；远端退出码在 `data.remote_exit_code`。
6. **退出码只有 8 位。** sshd 中继的是 `WEXITSTATUS`，所以远端 `exit 256` 会到达为 `0`。这是协议限制，无法还原。

## 主机密钥

强制校验，没有旁路，也没有「一律接受」开关。首次连接未知主机会失败并报告 `host_key_untrusted`；请人工核实后自行登记：

```powershell
ssh-keyscan -t ed25519 app01.example.internal >> $env:USERPROFILE\.ssh\known_hosts
```

已受信但密钥变化会报告 `host_key_changed` 并附上实际看到的指纹 —— 这比未知主机更值得警惕。工具不会代为接受任何密钥。

## 不做的事

不包装任何具体命令（没有 `logs`/`health`/`ps` 子命令），不判断业务是否正常，不保存业务清单，不部署/构建/迁移，不操作数据库，不做端口转发/SFTP/透传 ssh 选项。需要什么就 `run` 什么。

`profile validate` 是唯一的例外：它发送 `true`，因为那是唯一能证明「连通、密钥、凭据都对」而不改动任何东西的命令。

## 开发

```powershell
uv sync
uv run python -m pytest packages/host-cli/tests -q
uv run ruff check packages/host-cli
uv run ruff format --check packages/host-cli
uv run python -m mypy packages/host-cli/src
```

测试包内的 `conftest.py` 有 autouse fixture 把 `socket.connect` 与 `subprocess.Popen/run` 换成抛异常：**任何测试想连网或起进程都会立即失败**。这条约束来自 2026-11-20 的真实事故，不依赖自觉。
