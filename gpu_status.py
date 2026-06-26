#!/usr/bin/env python3
# [Flow: Step 1 (parse hosts) -> Step 2 (SSH query each host) -> Step 3 (parse JSON) -> Step 4 (print combined table)]
import argparse
import json
import subprocess
import sys

DEFAULT_HOSTS = ["b1", "b2"]
ROCM_SMI_CMD = "/opt/rocm/bin/rocm-smi --showuse --showtemp --showmemuse --showmaxpower --showpower --json"


def parse_args():
    parser = argparse.ArgumentParser(description="Query GPU status from remote hosts")
    parser.add_argument(
        "--hosts",
        default=",".join(DEFAULT_HOSTS),
        help="comma-separated host names (default: b1,b2)",
    )
    return parser.parse_args()


def run_remote(host, command):
    return subprocess.run(
        ["ssh", host, command],
        capture_output=True,
        text=True,
        check=False,
    )


def query_host(host):
    result = run_remote(host, ROCM_SMI_CMD)
    if result.returncode != 0:
        return None, result.stderr.strip()
    try:
        return json.loads(result.stdout), None
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"


def extract_info(gpu_data):
    return {
        "use": gpu_data.get("GPU use (%)", "N/A"),
        "vram": gpu_data.get("GPU Memory Allocated (VRAM%)", "N/A"),
        "edge": gpu_data.get("Temperature (Sensor edge) (C)", "N/A"),
        "junction": gpu_data.get("Temperature (Sensor junction) (C)", "N/A"),
        "memory": gpu_data.get("Temperature (Sensor memory) (C)", "N/A"),
        "power": gpu_data.get("Max Graphics Package Power (W)", "N/A"),
        "current_power": gpu_data.get("Current Socket Graphics Package Power (W)", "N/A"),
    }


def print_table(host, data):
    print(f"\n=== {host} ===")
    print(f"| {'GPU':<6} | {'Use':<5} | {'VRAM%':<6} | {'Edge':<5} | {'Junction':<8} | {'Mem':<5} | {'Power':<6} | {'CurPwr':<7} |")
    print(f"| {'-'*6} | {'-'*5} | {'-'*6} | {'-'*5} | {'-'*8} | {'-'*5} | {'-'*6} | {'-'*7} |")
    for card in sorted(data.keys()):
        info = extract_info(data[card])
        print(f"| {card:<6} | {info['use']:<5} | {info['vram']:<6} | {info['edge']:<5} | {info['junction']:<8} | {info['memory']:<5} | {info['power']:<6} | {info['current_power']:<7} |")


def main():
    args = parse_args()
    hosts = [h.strip() for h in args.hosts.split(",") if h.strip()]
    if not hosts:
        print("no hosts specified", file=sys.stderr)
        return
    for host in hosts:
        data, err = query_host(host)
        if err:
            print(f"[ERR] {host}: {err}", file=sys.stderr)
            continue
        print_table(host, data)


if __name__ == "__main__":
    main()
