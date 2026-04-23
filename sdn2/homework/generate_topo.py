from __future__ import annotations

import ipaddress

from frrnet import frrnet_main
from frrnet.topo import FrrTopo


class FatTreeK4Topo(FrrTopo):
    def build(self):
        core_switches = ["c0_0", "c0_1", "c1_0", "c1_1"]
        agg_switches = [f"a{pod}_{i}" for pod in range(4) for i in range(2)]
        edge_switches = [f"e{pod}_{i}" for pod in range(4) for i in range(2)]
        all_switches = core_switches + agg_switches + edge_switches

        for sw in all_switches:
            self.addSwitch(sw, daemons=["bgpd"])

        intf_index = {sw: 0 for sw in all_switches}
        host_pool = ipaddress.ip_network("172.16.0.0/16").subnets(new_prefix=30)
        host_id = 0

        def next_intf(sw: str) -> str:
            intf_index[sw] += 1
            return f"Ethernet1-{intf_index[sw]}"

        def add_sw_link(sw1: str, sw2: str) -> None:
            self.addLink(
                sw1,
                sw2,
                intf1=next_intf(sw1),
                intf2=next_intf(sw2),
                bw=10,
                delay="10ms",
            )

        for pod in range(4):
            a0 = f"a{pod}_0"
            a1 = f"a{pod}_1"
            e0 = f"e{pod}_0"
            e1 = f"e{pod}_1"

            # Aggregation <-> core.
            add_sw_link(a0, "c0_0")
            add_sw_link(a0, "c1_0")
            add_sw_link(a1, "c0_1")
            add_sw_link(a1, "c1_1")

            # Edge <-> aggregation.
            add_sw_link(e0, a0)
            add_sw_link(e0, a1)
            add_sw_link(e1, a0)
            add_sw_link(e1, a1)

            for edge_sw in (e0, e1):
                for _ in range(2):
                    subnet = next(host_pool)
                    hosts = list(subnet.hosts())
                    gw_ip = str(hosts[0])
                    host_ip = str(hosts[1])

                    host = self.addHost(
                        f"h{host_id}",
                        ip=f"{host_ip}/{subnet.prefixlen}",
                        defaultRoute=f"via {gw_ip}",
                    )
                    host_id += 1

                    # Host-edge links are left without bw/delay constraints.
                    self.addLink(host, edge_sw, intf2=next_intf(edge_sw))


def start_fattree_k4() -> None:
    frrnet_main(FatTreeK4Topo)


if __name__ == "__main__":
    start_fattree_k4()