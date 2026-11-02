# Containerized deployment using Podman and Quadlets

## Variants

Two container variants are supported:

- **Internal SUSE variant** (`containers/suse/Containerfile`):
  Uses the internal SUSE CA and bakes the internal `metadata` repository clone.
  Built locally on host as `localhost/qem-bot` via `qem-bot.build`.

- **openSUSE variant** (`containers/opensuse/Dockerfile`):
  Pure openSUSE Tumbleweed container using upstream distribution packages.
  Published by OBS to `registry.opensuse.org/opensuse/qem-bot:latest`.
  Deployment uses external configuration mounted at `/etc/openqabot` (such as
  the standalone quadlet `containers/systemd/qem-bot-opensuse.container`).

Both variants install their zypper package set from `container-packages.txt`.

## Local deployment (SUSE internal)

0. Complete steps from [qem-dashboard](https://github.com/openSUSE/qem-dashboard/tree/main/docs/Containers.md)
1. `cd /var/lib/data/qem`
2. `git clone https://github.com/openSUSE/qem-bot.git`
3. `echo -e "GITEA_TOKEN=123\nDASHBOARD_TOKEN=s3cret\nQEM_DASHBOARD_URL=http://localhost:3000/" > /var/lib/data/qem/qem-bot.env`
4. ```
cat > /var/lib/data/qem/oscrc <<EOF
[general]
apiurl = https://api.suse.de

[https://api.suse.de]
user=qem-bot
credentials_mgr_class=osc.credentials.TransientCredentialsManager
EOF
```
5. ```
mkdir -p /var/lib/data/qem/ssh
echo "$SSH_PRIV_KEY" > /var/lib/data/qem/ssh/id_rsa
chmod 600 /var/lib/data/qem/ssh/id_rsa
```
6. `ln -s "$PWD/qem-bot/containers/systemd/qem-bot.build" "$PWD/qem-bot/containers/systemd/qem-bot-gitea-sync.container" /etc/containers/systemd/`
   (builds the internal SUSE image from `containers/suse/Containerfile` via `qem-bot.build`)
7. `systemctl daemon-reload && systemctl start qem-bot-gitea-sync`

## OBS container build and deployment (openSUSE)

The openSUSE container is automatically built in the Open Build Service project
`devel:openQA` under the package `qem-bot-container` using `containers/opensuse/_service`.

To configure automatic rebuilds on GitHub `master` branch push:

1. In OBS project `devel:openQA`, create or configure package `qem-bot-container`
   with repository `containers` enabled, and upload `containers/opensuse/_service`.
2. Generate an OBS API token for `devel:openQA/qem-bot-container` with `operation=runservice`
   via the OBS WebUI (`/users/tokens`) or API (`POST /person/<user>/token`).
3. In GitHub repository settings (`openSUSE/qem-bot`), add a webhook:
   - Payload URL: `https://api.opensuse.org/trigger/webhook?id=<token_id>`
   - Content type: `application/json`
   - Secret: `<token_secret_string>`
   - Events: `push` (branch: `master`)

Published images are available at:
`registry.opensuse.org/opensuse/qem-bot:latest`

### Deployment on a host

1. `mkdir -p /var/lib/data/qem/config` and put the `.yml` configuration files
   there as described in [config](config.md), e.g.
   `cp metadata/qem-bot/*.yml /var/lib/data/qem/config/`
2. `ln -s "$PWD/qem-bot/containers/systemd/qem-bot-opensuse.container" /etc/containers/systemd/`
3. `systemctl daemon-reload && systemctl start qem-bot-opensuse podman-auto-update.timer`
   (`podman-auto-update.timer` is needed for `AutoUpdate=registry`)
