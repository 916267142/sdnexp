from os_ken import cfg
from os_ken import log
from os_ken.base import app_manager
from os_ken.base.app_manager import lookup_service_brick
from os_ken.controller import ofp_event
from os_ken.controller.handler import MAIN_DISPATCHER
from os_ken.controller.handler import set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib.packet import packet
from os_ken.lib.packet import ethernet, arp, ipv4
from os_ken.lib.packet import ether_types
from os_ken.topology.switches import LLDPPacket
from os_ken.lib import hub

import time
import networkx as nx

from controllers.network_awareness import NetworkAwareness


ETHERNET = ethernet.ethernet.__name__
ETHERNET_MULTICAST = "ff:ff:ff:ff:ff:ff"
ARP = arp.arp.__name__

GET_DELAY_INTERVAL = 2
SEND_ECHO_REQUEST_INTERVAL = 2


class ShortestForward(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'network_awareness': NetworkAwareness}

    def __init__(self, *args, **kwargs):
        super(ShortestForward, self).__init__(*args, **kwargs)
        self.network_awareness = kwargs['network_awareness']
        self.weight = 'delay'
        self.mac_to_port = {}
        self.sw = {}
        self.path = None
        self.switches = None
        self.lldp_delay = {}
        self.echo_delay = {}
        self.monitor_thread = hub.spawn(self._monitor_delay)

    def add_flow(self, datapath, priority, match, actions, idle_timeout=0, hard_timeout=0):
        dp = datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=dp, priority=priority,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
            match=match, instructions=inst)
        dp.send_msg(mod)

    def delete_flow(self, datapath, match):
        ofp = datapath.ofproto
        parser = datapath.ofproto_parser
        mod = parser.OFPFlowMod(
            datapath=datapath,
            command=ofp.OFPFC_DELETE,
            out_port=ofp.OFPP_ANY,
            out_group=ofp.OFPG_ANY,
            match=match,
        )
        datapath.send_msg(mod)

    def _monitor_delay(self):
        while True:
            self._sync_graph_delay()
            self._send_echo_requests()
            hub.sleep(GET_DELAY_INTERVAL)

    def _send_echo_requests(self):
        for dp in list(self.network_awareness.switch_info.values()):
            try:
                payload = str(time.time()).encode('ascii')
                req = dp.ofproto_parser.OFPEchoRequest(dp, payload)
                dp.send_msg(req)
            except Exception:
                continue
            hub.sleep(SEND_ECHO_REQUEST_INTERVAL / 10)

    def _ensure_switches(self):
        if self.switches is None:
            self.switches = lookup_service_brick('switches')
        return self.switches

    def _sync_graph_delay(self):
        topo_map = self.network_awareness.topo_map
        if topo_map is None:
            return

        for src, dst in topo_map.edges:
            if isinstance(src, int) and isinstance(dst, int):
                topo_map[src][dst].setdefault('delay', float('inf'))
                lldp_s12 = self.lldp_delay.get((src, dst))
                lldp_s21 = self.lldp_delay.get((dst, src))
                echo_s1 = self.echo_delay.get(src)
                echo_s2 = self.echo_delay.get(dst)
                if None not in (lldp_s12, lldp_s21, echo_s1, echo_s2):
                    delay = (lldp_s12 + lldp_s21 - echo_s1 - echo_s2) / 2.0
                    topo_map[src][dst]['delay'] = max(delay, 0.0)
            else:
                topo_map[src][dst]['delay'] = 0.0

    def _build_delay_graph(self):
        topo_map = self.network_awareness.topo_map
        delay_graph = nx.Graph()
        if topo_map is None:
            return delay_graph

        delay_graph.add_nodes_from(topo_map.nodes)
        for src, dst in topo_map.edges:
            if (src, dst) in self.blocked_links or (dst, src) in self.blocked_links:
                continue
            delay = topo_map[src][dst].get('delay', float('inf'))
            if delay is None:
                delay = float('inf')
            delay_graph.add_edge(src, dst, delay=delay)
        return delay_graph

    def _handle_lldp_delay(self, msg, src_dpid, src_port_no):
        switches = self._ensure_switches()
        if switches is None:
            return

        dst_dpid = msg.datapath.id
        for port in switches.ports.keys():
            if src_dpid == port.dpid and src_port_no == port.port_no:
                self.lldp_delay[(src_dpid, dst_dpid)] = switches.ports[port].delay
                break
        self._sync_graph_delay()

    def _link_peer(self, dpid, port_no):
        peer = self.network_awareness.port_link.get((dpid, port_no))
        if peer is None:
            return None
        return peer[1]

    def _block_link(self, dpid, port_no):
        peer_dpid = self._link_peer(dpid, port_no)
        if peer_dpid is None:
            return
        self.blocked_links.add((dpid, peer_dpid))
        self.blocked_links.add((peer_dpid, dpid))

    def _unblock_link(self, dpid, port_no):
        peer_dpid = self._link_peer(dpid, port_no)
        if peer_dpid is None:
            return
        self.blocked_links.discard((dpid, peer_dpid))
        self.blocked_links.discard((peer_dpid, dpid))

    def _remove_ipv4_flows(self, dpid=None):
        if dpid is not None and dpid in self.network_awareness.switch_info:
            dp = self.network_awareness.switch_info[dpid]
            match = dp.ofproto_parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP)
            self.delete_flow(dp, match)
            return

        for dp in list(self.network_awareness.switch_info.values()):
            match = dp.ofproto_parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP)
            self.delete_flow(dp, match)

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def port_status_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        dpid = dp.id
        port_no = msg.desc.port_no

        if msg.reason == ofp.OFPPR_DELETE:
            self._block_link(dpid, port_no)
            self._remove_ipv4_flows()
        elif msg.reason == ofp.OFPPR_ADD:
            self._unblock_link(dpid, port_no)
            self._remove_ipv4_flows()

        self._sync_graph_delay()

    @set_ev_cls(ofp_event.EventOFPEchoReply, MAIN_DISPATCHER)
    def echo_reply_handler(self, ev):
        msg = ev.msg
        try:
            send_timestamp = float(msg.data.decode('ascii'))
        except Exception:
            return

        self.echo_delay[msg.datapath.id] = max(time.time() - send_timestamp, 0.0)
        self._sync_graph_delay()

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        try:
            src_dpid, src_port_no = LLDPPacket.lldp_parse(msg.data)
            self._handle_lldp_delay(msg, src_dpid, src_port_no)
            return
        except Exception:
            pass

        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth_pkt = pkt.get_protocol(ethernet.ethernet)
        arp_pkt = pkt.get_protocol(arp.arp)
        ipv4_pkt = pkt.get_protocol(ipv4.ipv4)

        if eth_pkt is None:
            return

        pkt_type = eth_pkt.ethertype
        dst_mac = eth_pkt.dst
        src_mac = eth_pkt.src

        if isinstance(arp_pkt, arp.arp):
            self.handle_arp(msg, in_port, dst_mac, src_mac, pkt, pkt_type)

        if isinstance(ipv4_pkt, ipv4.ipv4):
            self.handle_ipv4(msg, ipv4_pkt.src, ipv4_pkt.dst, pkt_type)

    def handle_arp(self, msg, in_port, dst, src, pkt, pkt_type):
        dp = msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        arp_pkt = pkt.get_protocol(arp.arp)
        if dst == ETHERNET_MULTICAST and isinstance(arp_pkt, arp.arp):
            if arp_pkt.opcode == arp.ARP_REQUEST:
                key = (dp.id, src, arp_pkt.dst_ip)
                if key in self.sw and self.sw[key] != in_port:
                    match = parser.OFPMatch(
                        in_port=in_port,
                        eth_type=ether_types.ETH_TYPE_ARP,
                        arp_op=arp.ARP_REQUEST,
                        eth_src=src,
                        arp_tpa=arp_pkt.dst_ip,
                    )
                    self.add_flow(dp, 20, match, [], idle_timeout=10)
                    return
                self.sw[key] = in_port

        actions = [parser.OFPActionOutput(ofp.OFPP_FLOOD)]
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=msg.data)
        dp.send_msg(out)

    def handle_ipv4(self, msg, src_ip, dst_ip, pkt_type):
        parser = msg.datapath.ofproto_parser

        self._sync_graph_delay()
        delay_graph = self._build_delay_graph()
        try:
            dpid_path = nx.shortest_path(delay_graph, src_ip, dst_ip, weight='delay')
        except Exception:
            dpid_path = None
        if not dpid_path:
            return

        self.path = dpid_path
        port_path = []
        for i in range(1, len(dpid_path) - 1):
            in_port = self.network_awareness.link_info[(dpid_path[i], dpid_path[i - 1])]
            out_port = self.network_awareness.link_info[(dpid_path[i], dpid_path[i + 1])]
            port_path.append((in_port, dpid_path[i], out_port))

        total_delay = nx.path_weight(delay_graph, dpid_path, weight='delay')
        self.show_path(src_ip, dst_ip, port_path, total_delay)

        for node in port_path:
            in_port, dpid, out_port = node
            self.send_flow_mod(parser, dpid, pkt_type, src_ip, dst_ip, in_port, out_port)
            self.send_flow_mod(parser, dpid, pkt_type, dst_ip, src_ip, out_port, in_port)

        _, dpid, out_port = port_path[-1]
        dp = self.network_awareness.switch_info[dpid]
        actions = [parser.OFPActionOutput(out_port)]
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=msg.data)
        dp.send_msg(out)

    def send_flow_mod(self, parser, dpid, pkt_type, src_ip, dst_ip, in_port, out_port):
        dp = self.network_awareness.switch_info[dpid]
        match = parser.OFPMatch(
            in_port=in_port, eth_type=pkt_type, ipv4_src=src_ip, ipv4_dst=dst_ip)
        actions = [parser.OFPActionOutput(out_port)]
        self.add_flow(dp, 1, match, actions, 10, 30)

    def show_path(self, src, dst, port_path, total_delay):
        self.logger.info('delay path: {} -> {}'.format(src, dst))
        path = src + ' -> '
        for node in port_path:
            path += '{}:s{}:{}'.format(*node) + ' -> '
        path += dst
        self.logger.info(path)
        self.logger.info('total delay: {:.6f}s ({:.3f} ms)'.format(total_delay, total_delay * 1000.0))


if __name__ == '__main__':
    cfg.CONF()
    cfg.CONF.set_override('observe_links', True)
    log.init_log()
    app_manager.AppManager.run_apps(["controllers.task3.shortest_forward"])