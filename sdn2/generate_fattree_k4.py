#!/usr/bin/env python3
"""Generate k=4 Fat-tree topology and FRR BGP configs.

Output layout (under --output):
  main.py
  config/
    <switch>.conf
"""

from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
from typing import Dict, List, Tuple


SwitchState = Dict[str, object]


def next_intf(intf_index: Dict[str, int], sw: str) -> str:
    intf_index[sw] += 1
    return f"Ethernet1-{intf_index[sw]}"


def build_k4_model() -> Tuple[
    List[str],
    List[Tuple[str, str, str, str]],
    List[Tuple[str, str, str, str, str]],
    Dict[str, SwitchState],
]:
    """Build abstract k=4 fat-tree model for topology and config generation."""
    core_switches = ["c0_0", "c0_1", "c1_0", "c1_1"]
    agg_switches = [f"a{pod}_{i}" for pod in range(4) for i in range(2)]
    edge_switches = [f"e{pod}_{i}" for pod in range(4) for i in range(2)]
    all_switches = core_switches + agg_switches + edge_switches

    # Unique ASN per switch.
    switch_asn: Dict[str, int] = {}
    for idx, sw in enumerate(all_switches, start=1):
        switch_asn[sw] = 65000 + idx

    intf_index = {sw: 0 for sw in all_switches}
    sw_state: Dict[str, SwitchState] = {
        sw: {"asn": switch_asn[sw], "ifaces": [], "neighbors": [], "networks": []}
        for sw in all_switches
    }

    # 32 switch-switch links in k=4 fat-tree.
    p2p_pool = ipaddress.ip_network("10.0.0.0/16").subnets(new_prefix=31)

    sw_links: List[Tuple[str, str, str, str]] = []
    host_links: List[Tuple[str, str, str, str, str]] = []
    host_pool = ipaddress.ip_network("172.16.0.0/16").subnets(new_prefix=30)

    def add_sw_sw_link(sw1: str, sw2: str) -> None:
        subnet = next(p2p_pool)
        hosts = list(subnet.hosts())
        ip1 = f"{hosts[0]}/31"
        ip2 = f"{hosts[1]}/31"

        intf1 = next_intf(intf_index, sw1)
        intf2 = next_intf(intf_index, sw2)

        sw_state[sw1]["ifaces"].append((intf1, ip1))
        sw_state[sw2]["ifaces"].append((intf2, ip2))
        sw_state[sw1]["neighbors"].append((str(hosts[1]), sw_state[sw2]["asn"]))
        sw_state[sw2]["neighbors"].append((str(hosts[0]), sw_state[sw1]["asn"]))

        sw_links.append((sw1, sw2, intf1, intf2))

    host_id = 0
    for pod in range(4):
        a0 = f"a{pod}_0"
        a1 = f"a{pod}_1"
        e0 = f"e{pod}_0"
        e1 = f"e{pod}_1"

        # Aggregation -> core links.
        add_sw_sw_link(a0, "c0_0")
        add_sw_sw_link(a0, "c1_0")
        add_sw_sw_link(a1, "c0_1")
        add_sw_sw_link(a1, "c1_1")

        # Edge -> aggregation links.
        add_sw_sw_link(e0, a0)
        add_sw_sw_link(e0, a1)
        add_sw_sw_link(e1, a0)
        add_sw_sw_link(e1, a1)

        def add_hosts_for_edge(edge_sw: str) -> None:
            nonlocal host_id
            for _ in range(2):
                h = f"h{host_id}"
                host_id += 1
                subnet = next(host_pool)
                hosts = list(subnet.hosts())

                gw_ip = str(hosts[0])
                host_ip = str(hosts[1])
                sw_if = next_intf(intf_index, edge_sw)

                sw_state[edge_sw]["ifaces"].append((sw_if, f"{gw_ip}/{subnet.prefixlen}"))
                sw_state[edge_sw]["networks"].append(str(subnet))
                host_links.append(
                    (h, edge_sw, f"{host_ip}/{subnet.prefixlen}", f"via {gw_ip}", sw_if)
                )

        add_hosts_for_edge(e0)
        add_hosts_for_edge(e1)

    return all_switches, sw_links, host_links, sw_state


