#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="autotunnel-x"
APP_USER="autotunnel"
APP_GROUP="autotunnel"
INSTALL_DIR="/opt/autotunnel-x"
CONFIG_DIR="/etc/autotunnel-x"
STATE_DIR="/var/lib/autotunnel-x"
LOG_DIR="/var/log/autotunnel"
VENV_DIR="${INSTALL_DIR}/venv"
ROLE=""
PEER_HOST=""
WEB_PORT="8088"
ADMIN_USER="admin"
ADMIN_PASSWORD=""
NON_INTERACTIVE="false"

usage() {
  cat <<USAGE
AutoTunnel-X installer for Ubuntu Server 22.04/24.04 LTS.

Usage:
  sudo ./install.sh --role inbound|outbound --peer <peer-public-ip-or-host> [options]

Options:
  --web-port <port>         Web UI listen port. Default: 8088
  --admin-user <name>       Dashboard admin username. Default: admin
  --admin-password <pass>   Dashboard admin password. Generated if omitted in non-interactive mode.
  --non-interactive         Do not prompt.
  -h, --help                Show this help.
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

log() {
  echo "[autotunnel-x] $*"
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "Run this installer as root."
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --role) ROLE="${2:-}"; shift 2 ;;
      --peer) PEER_HOST="${2:-}"; shift 2 ;;
      --web-port) WEB_PORT="${2:-}"; shift 2 ;;
      --admin-user) ADMIN_USER="${2:-}"; shift 2 ;;
      --admin-password) ADMIN_PASSWORD="${2:-}"; shift 2 ;;
      --non-interactive) NON_INTERACTIVE="true"; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unknown argument: $1" ;;
    esac
  done
}

prompt_missing() {
  if [[ -z "${ROLE}" && "${NON_INTERACTIVE}" != "true" ]]; then
    read -r -p "Server role (inbound/outbound): " ROLE
  fi
  if [[ -z "${PEER_HOST}" && "${NON_INTERACTIVE}" != "true" ]]; then
    read -r -p "Peer public IP or DNS name: " PEER_HOST
  fi
  if [[ -z "${ADMIN_PASSWORD}" && "${NON_INTERACTIVE}" != "true" ]]; then
    read -r -s -p "Web admin password: " ADMIN_PASSWORD
    echo
  fi
  [[ "${ROLE}" == "inbound" || "${ROLE}" == "outbound" ]] || die "--role must be inbound or outbound."
  [[ -n "${PEER_HOST}" ]] || die "--peer is required."
  if [[ -z "${ADMIN_PASSWORD}" ]]; then
    ADMIN_PASSWORD="$(openssl rand -base64 24 | tr -d '\n')"
    log "Generated admin password: ${ADMIN_PASSWORD}"
  fi
}

detect_ubuntu() {
  if [[ ! -f /etc/os-release ]]; then
    die "Unsupported operating system. Ubuntu 22.04/24.04 LTS is required."
  fi
  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${ID}" != "ubuntu" ]]; then
    die "Unsupported distribution: ${PRETTY_NAME:-unknown}. Ubuntu 22.04/24.04 LTS is required."
  fi
  case "${VERSION_ID}" in
    22.04|24.04) ;;
    *) die "Unsupported Ubuntu version ${VERSION_ID}. Use 22.04 or 24.04 LTS." ;;
  esac
}

install_packages() {
  export DEBIAN_FRONTEND=noninteractive
  log "Updating apt metadata."
  apt-get update -y
  log "Installing base networking, build, and runtime packages."
  apt-get install -y \
    ca-certificates curl gnupg lsb-release software-properties-common \
    python3 python3-venv python3-pip python3-dev build-essential \
    git jq yq openssl systemd iproute2 iputils-ping iperf3 \
    iptables nftables ufw wireguard wireguard-tools openvpn \
    autossh openssh-client openssh-server iodine moreutils logrotate \
    net-tools dnsutils socat tar unzip ssl-cert rsync

  if ! command -v docker >/dev/null 2>&1; then
    log "Installing Docker CE."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    . /etc/os-release
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi

  if ! command -v go >/dev/null 2>&1; then
    log "Installing Go from Ubuntu packages."
    apt-get install -y golang-go
  fi

  systemctl enable --now docker
}

