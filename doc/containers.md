# Containerized deployment using Podman and quadlets

0. Complete steps from [qem-dashboard](https://github.com/openSUSE/qem-dashboard/tree/main/docs/Containers.md)
1. `cd /var/lib/data/qem`
2. `git clone https://github.com/openSUSE/qem-bot.git`
3. `echo -e "GITEA_TOKEN=123\nDASHBOARD_TOKEN=s3cret" > /var/lib/data/qem/qem-bot.env`
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
6. `for quadlet in qem-bot/containers/systemd/*; do ln -s "$PWD/$quadlet" /etc/containers/systemd/; done`
7. `systemctl daemon-reload && systemctl start qem-bot-gitea-sync`
