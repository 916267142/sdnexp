#!/usr/bin/env python3
"""Generate FRR BGP configs for a k=4 Fat-tree.

Design summary:
- Topology: 4 core, 8 aggregation, 8 edge switches.
- ASN: each switch gets a unique private ASN (65001+).
- Switch-switch links: /31 from 10.0.0.0/16.
- Host-edge links: /30 from 172.16.0.0/16 (edge gateway + host).

Output:
- One config per switch in <output>/config/*.conf
"""

from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path


def next_intf(index_map: dict[str, int], sw: str) -> str:
    index_map[sw] += 1
    return f"Ethernet1-{index_map[sw]}"


def build_switches() -> list[str]:
    core = ["c0_0", "c0_1", "c1_0", "c1_1"]
    agg = [f"a{pod}_{i}" for pod in range(4) for i in range(2)]
    edge = [f"e{pod}_{i}" for pod in range(4) for i in range(2)]
    return core + agg + edge


def build_model() -> dict[str, dict[str, object]]:
    switches = build_switches()

    switch_asn: dict[str, int] = {}
    for idx, sw in enumerate(switches, start=1):
        switch_asn[sw] = 65000 + idx

    state: dict[str, dict[str, object]] = {
        sw: {"asn": switch_asn[sw], "ifaces": [], "neighbors": [], "networks": []}
        for sw in switches
    }
    intf_index = {sw: 0 for sw in switches}

    p2p_pool = ipaddress.ip_network("10.0.0.0/16").subnets(new_prefix=31)
    host_pool = ipaddress.ip_network("172.16.0.0/16").subnets(new_prefix=30)

    def add_switch_link(sw1: str, sw2: str) -> None:
        subnet = next(p2p_pool)
        hosts = list(subnet.hosts())
        ip1 = f"{hosts[0]}/{subnet.prefixlen}"
        ip2 = f"{hosts[1]}/{subnet.prefixlen}"

        intf1 = next_intf(intf_index, sw1)
        intf2 = next_intf(intf_index, sw2)

        state[sw1]["ifaces"].append((intf1, ip1))
        state[sw2]["ifaces"].append((intf2, ip2))

        state[sw1]["neighbors"].append((str(hosts[1]), state[sw2]["asn"]))
        state[sw2]["neighbors"].append((str(hosts[0]), state[sw1]["asn"]))

    def add_host_link(edge_sw: str) -> None:
        subnet = next(host_pool)
        hosts = list(subnet.hosts())
        gw_ip = str(hosts[0])

        intf = next_intf(intf_index, edge_sw)
        state[edge_sw]["ifaces"].append((intf, f"{gw_ip}/{subnet.prefixlen}"))
        state[edge_sw]["networks"].append(str(subnet))

    for pod in range(4):
        a0 = f"a{pod}_0"
        a1 = f"a{pod}_1"
        e0 = f"e{pod}_0"
        e1 = f"e{pod}_1"

        # Aggregation <-> core.
        add_switch_link(a0, "c0_0")
        add_switch_link(a0, "c1_0")
        add_switch_link(a1, "c0_1")
        add_switch_link(a1, "c1_1")

        # Edge <-> aggregation.
        add_switch_link(e0, a0)
        add_switch_link(e0, a1)
        add_switch_link(e1, a0)
        add_switch_link(e1, a1)

        # Two hosts per edge switch.
        add_host_link(e0)
        add_host_link(e0)
        add_host_link(e1)
        add_host_link(e1)

    return state


def render_config(sw: str, sw_state: dict[str, object]) -> str:
    asn = sw_state["asn"]
    ifaces = sw_state["ifaces"]
    neighbors = sorted(sw_state["neighbors"], key=lambda item: item[0])
    networks = sorted(set(sw_state["networks"]))

    lines: list[str] = []
    lines.append("frr defaults datacenter")
    lines.append("!")
    lines.append("!")

    for intf, ip_cidr in ifaces:
        lines.append(f"interface {intf}")
        lines.append(f"  ip address {ip_cidr}")
        lines.append("!")

    lines.append("!")
    lines.append(f"router bgp {asn}")
    # lines.append("  bgp bestpath as-path multipath-relax")
    lines.append("  maximum-paths 64")

    for neigh_ip, neigh_asn in neighbors:
        lines.append(f"  neighbor {neigh_ip} remote-as {neigh_asn}")

    for network in networks:
        lines.append(f"  network {network}")

    lines.append("")
    return "\n".join(lines)


def write_configs(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    config_dir = output_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    state = build_model()
    for sw in build_switches():
        (config_dir / f"{sw}.conf").write_text(
            render_config(sw, state[sw]), encoding="utf-8"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate FRR BGP config files for a k=4 Fat-tree"
    )
    parser.add_argument(
        "-o",
        "--output",
        default=".",
        help="Output directory. Configs are written to <output>/config (default: current directory)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out = Path(args.output)
    write_configs(out)
    print(f"Generated FRR configs at: {out / 'config'}")


if __name__ == "__main__":
    main()
