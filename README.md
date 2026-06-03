# AutoTunnel-X

AutoTunnel-X is an Ubuntu LTS orchestration framework for deploying, benchmarking, and failing over across many tunnel transports. It is designed to be installed on both sides of a two-node topology:

- `inbound`: the server that initiates outbound/reverse sessions when needed.
- `outbound`: the public peer that accepts listener-oriented transports.

The framework uses a Bash installer for host preparation and Python services for orchestration and the Web UI.

## Transport Inventory

AutoTunnel-X ships with 28 protocol profiles:

| Family | Profiles |
| --- | --- |
| Classic Linux L3 | GRE, IPIP, SIT/6to4 |
| L3 VPN | WireGuard, OpenVPN UDP, OpenVPN TCP |
| Reverse proxy / forwarders | FRP, Rathole, Chisel, Gost TCP, Gost UDP, Gost WS/TLS |
| Secure encapsulation | WSTunnel, ShadowTLS, autossh |
| Xray-core | VLESS Reality, VLESS gRPC, VLESS WS, Trojan gRPC, Trojan TLS |
| UDP transports | Hysteria 2, TUIC v5, Juicity |
| CDN / DNS | cloudflared, Arvan/CDN over Gost WS/TLS, NaiveProxy, Iodine, DNScat |

Account-bound transports are fully implemented but remain in `waiting_for_credentials` until their required operator-owned values are set:

- `cloudflared`: `credentials.cloudflared_token` and `credentials.cloudflared_hostname`
- `arvan_cdn`: `credentials.cdn_host`
- `iodine_dns` and `dnscat3`: `credentials.dns_tunnel_domain`
- WireGuard and Xray Reality require peer public material; use the sync flow below.

## Directory Layout

```text
/opt/autotunnel-x                application code and Python venv
/etc/autotunnel-x/config.yaml    runtime configuration
/var/lib/autotunnel-x/state.db   status, metrics, manual override state
/var/lib/autotunnel-x/protocols  generated per-transport config
/var/log/autotunnel/engine.log   structured JSON engine log
/var/log/autotunnel/webui.log    structured JSON Web UI log
```

## Install

Run on each server from the repository root.

Outbound server:

```bash
sudo ./install.sh \
  --role outbound \
  --peer INBOUND_PUBLIC_IP_OR_DNS \
  --web-port 8088 \
  --admin-user admin
```

Inbound server:

```bash
sudo ./install.sh \
  --role inbound \
  --peer OUTBOUND_PUBLIC_IP_OR_DNS \
  --web-port 8088 \
  --admin-user admin
```

The installer:

1. Validates Ubuntu 22.04/24.04.
2. Installs Docker, Go, Python, iptables/nftables, iproute2, iperf3, WireGuard, OpenVPN, autossh, iodine, systemd assets, and support tools.
3. Writes `/etc/autotunnel-x/config.yaml`.
4. Enables `autotunnel-engine.service` and `autotunnel-webui.service`.
5. Opens the Web UI and managed tunnel port ranges when UFW is active.

## First Sync

After the engine deploys the first time, run sync in both directions to exchange WireGuard and Xray Reality public material.

On outbound:

```bash
sudo autotunnelctl sync \
  --peer-url http://INBOUND_PUBLIC_IP_OR_DNS:8088 \
  --token INBOUND_BOOTSTRAP_TOKEN
sudo systemctl restart autotunnel-engine
```

On inbound:

```bash
sudo autotunnelctl sync \
  --peer-url http://OUTBOUND_PUBLIC_IP_OR_DNS:8088 \
  --token OUTBOUND_BOOTSTRAP_TOKEN
sudo systemctl restart autotunnel-engine
```

The bootstrap token is printed by `autotunnelctl init` during installation and stored in `/etc/autotunnel-x/config.yaml` under `peer.bootstrap_token`.

## Operations

Status:

```bash
sudo autotunnelctl status
```

Force deployment:

```bash
sudo autotunnelctl deploy
```

Run one benchmark cycle:

```bash
sudo autotunnelctl benchmark
```

Follow logs:

```bash
sudo journalctl -u autotunnel-engine -f
sudo tail -f /var/log/autotunnel/engine.log | jq
```

Dashboard:

```text
http://SERVER_IP:8088
```

## Failover and Load Balancing

Every benchmark cycle records:

- RTT latency
- jitter
- packet loss
- throughput from `iperf3` where available, otherwise short HTTPS probes
- computed tunnel score

`routing.mode: failover` selects the highest-scoring usable transport. `routing.mode: loadbalance` selects the top `routing.load_balance_top_n` transports.

L3 tunnel routing uses `ip route replace`. Proxy tunnel routing uses an `AUTOTUNNELX_PROXY` NAT chain and iptables nth mode for load-balanced proxy selection.

## Systemd Services

Core services:

```text
autotunnel-engine.service
autotunnel-webui.service
```

Each deployed transport gets its own generated unit:

```text
autotunnel-tunnel-<name>.service
```

Examples:

```bash
sudo systemctl status autotunnel-tunnel-wireguard
sudo systemctl restart autotunnel-tunnel-hysteria2
```

## Security Notes

- Use this framework only on infrastructure you own or administer.
- Keep `/etc/autotunnel-x/config.yaml` root-readable only; it contains shared tunnel credentials.
- Put the Web UI behind a private management network or an additional reverse proxy with TLS for production.
- Replace snakeoil certificates with valid certificates for TLS-based transports where clients validate certificates.
- Review local laws, provider policies, and enterprise change-control rules before enabling CDN or DNS tunnel profiles.
