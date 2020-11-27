#!/usr/bin/python
"CS244 Spring 2015 Assignment 1: Bufferbloat"

from mininet.topo import Topo
from mininet.node import CPULimitedHost
from mininet.link import TCLink
from mininet.net import Mininet
from mininet.log import lg, info
from mininet.util import dumpNodeConnections
from mininet.cli import CLI

from subprocess import Popen, PIPE
from time import sleep, time
from multiprocessing import Process
from argparse import ArgumentParser

from monitor import monitor_qlen
import termcolor as T

import sys
import os
import math
import numpy as np

# TODO: Don't just read the TODO sections in this code.  Remember that
# one of the goals of this assignment is for you to learn how to use
# Mininet. :-)

parser = ArgumentParser(description="Bufferbloat tests")
parser.add_argument('--bw-host', '-B',
                    type=float,
                    help="Bandwidth of host links (Mb/s)",
                    default=1000)

parser.add_argument('--bw-net', '-b',
                    type=float,
                    help="Bandwidth of bottleneck (network) link (Mb/s)",
                    required=True)

parser.add_argument('--delay',
                    type=float,
                    help="Link propagation delay (ms)",
                    required=True)

parser.add_argument('--dir', '-d',
                    help="Directory to store outputs",
                    required=True)

parser.add_argument('--time', '-t',
                    help="Duration (sec) to run the experiment",
                    type=int,
                    default=10)

parser.add_argument('--maxq',
                    type=int,
                    help="Max buffer size of network interface in packets",
                    default=100)

# Linux uses CUBIC-TCP by default that doesn't have the usual sawtooth
# behaviour.  For those who are curious, invoke this script with
# --cong cubic and see what happens...
# sysctl -a | grep cong should list some interesting parameters.
parser.add_argument('--cong',
                    help="Congestion control algorithm to use",
                    default="reno")

# Expt parameters
args = parser.parse_args()


class BBTopo(Topo):
    "Simple topology for bufferbloat experiment."

    def build(self, n=2):
        # Here I have created a switch.  If you change its name, its
        # interface names will change from s0-eth1 to newname-eth1.
        switch = self.addSwitch('s0')
        print "Setting %s hosts" % n
        for i in range(n):
            host = self.addHost('h%s' % (i + 1))

        print "Setting up the link from h1 to switch"
        # Link from h1 to router. 10Gbs with 5ms delay.
        delay = args.delay
        bw_host = args.bw_host
        bw_net = args.bw_net
        maxq = args.maxq
        time = args.time
        print "Parameters: delay %s, host bw %s, bottleneck bw %s, time %s" % \
            (delay, bw_host, bw_net, time)
        self.addLink('h1', switch,
                     bw=bw_host, delay='%sms' % delay, max_queue_size=maxq)

        print "Setting up the link from switch to h2"
        # Link from Router to h2. 1.5Mbs, 5ms delay.
        self.addLink(switch, 'h2',
                     bw=bw_net, delay='%sms' % delay, max_queue_size=maxq)
        return

# Simple wrappers around monitoring utilities.  You are welcome to
# contribute neatly written (using classes) monitoring scripts for
# Mininet!


def start_tcpprobe(outfile="cwnd.txt"):
    os.system("rmmod tcp_probe; modprobe tcp_probe full=1;")
    return

# Simple wrappers around monitoring utilities.  You are welcome to
# contribute neatly written (using classes) monitoring scripts for
# Mininet!


def start_tcpprobe(outfile="cwnd.txt"):
    os.system("rmmod tcp_probe; modprobe tcp_probe full=1;")
    Popen("cat /proc/net/tcpprobe > %s/%s" % (args.dir, outfile),
          shell=True)


def stop_tcpprobe():
    Popen("killall -9 cat", shell=True).wait()


def start_qmon(iface, interval_sec=0.1, outfile="q.txt"):
    monitor = Process(target=monitor_qlen,
                      args=(iface, interval_sec, outfile))
    monitor.start()
    return monitor