def render_main_py(
    all_switches: List[str],
    sw_links: List[Tuple[str, str, str, str]],
    host_links: List[Tuple[str, str, str, str, str]],
) -> str:
    lines: List[str] = []
    lines.append("from frrnet import frrnet_main")
    lines.append("from frrnet.topo import FrrTopo")
    lines.append("")
    lines.append("")
    lines.append("class FatTreeK4BgpTopo(FrrTopo):")
    lines.append("    def build(self):")
    lines.append("        # Add FRR switches (bgpd enabled).")
    lines.append("        switches = [")
    for sw in all_switches:
        lines.append(f"            \"{sw}\",")
    lines.append("        ]")
    lines.append("        for sw in switches:")
    lines.append("            self.addSwitch(sw, daemons=[\"bgpd\"])")
    lines.append("")
    lines.append("        # Add hosts and host-edge links (no bandwidth/delay constraints).")
    lines.append("        hosts = [")
    for h, edge, hip, default_route, sw_if in host_links:
        lines.append(
            "            "
            + f"(\"{h}\", \"{hip}\", \"{default_route}\", \"{edge}\", \"{sw_if}\"),"
        )
    lines.append("        ]")
    lines.append("        for h, hip, default_route, edge, edge_if in hosts:")
    lines.append("            self.addHost(h, ip=hip, defaultRoute=default_route)")
    lines.append("            self.addLink(h, edge, intf2=edge_if)")
    lines.append("")
    lines.append("        # Add switch-switch links with fixed 10Mbps bandwidth and 10ms delay.")
    lines.append("        sw_links = [")
    for s1, s2, i1, i2 in sw_links:
        lines.append(f"            (\"{s1}\", \"{s2}\", \"{i1}\", \"{i2}\"),")
    lines.append("        ]")
    lines.append("        for s1, s2, i1, i2 in sw_links:")
    lines.append("            self.addLink(s1, s2, intf1=i1, intf2=i2, bw=10, delay=\"10ms\")")
    lines.append("")
    lines.append("")
    lines.append("if __name__ == \"__main__\":")
    lines.append("    frrnet_main(FatTreeK4BgpTopo)")
    lines.append("")
    return "\n".join(lines)


def render_switch_conf(sw: str, state: SwitchState) -> str:
    asn = state["asn"]
    ifaces: List[Tuple[str, str]] = state["ifaces"]
    neighbors: List[Tuple[str, int]] = sorted(state["neighbors"], key=lambda x: x[0])
    networks: List[str] = sorted(set(state["networks"]))

    lines: List[str] = []
    lines.append("frr defaults datacenter")
    lines.append("!")
    lines.append("!")

    for intf, ip_cidr in ifaces:
        lines.append(f"interface {intf}")
        lines.append(f"  ip address {ip_cidr}")
        lines.append("!")

    lines.append("!")
    lines.append(f"router bgp {asn}")
    lines.append("  bgp bestpath as-path multipath-relax")
    lines.append("  maximum-paths 64")

    for peer_ip, peer_as in neighbors:
        lines.append(f"  neighbor {peer_ip} remote-as {peer_as}")

    for net in networks:
        lines.append(f"  network {net}")

    lines.append("")
    return "\n".join(lines)


def write_output(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    config_dir = output_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    all_switches, sw_links, host_links, sw_state = build_k4_model()

    (output_dir / "main.py").write_text(
        render_main_py(all_switches, sw_links, host_links), encoding="utf-8"
    )

    for sw in all_switches:
        (config_dir / f"{sw}.conf").write_text(
            render_switch_conf(sw, sw_state[sw]), encoding="utf-8"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate FRR Fat-tree(k=4) topology script and BGP configs"
    )
    parser.add_argument(
        "-o",
        "--output",
        default="fattree_k4_auto",
        help="Output directory (default: %(default)s)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output)
    write_output(output_dir)
    print(f"Generated files under: {output_dir}")


if __name__ == "__main__":
    main()
