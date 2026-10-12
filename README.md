# rootless-stack / base

Host setup and conventions shared by every
[rootless-stack](https://github.com/rootless-stack) stack.  Each stack is
its own repository and lists what it needs:

| Stack | What | Needs |
| --- | --- | --- |
| [dns](https://github.com/rootless-stack/dns) | validating resolver for the host (not containers) | nothing |
| [ldap](https://github.com/rootless-stack/ldap) | lldap user directory | base |
| [mail](https://github.com/rootless-stack/mail) | Postfix, Dovecot, Rspamd, ClamAV | base, ldap, dns |
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
- **Pinned or signed images.**  Upstream images are referenced by tag
  plus digest.  Our own images by tag alone, with `AutoUpdate=registry`:
  their signature, not a digest, makes them trustworthy (below).
- **Plain systemd.**  Each stack has an anchor unit, `<stack>.service`,
  that starts, stops and restarts all its containers.  Healthchecks gate
  readiness, and an unhealthy container is restarted on its own.
- **Local changes in drop-ins**
  (`~/.config/containers/systemd/<unit>.container.d/*.conf`), so shipped
  units can be replaced on update.

## Signed images and automatic updates

Images under `ghcr.io/rootless-stack/` are published only after their
stack's tests pass, and signed twice, both signatures logged in
[Rekor](https://docs.sigstore.dev/logging/overview/), the public
transparency log:

- **keyless**, by the publishing workflow;
- with the **org key** ([sigstore/cosign.pub](sigstore/cosign.pub)), which
  Podman checks itself, without cosign.

With [containers/policy.json](containers/policy.json) in a stack user's
`~/.config/containers/`, Podman refuses any image from
`ghcr.io/rootless-stack/` that lacks a valid org-key signature or its Rekor
entry; other registries are unaffected.  As the stack user:

```sh
mkdir -p ~/.config/containers/registries.d
cp /opt/rootless-stack/base/containers/policy.json ~/.config/containers/
cp /opt/rootless-stack/base/containers/registries.d/* ~/.config/containers/registries.d/
```

Units of signed images carry `AutoUpdate=registry`.  To keep them current,
enable Podman's timer as the stack user:

```sh
systemctl --user enable --now podman-auto-update.timer
```

Once a day it pulls a newer image for the unit's tag, checked against the
policy, restarts the container and rolls back if the new one does not
come up healthy.  Images from other registries are pinned by digest and
change only with the repository.

To check a signature by hand with cosign instead:

```sh
cosign verify ghcr.io/rootless-stack/<image>:<tag> \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity https://github.com/rootless-stack/.github/.github/workflows/promote-image.yml@refs/heads/main \
  --certificate-github-workflow-repository rootless-stack/<stack>
```

## Optional: port reservation

Stacks that serve ports below 1024 (mail: 25, 465, 587, 993) need
`net.ipv4.ip_unprivileged_port_start = 25`, which lets **every** user bind
25-1023.  Podman offers no per-user alternative: a capability does not
reach across a rootless container's user namespace.

[hardening/ports](hardening/ports/) restores that protection, and makes it
stricter than the kernel's, from one file listing which stack user serves
which ports:

1. **nftables:** traffic to 25-1023 (TCP and UDP) reaches a socket only if
   it belongs to a system service (`system.slice`, `init.scope`) or to the
   stack user that owns the port.  Anyone else's listener gets nothing.
2. **systemd:** a listed stack user can bind only its own ports in that
   range (`SocketBindDeny=` / `SocketBindAllow=` on its slice), in any
   network namespace, plus 53 for Podman's container DNS.

As root:

```sh
P=/opt/rootless-stack/base/hardening/ports
install -m 0755 $P/rootless-port-reservation /usr/local/sbin/
install -D -m 0644 $P/ports.conf.example /etc/rootless-stack/ports.conf   # then edit it
install -m 0644 $P/rootless-port-reservation.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now rootless-port-reservation.service
```

After editing `ports.conf`: `systemctl reload rootless-port-reservation`,
then restart the affected stacks.  Things to know:

- A connection to a reserved port nobody may serve is dropped silently,
  not refused.
- A root process started from a login shell runs in `user-0.slice`, not
  `system.slice`, and gets no traffic on reserved ports.
- A listed stack cannot bind other ports below 1024 even inside its own
  containers' networks.
- Ports above 1023 (e.g. ManageSieve on 4190) are not covered.

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