def start_iperf(net):
    h2 = net.get('h2')
    print "Starting iperf server..."
    # For those who are curious about the -w 16m parameter, it ensures
    # that the TCP flow is not receiver window limited.  If it is,
    # there is a chance that the router buffer may not get filled up.
    server = h2.popen("iperf -s -w 16m")

    # Sending the iperf flow from h1 to h2 with the given duration
    h1 = net.get('h1')
    time = args.time
    print "Starting iperf client and tcp flow for %ss" % time
    h1.cmd("iperf -t %s -c %s" % (time, h2.IP()))


def start_webserver(net):
    h1 = net.get('h1')
    proc = h1.popen("python http/webserver.py", shell=True)
    sleep(1)
    return [proc]


def start_ping(net):
    print "Starting ping from h1 to h2, 10 times a sec"
    h1 = net.get("h1")
    h2 = net.get("h2")
    # Sending ping for 10 * time packets
    time = args.time
    h1.popen("ping -c %s -i 0.1 %s > %s/ping.txt" %
             (time * 10, h2.IP(), args.dir), shell=True)
    return


def get_web_measurement(net):
    h1 = net.get('h1')
    h2 = net.get('h2')
    results = []
    for i in range(3):
        t = h2.popen(
            'curl -o /dev/null -s -w %%{time_total} %s/http/index.html' % h1.IP()).communicate()[0]
    results.append(t)
    return results


def bufferbloat():
    if not os.path.exists(args.dir):
        os.makedirs(args.dir)
    os.system("sysctl -w net.ipv4.tcp_congestion_control=%s" % args.cong)
    topo = BBTopo()
    net = Mininet(topo=topo, host=CPULimitedHost, link=TCLink)
    net.start()
    # This dumps the topology and how nodes are interconnected through
    # links.
    dumpNodeConnections(net.hosts)
    # This performs a basic all pairs ping test.
    net.pingAll()
    # Start all the monitoring processes
    start_tcpprobe("cwnd.txt")

    # TODO: Start monitoring the queue sizes.  Since the switch I
    # created is "s0", I monitor one of the interfaces.  Which
    # interface?  The interface numbering starts with 1 and increases.
    # Depending on the order you add links to your network, this
    # number may be 1 or 2.  Ensure you use the correct number.
    qmon = start_qmon(iface='s0-eth2',
                      outfile='%s/q.txt' % (args.dir))

    # TODO: Start iperf, webservers, etc.
    iperf_proc = Process(target=start_iperf, args=(net, ))
    ping_proc = Process(target=start_ping, args=(net, ))
    iperf_proc.start()
    ping_proc.start()

    # TODO: Close the procs...
    webservers = start_webserver(net)

    # TODO: measure the time it takes to complete webpage transfer
    # from h1 to h2 (say) 3 times.  Hint: check what the following
    # command does: curl -o /dev/null -s -w %{time_total} google.com
    # Now use the curl command to fetch webpage from the webserver you
    # spawned on host h1 (not from google!)

    # Hint: have a separate function to do this and you may find the
    # loop below useful.
    # I think it's done -- Eyal
    web_download_time = []
    start_time = time()
    while True:
        # do the measurement (say) 3 times.
        web_download_time.extend(get_web_measurement(net))
        sleep(5)
        now = time()
        delta = now - start_time
        if delta > args.time:
            break
        print "%.1fs left..." % (args.time - delta)
    # print web_download_time

    wdt = np.array(web_download_time).astype(np.float)
    # TODO: Move to readme
    f = open('./web_result.txt', 'w+')
    f.write("Mean of web download: %lf \n" % np.mean(wdt))
    f.write("Standard deviation: %lf \n" % np.std(wdt))
    f.close()
    # TODO: compute average (and standard deviation) of the fetch
    # times.  You don't need to plot them.  Just note it in your
    # README and explain.
    # I think it's done, need to add results to readme in a meaningfull way

    # Hint: The command below invokes a CLI which you can use to
    # debug.  It allows you to run arbitrary commands inside your
    # emulated hosts h1 and h2.
    # CLI(net)

    stop_tcpprobe()
    qmon.terminate()
    net.stop()
    # Ensure that all processes you create within Mininet are killed.
    # Sometimes they require manual killing.
    Popen("pgrep -f webserver.py | xargs kill -9", shell=True).wait()


if __name__ == "__main__":
    bufferbloat()
