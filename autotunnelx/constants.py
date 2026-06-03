from __future__ import annotations

DEFAULT_CONFIG_PATH = "/etc/autotunnel-x/config.yaml"
DEFAULT_STATE_DIR = "/var/lib/autotunnel-x"
DEFAULT_LOG_DIR = "/var/log/autotunnel"
ENGINE_LOG = "engine.log"
WEB_LOG = "webui.log"


def default_protocols() -> list[dict]:
    """Return the default transport inventory.

    Ports are intentionally allocated in a compact high range so the installer
    and firewall manager can reason about them consistently.
    """

    return [
        {
            "name": "gre",
            "type": "gre",
            "enabled": True,
            "mode": "l3",
            "interface": "atx-gre0",
            "local_tunnel_ip": "10.71.0.1/30",
            "peer_tunnel_ip": "10.71.0.2",
        },
        {
            "name": "ipip",
            "type": "ipip",
            "enabled": True,
            "mode": "l3",
            "interface": "atx-ipip0",
            "local_tunnel_ip": "10.71.1.1/30",
            "peer_tunnel_ip": "10.71.1.2",
        },
        {
            "name": "sit6to4",
            "type": "sit",
            "enabled": True,
            "mode": "l3",
            "interface": "atx-sit0",
            "local_tunnel_ip": "fd71:71::1/126",
            "peer_tunnel_ip": "fd71:71::2",
        },
        {
            "name": "wireguard",
            "type": "wireguard",
            "enabled": True,
            "mode": "l3",
            "interface": "atxwg0",
            "listen_port": 51820,
            "local_tunnel_ip": "10.72.0.1/30",
            "peer_tunnel_ip": "10.72.0.2",
        },
        {
            "name": "openvpn_udp",
            "type": "openvpn",
            "enabled": True,
            "mode": "l3",
            "proto": "udp",
            "listen_port": 50010,
            "interface": "tun-atxudp",
            "local_tunnel_ip": "10.72.1.1",
            "peer_tunnel_ip": "10.72.1.2",
        },
        {
            "name": "openvpn_tcp",
            "type": "openvpn",
            "enabled": True,
            "mode": "l3",
            "proto": "tcp-server",
            "client_proto": "tcp-client",
            "listen_port": 50011,
            "interface": "tun-atxtcp",
            "local_tunnel_ip": "10.72.2.1",
            "peer_tunnel_ip": "10.72.2.2",
        },
        {"name": "frp", "type": "frp", "enabled": True, "mode": "proxy", "listen_port": 50020, "local_port": 12020},
        {"name": "rathole", "type": "rathole", "enabled": True, "mode": "proxy", "listen_port": 50021, "local_port": 12021},
        {"name": "chisel", "type": "chisel", "enabled": True, "mode": "proxy", "listen_port": 50022, "local_port": 12022},
        {"name": "gost_tcp", "type": "gost_tcp", "enabled": True, "mode": "proxy", "listen_port": 50023, "local_port": 12023},
        {"name": "gost_udp", "type": "gost_udp", "enabled": True, "mode": "proxy", "listen_port": 50024, "local_port": 12024},
        {"name": "gost_ws_tls", "type": "gost_ws_tls", "enabled": True, "mode": "proxy", "listen_port": 50025, "local_port": 12025},
        {"name": "wstunnel", "type": "wstunnel", "enabled": True, "mode": "proxy", "listen_port": 50026, "local_port": 12026},
        {"name": "shadowtls", "type": "shadowtls", "enabled": True, "mode": "proxy", "listen_port": 50027, "local_port": 12027, "sni": "www.microsoft.com"},
        {"name": "ssh_autossh", "type": "ssh_autossh", "enabled": True, "mode": "proxy", "listen_port": 50028, "local_port": 12028},
        {"name": "xray_vless_reality", "type": "xray_vless_reality", "enabled": True, "mode": "proxy", "listen_port": 50029, "local_port": 12029, "sni": "www.cloudflare.com"},
        {"name": "xray_vless_grpc", "type": "xray_vless_grpc", "enabled": True, "mode": "proxy", "listen_port": 50030, "local_port": 12030, "service_name": "atxgrpc"},
        {"name": "xray_vless_ws", "type": "xray_vless_ws", "enabled": True, "mode": "proxy", "listen_port": 50031, "local_port": 12031, "path": "/atx-ws"},
        {"name": "xray_trojan_grpc", "type": "xray_trojan_grpc", "enabled": True, "mode": "proxy", "listen_port": 50032, "local_port": 12032, "service_name": "atxtrojan"},
        {"name": "xray_trojan_tls", "type": "xray_trojan_tls", "enabled": True, "mode": "proxy", "listen_port": 50033, "local_port": 12033, "sni": "www.bing.com"},
        {"name": "hysteria2", "type": "hysteria2", "enabled": True, "mode": "proxy", "listen_port": 50034, "local_port": 12034, "sni": "www.apple.com"},
        {"name": "tuic_v5", "type": "tuic_v5", "enabled": True, "mode": "proxy", "listen_port": 50035, "local_port": 12035, "sni": "www.mozilla.org"},
        {"name": "juicity", "type": "juicity", "enabled": True, "mode": "proxy", "listen_port": 50036, "local_port": 12036, "sni": "www.google.com"},
        {
            "name": "cloudflared",
            "type": "cloudflared",
            "enabled": True,
            "mode": "proxy",
            "listen_port": 50037,
            "local_port": 12037,
            "credential_keys": ["cloudflared_token", "cloudflared_hostname"],
        },
        {
            "name": "arvan_cdn",
            "type": "arvan_cdn",
            "enabled": True,
            "mode": "proxy",
            "listen_port": 50038,
            "local_port": 12038,
            "credential_keys": ["cdn_host"],
        },
        {"name": "naiveproxy", "type": "naiveproxy", "enabled": True, "mode": "proxy", "listen_port": 50039, "local_port": 12039, "sni": "www.gstatic.com"},
        {
            "name": "iodine_dns",
            "type": "iodine_dns",
            "enabled": True,
            "mode": "l3",
            "listen_port": 53,
            "interface": "dns0",
            "local_tunnel_ip": "10.72.53.1/30",
            "peer_tunnel_ip": "10.72.53.2",
            "credential_keys": ["dns_tunnel_domain"],
        },
        {
            "name": "dnscat3",
            "type": "dnscat3",
            "enabled": True,
            "mode": "proxy",
            "listen_port": 50040,
            "local_port": 12040,
            "credential_keys": ["dns_tunnel_domain"],
        },
    ]
