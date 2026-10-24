"""Verify EdgeTunnel entrance and GO2SOCKS5 egress routing chain."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time

try:
    from .node_probe import (
        load_profile,
        make_config,
        prepare_runtime,
        proxy_request,
    )
except ImportError:
    from node_probe import (
        load_profile,
        make_config,
        prepare_runtime,
        proxy_request,
    )


def parse_trace(text):
    """Parse Cloudflare cdn-cgi/trace key=value format."""
    data = {}
    for line in text.splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            data[key.strip()] = value.strip()
    return data


def verify_general_egress(port, directory):
    """Check general egress through an external IP diagnosis endpoint."""
    result = proxy_request(port, 'https://api.ipify.org?format=json', directory, expected=200)
    body_file = directory / 'response.bin'
    payload = {}
    if body_file.exists():
        try:
            payload = json.loads(body_file.read_text(encoding='utf-8', errors='replace'))
        except Exception:
            pass
    ip = payload.get('ip')
    return {
        'status': 'passed' if not result['failure'] and ip else 'failed',
        'http_status': result.get('http_status'),
        'duration_ms': result.get('duration_ms'),
        'egress_ip': ip,
        'failure': result.get('failure'),
    }


def verify_gemini_egress(port, directory):
    """Check Gemini accessibility and detect regional or challenge blocks."""
    result = proxy_request(port, 'https://gemini.google.com/', directory, expected=(200, 301, 302))
    body_file = directory / 'response.bin'
    payload = body_file.read_bytes() if body_file.exists() else b''
    lower = payload.lower()

    if result['failure']:
        return {
            'status': 'failed',
            'reason': result['failure'],
            'http_status': result.get('http_status'),
            'duration_ms': result.get('duration_ms'),
        }

    # Explicit Google region rejections
    if any(marker in lower for marker in (
        b"gemini isn't currently supported in your country",
        b'gemini is not currently supported in your country',
        b'gemini isn\xe2\x80\x99t currently supported in your country',
        b'gemini is not available in your country',
        b'gemini isn\xe2\x80\x99t available in your country',
    )):
        return {
            'status': 'region_rejected',
            'reason': 'explicit_region_notice',
            'http_status': result.get('http_status'),
            'duration_ms': result.get('duration_ms'),
        }

    # Challenge or captcha pages
    if any(w in lower for w in (b'<title>sorry...', b'google.com/sorry', b'recaptcha', b'cf-chl-')):
        return {
            'status': 'blocked',
            'reason': 'bot_or_captcha_challenge',
            'http_status': result.get('http_status'),
            'duration_ms': result.get('duration_ms'),
        }

    return {
        'status': 'passed',
        'reason': 'accessible',
        'http_status': result.get('http_status'),
        'duration_ms': result.get('duration_ms'),
    }


def verify_node_chain(ip, profile, binary, work):
    """Execute dual-track verification on a candidate entrance IP."""
    report = {
        'entrance_ip': ip,
        'chain_healthy': False,
        'general_egress': None,
        'gemini_check': None,
        'failure': None,
    }
    process = None
    with tempfile.TemporaryDirectory(prefix='verify-', dir=work) as folder:
        directory = Path(folder)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]

        config_path = directory / 'config.json'
        fd = os.open(config_path, os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(make_config(profile, ip, port), handle)

        try:
            child_env = {k: v for k, v in os.environ.items() if k != 'NODE_PROFILE_JSON'}
            process = subprocess.Popen(
                [str(binary), 'run', '-c', str(config_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=child_env,
            )
            deadline = time.monotonic() + 5
            ready = False
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                        ready = True
                    break
                except OSError:
                    time.sleep(0.05)

            if not ready:
                report['failure'] = 'runtime_start_failed'
                return report

            general = verify_general_egress(port, directory)
            report['general_egress'] = general

            gemini = verify_gemini_egress(port, directory)
            report['gemini_check'] = gemini

            if general['status'] == 'passed' and gemini['status'] == 'passed':
                report['chain_healthy'] = True
            else:
                report['failure'] = general.get('failure') or gemini.get('reason')

            return report
        finally:
            if process:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    parser = argparse.ArgumentParser(description='Verify EdgeTunnel entrance and GO2SOCKS5 egress routing chain')
    parser.add_argument('--ip', required=True, help='Candidate entrance IP address')
    parser.add_argument('--workdir', default='.work', help='Working directory for runtime artifacts')
    args = parser.parse_args()

    work = Path(args.workdir).resolve()
    work.mkdir(exist_ok=True)

    profile = load_profile(work)
    binary = prepare_runtime(work)

    print(f'Starting verification for entrance: {args.ip}')
    report = verify_node_chain(args.ip, profile, binary, work)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not report['chain_healthy']:
        sys.exit(1)


if __name__ == '__main__':
    main()
