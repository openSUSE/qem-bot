#!BuildTag: opensuse/qem-bot:latest opensuse/qem-bot:%RELEASE%
FROM opensuse/tumbleweed

# labelprefix=org.opensuse.qem-bot
LABEL org.opencontainers.image.title="qem-bot container"
LABEL org.opencontainers.image.description="Tool for scheduling maintenance tests on openQA"
LABEL org.opencontainers.image.version="%RELEASE%"
LABEL org.opensuse.reference="registry.opensuse.org/opensuse/qem-bot:%RELEASE%"
LABEL org.openbuildservice.disturl="%DISTURL%"
LABEL org.opencontainers.image.created="%BUILDTIME%"
# endlabelprefix

COPY container-packages.txt /tmp/container-packages.txt
RUN zypper --gpg-auto-import-keys ref \
    && zypper in -y -C $(cat /tmp/container-packages.txt) \
    && zypper clean -a

WORKDIR /app
COPY . .

RUN ./qem-bot.py --help

ENTRYPOINT ["./qem-bot.py"]