create_users_dirs() {
  if ! getent group "${APP_GROUP}" >/dev/null; then
    groupadd --system "${APP_GROUP}"
  fi
  if ! id "${APP_USER}" >/dev/null 2>&1; then
    useradd --system --gid "${APP_GROUP}" --home-dir "${STATE_DIR}" --shell /usr/sbin/nologin "${APP_USER}"
  fi
  install -d -m 0755 "${INSTALL_DIR}"
  install -d -m 0750 -o root -g "${APP_GROUP}" "${CONFIG_DIR}"
  install -d -m 0750 -o root -g "${APP_GROUP}" "${STATE_DIR}"
  install -d -m 0750 -o root -g "${APP_GROUP}" "${STATE_DIR}/protocols"
  install -d -m 0750 -o root -g "${APP_GROUP}" "${LOG_DIR}"
}

copy_tree() {
  log "Copying project files to ${INSTALL_DIR}."
  rsync -a --delete \
    --exclude ".git" \
    --exclude "venv" \
    --exclude "__pycache__" \
    "$(pwd)/" "${INSTALL_DIR}/"
}

setup_python() {
  log "Creating Python virtual environment."
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
  "${VENV_DIR}/bin/python" -m pip install "${INSTALL_DIR}"
  ln -sf "${VENV_DIR}/bin/autotunnelctl" /usr/local/bin/autotunnelctl
}

install_units() {
  log "Installing systemd services and logrotate policy."
  install -m 0644 "${INSTALL_DIR}/packaging/systemd/autotunnel-engine.service" /etc/systemd/system/autotunnel-engine.service
  install -m 0644 "${INSTALL_DIR}/packaging/systemd/autotunnel-webui.service" /etc/systemd/system/autotunnel-webui.service
  install -m 0644 "${INSTALL_DIR}/packaging/logrotate/autotunnel" /etc/logrotate.d/autotunnel
  systemctl daemon-reload
}

configure_app() {
  log "Writing initial AutoTunnel-X configuration."
  "${VENV_DIR}/bin/autotunnelctl" init \
    --role "${ROLE}" \
    --peer "${PEER_HOST}" \
    --config "${CONFIG_DIR}/config.yaml" \
    --state-dir "${STATE_DIR}" \
    --log-dir "${LOG_DIR}" \
    --web-port "${WEB_PORT}" \
    --admin-user "${ADMIN_USER}" \
    --admin-password "${ADMIN_PASSWORD}"
}

open_firewall() {
  log "Applying firewall baseline."
  if ufw status >/dev/null 2>&1 && ufw status | grep -qi "Status: active"; then
    ufw allow OpenSSH || true
    ufw allow "${WEB_PORT}/tcp" comment "AutoTunnel-X Web UI" || true
    ufw allow 50000:50100/tcp comment "AutoTunnel-X TCP transports" || true
    ufw allow 50000:50100/udp comment "AutoTunnel-X UDP transports" || true
    ufw allow 51820/udp comment "AutoTunnel-X WireGuard" || true
  else
    log "UFW is inactive; AutoTunnel-X will manage iptables/nftables at runtime."
  fi
}

start_services() {
  log "Enabling and starting services."
  systemctl enable --now autotunnel-engine.service
  systemctl enable --now autotunnel-webui.service
  log "Dashboard: http://$(hostname -I | awk '{print $1}'):${WEB_PORT}"
}

main() {
  require_root
  parse_args "$@"
  prompt_missing
  detect_ubuntu
  install_packages
  create_users_dirs
  copy_tree
  setup_python
  install_units
  configure_app
  open_firewall
  start_services
  log "Installation complete."
}

main "$@"
