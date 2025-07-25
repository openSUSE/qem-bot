FROM opensuse/tumbleweed:latest

# Add repository for internal CA and install dependencies
RUN zypper ar https://download.opensuse.org/repositories/SUSE:/CA/openSUSE_Tumbleweed/SUSE:CA.repo \
    && zypper --gpg-auto-import-keys ref \
    && zypper in -y -C \
        ca-certificates-suse \
        git \
        openssh-clients \
        python3-jsonschema \
        python3-openqa_client \
        python3-osc \
        python3-pika \
        python3-requests \
        python3-ruamel.yaml \
    && zypper clean -a

# Install application
WORKDIR /app
COPY . .
# Alternatively, use sources from git
# RUN git clone https://github.com/openSUSE/qem-bot .

# Clone metadata
RUN git clone --depth 1 https://gitlab.suse.de/qa-maintenance/metadata.git

# Create directory for osc configuration
RUN mkdir -p /root/.config/osc

ENTRYPOINT ["./qem-bot.py", "-c", "metadata/qem-bot", "-s", "metadata/qem-bot/singlearch.yml"]
