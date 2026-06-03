from __future__ import annotations

import logging
from typing import Any

from .base import ProtocolAdapter
from .classic import ClassicTunnelAdapter
from .containers import (
    ArvanCdnAdapter,
    ChiselAdapter,
    CloudflaredAdapter,
    Dnscat3Adapter,
    FrpAdapter,
    GostAdapter,
    Hysteria2Adapter,
    IodineAdapter,
    JuicityAdapter,
    NaiveProxyAdapter,
    RatholeAdapter,
    ShadowTLSAdapter,
    TuicAdapter,
    WSTunnelAdapter,
)
from .openvpn import OpenVPNAdapter
from .ssh import AutosshAdapter
from .wireguard import WireGuardAdapter
from .xray import XrayAdapter


ADAPTERS: dict[str, type[ProtocolAdapter]] = {
    "gre": ClassicTunnelAdapter,
    "ipip": ClassicTunnelAdapter,
    "sit": ClassicTunnelAdapter,
    "wireguard": WireGuardAdapter,
    "openvpn": OpenVPNAdapter,
    "frp": FrpAdapter,
    "rathole": RatholeAdapter,
    "chisel": ChiselAdapter,
    "gost_tcp": GostAdapter,
    "gost_udp": GostAdapter,
    "gost_ws_tls": GostAdapter,
    "wstunnel": WSTunnelAdapter,
    "shadowtls": ShadowTLSAdapter,
    "ssh_autossh": AutosshAdapter,
    "xray_vless_reality": XrayAdapter,
    "xray_vless_grpc": XrayAdapter,
    "xray_vless_ws": XrayAdapter,
    "xray_trojan_grpc": XrayAdapter,
    "xray_trojan_tls": XrayAdapter,
    "hysteria2": Hysteria2Adapter,
    "tuic_v5": TuicAdapter,
    "juicity": JuicityAdapter,
    "cloudflared": CloudflaredAdapter,
    "arvan_cdn": ArvanCdnAdapter,
    "naiveproxy": NaiveProxyAdapter,
    "iodine_dns": IodineAdapter,
    "dnscat3": Dnscat3Adapter,
}


def adapter_for(spec: dict[str, Any], config: dict[str, Any], logger: logging.Logger) -> ProtocolAdapter:
    cls = ADAPTERS.get(str(spec.get("type")))
    if not cls:
        raise KeyError(f"Unsupported tunnel type: {spec.get('type')}")
    return cls(spec, config, logger)


def adapters_for_config(config: dict[str, Any], logger: logging.Logger) -> list[ProtocolAdapter]:
    return [adapter_for(spec, config, logger) for spec in config.get("protocols", [])]
