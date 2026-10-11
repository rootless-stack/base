# rootless-stack / base

Host setup and conventions shared by every
[rootless-stack](https://github.com/rootless-stack) stack.  Each stack is
its own repository and lists what it needs:

| Stack | What | Needs |
| --- | --- | --- |
| [ldap](https://github.com/rootless-stack/ldap) | lldap user directory | base |
| [mail](https://github.com/rootless-stack/mail) | Postfix, Dovecot, Rspamd, ClamAV | base, ldap |
| security | CrowdSec with stack-specific rules | planned |
| web | Caddy front door, ACME | planned |
| cloud | Nextcloud | planned |
| wordpress | WordPress | planned |

Each stack runs as its own unprivileged Linux user, one Quadlet unit per
container, with no root daemon and no orchestrator.  Hosts need `podman`
(5.0 or newer) and `systemd` to run them; setting a stack up also uses
`openssl` and, for stacks with configuration templates, Python 3.11+ with
Jinja2 (`render.py`).

## Host setup

Clone each repository you use into `/opt/rootless-stack/<name>`; the
stacks' READMEs assume that layout.  Once per host, as root:

```sh
git clone https://github.com/rootless-stack/base /opt/rootless-stack/base
install -D -m 0644 /opt/rootless-stack/base/seccomp/rootless-stack.json \
  /etc/containers/seccomp/rootless-stack.json
install -m 0644 /opt/rootless-stack/base/tmpfiles.d/rootless-ipc.conf /etc/tmpfiles.d/
systemd-tmpfiles --create
```

Then follow each stack's README, prerequisites first.

## Conventions

Every stack follows these, so stacks combine without knowing each other's
internals.

- **One user per stack** (`<stack>-svc`), with its own uid, subuid range,
  Podman storage and user namespace, and lingering enabled.  In its home:
  `config/` (rendered configuration, `config/env` for non-secret
  variables), `secrets/` (one file per secret, mounted read-only),
  `data/` (persistent state), and the units under `.config/`.
- **Least privilege.**  Every container drops all capabilities and adds
  back only what a daemon needs, runs on a read-only root filesystem with
  sized tmpfs mounts, and uses `NoNewPrivileges` and the seccomp profile
  in this repository.
- **No secrets in the environment** or on command lines.  Secrets are
  files.
- **Sockets between stacks.**  A stack that serves others binds Unix
  sockets under `/run/rootless-ipc/<service>/`; those paths are its public
  interface, listed in its README.  The directory's ACL is the gate.  The
  provider's tmpfiles file creates the directories; each consumer appends
  its own grants (`a+`) in its own tmpfiles file, including its host user,
  which Podman needs to set up the mount.
- **SELinux and AppArmor alike.**  Mounts carry `:Z` (private to one
  container) or `:z` (shared within the stack).  A mount of another
  stack's directory carries neither: only the owner may relabel it.
- **Pinned images.**  Every image reference is tag plus digest.
- **Plain systemd.**  Each stack has an anchor unit, `<stack>.service`,
  that starts, stops and restarts all its containers.  Healthchecks gate
  readiness, and an unhealthy container is restarted on its own.
- **Local changes in drop-ins**
  (`~/.config/containers/systemd/<unit>.container.d/*.conf`), so shipped
  units can be replaced on update.

## render.py

```sh
python3 /opt/rootless-stack/base/render.py SRC DST VARS.toml SECRETS_DIR
```

Copies a stack's template tree, rendering `*.j2` with Jinja2.  Templates
see the variables from `VARS.toml`, `secret.<name>` for every file in
`SECRETS_DIR`, and the filter `user | subuid(n)`, which gives the host uid
that container uid `n` of a rootless user maps to.

## License

[Apache License 2.0](LICENSE).
