"""Exercise the real proxy; never allow a direct outbound fallback."""
import copy
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import socket
import statistics
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.request

RUNTIME_VERSION = '1.14.2'
ARCHIVE_HASHES = {
    'linux-amd64': 'a684484d7477d1437282ee411f4d131d0340aaad60a7868841ebd5d87dd8a0c6',
    'darwin-arm64': '925c5382eca8492b0150f868a6db20b18290a38700e621724b3703fd453e032d',
}
TARGETS = (
    ('baseline', 'https://www.gstatic.com/generate_204', 204, None),
    ('youtube', 'https://www.youtube.com/', 200, b'youtube'),
    ('x', 'https://x.com/', 200, b'x.com'),
)
TRANSFER_BYTES = 1024 * 1024
QUALITY_LOCK = threading.Lock()
QUALITY_LAST_REQUEST = 0.0


def parse_quality(payload):
    """Only publish documented, validated fields; never retain arbitrary API output."""
    if not isinstance(payload, dict):
        raise ValueError('Invalid quality response')
    address = ipaddress.ip_address(payload['ip'])
    if not address.is_global:
        raise ValueError('Invalid exit address')
    risk = payload.get('fraudScore')
    if isinstance(risk, bool) or not isinstance(risk, (int, float)) or not 0 <= risk <= 100:
        raise ValueError('Missing or invalid risk score')
    country = payload.get('countryCode')
    asn = payload.get('asn')
    return {'state': 'scored', 'provider': 'IPPure', 'exit_ip': str(address),
            'exit_country': country if isinstance(country, str) and re.fullmatch('[A-Z]{2}', country) else None,
            'asn': asn if type(asn) is int and 0 < asn <= 4294967295 else None,
            'fraud_score': risk, 'quality_score': round(100-risk, 1),
            'is_residential': payload.get('isResidential') if type(payload.get('isResidential')) is bool else None}


def query_quality(port, directory):
    global QUALITY_LAST_REQUEST
    unknown = {'state': 'unknown', 'provider': 'IPPure', 'quality_score': None}
    try:
        # Space requests across concurrent nodes; never query using a direct fallback.
        with QUALITY_LOCK:
            delay = 1-(time.monotonic()-QUALITY_LAST_REQUEST)
            if delay > 0:
                time.sleep(delay)
            QUALITY_LAST_REQUEST = time.monotonic()
        result = proxy_request(port, 'https://my.ippure.com/v1/info', directory)
        if result['failure']:
            return {**unknown, 'failure': result['failure']}
        return parse_quality(json.loads((directory / 'response.bin').read_text()))
    except Exception:
        return {**unknown, 'failure': 'invalid_or_unavailable_response'}


def load_profile(work):
    raw = os.getenv('NODE_PROFILE_JSON')
    if not raw and not os.getenv('GITHUB_ACTIONS'):
        path = work / 'node-profile.json'
        raw = path.read_text() if path.exists() else None
    if not raw:
        raise RuntimeError('Missing private node test profile; existing lists preserved')
    try:
        source = json.loads(raw)
        profile = {k: copy.deepcopy(source[k]) for k in ('type', 'uuid', 'password', 'server_port', 'tls', 'transport', 'flow') if k in source}
        if profile['type'] not in ('vless', 'trojan'):
            raise ValueError()
        if not profile['tls']['enabled'] or profile['tls'].get('insecure'):
            raise ValueError()
        if profile['transport']['type'] != 'ws':
            raise ValueError()
        if not profile['tls']['server_name'] or not profile['transport']['headers']['Host']:
            raise ValueError()
        if not profile.get('uuid' if profile['type'] == 'vless' else 'password'):
            raise ValueError()
        profile['server_port'] = int(profile.get('server_port', 443))
    except Exception:
        raise RuntimeError('Invalid private node profile; expected authenticated WS TLS') from None
    return profile


def prepare_runtime(work):
    target = {'Linux': 'linux', 'Darwin': 'darwin'}[platform.system()] + '-' + {'x86_64': 'amd64', 'arm64': 'arm64'}[platform.machine()]
    if target not in ARCHIVE_HASHES:
        raise RuntimeError('Unsupported node-check runtime architecture')
    archive = work / f'sing-box-{RUNTIME_VERSION}-{target}.tar.gz'
    if not archive.exists():
        url = f'https://github.com/SagerNet/sing-box/releases/download/v{RUNTIME_VERSION}/{archive.name}'
        with urllib.request.urlopen(url, timeout=45) as response:
            archive.write_bytes(response.read())
    payload = archive.read_bytes()
    if hashlib.sha256(payload).hexdigest() != ARCHIVE_HASHES[target]:
        raise RuntimeError('Node-check runtime checksum mismatch')
    binary = work / 'sing-box'
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as bundle:
        member = next(m for m in bundle.getmembers() if m.isfile() and m.name.endswith('/sing-box'))
        binary.write_bytes(bundle.extractfile(member).read())
    binary.chmod(0o755)
    return binary


def make_config(profile, ip, port):
    outbound = copy.deepcopy(profile)
    outbound.update({'tag': 'tested-node', 'server': ip, 'network': 'tcp'})
    return {'log': {'disabled': True},
            'inbounds': [{'type': 'mixed', 'tag': 'test-in', 'listen': '127.0.0.1', 'listen_port': port}],
            'outbounds': [outbound], 'route': {'final': 'tested-node'}}


def classify_request(exit_code, code, size, expected, marker, body):
    if exit_code:
        return {28: 'timeout', 60: 'tls_error', 7: 'connection_error', 35: 'tls_error',
                56: 'receive_error', 52: 'empty_response'}.get(exit_code, 'transport_error')
    accepted = expected if isinstance(expected, tuple) else (expected,)
    if code not in accepted:
        return 'unexpected_http_status'
    lower = body.lower()
    if any(word in lower for word in (b'<title>just a moment', b'attention required!', b'cf-chl-')):
        return 'challenge_page'
    if marker and (size < 100 or marker not in lower):
        return 'unexpected_page'
    return None


def extract_transfer_source(body):
    text = body.decode('utf-8', errors='replace').replace('\\/', '/')
    match = re.search(r'(/s/player/[A-Za-z0-9_./-]+/base\.js)', text)
    return 'https://www.youtube.com'+match.group(1) if match else None


def proxy_request(port, url, directory, expected=200, marker=None, rate=None, ranged=False):
    body_file = directory / 'response.bin'
    args = ['curl', '--silent', '--show-error', '--http1.1', '--proxy', f'http://127.0.0.1:{port}',
            '--noproxy', '', '--connect-timeout', '5', '--max-time', '20', '--location',
            '--max-redirs', '3', '--proto', '=https', '--proto-redir', '=https',
            '--user-agent', 'Mozilla/5.0', '--max-filesize', '4194304',
            '--output', str(body_file), '--write-out', '%{http_code} %{time_total} %{size_download} %{speed_download}', url]
    if rate:
        args.extend(['--limit-rate', rate])
    if ranged:
        args.extend(['--range', f'0-{TRANSFER_BYTES-1}'])
    result = subprocess.run(args, capture_output=True, text=True, timeout=25)
    try:
        code, duration, size, speed = result.stdout.strip().split()
        code, duration, size, speed = int(code), float(duration), int(float(size)), float(speed)
    except ValueError:
        code, duration, size, speed = 0, 0, 0, 0
    payload = body_file.read_bytes() if body_file.exists() else b''
    body = payload[:1024*1024]
    failure = classify_request(result.returncode, code, size, expected, marker, body)
    return {'http_status': code, 'duration_ms': round(duration*1000, 1),
            'bytes': size, 'speed_kib_s': round(speed/1024, 1), 'failure': failure,
            'sha256': hashlib.sha256(payload).hexdigest(),
            'transfer_url': extract_transfer_source(body) if marker == b'youtube' else None}


def check_node(ip, profile, binary, work):
    report = {'ip': ip, 'passed': False, 'phase': 'runtime', 'checks': []}
    process = None
    with tempfile.TemporaryDirectory(prefix='node-', dir=work) as folder:
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
            process = subprocess.Popen([str(binary), 'run', '-c', str(config_path)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=child_env)
            deadline = time.monotonic()+5
            ready = False
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.1):
                        ready = True
                    break
                except OSError:
                    time.sleep(.05)
            if not ready:
                report['failure'] = 'runtime_start_failed'
                return report
            timings = []
            transfer_url = None
            for round_number in range(1, 4):
                for target, url, expected, marker in TARGETS:
                    report['phase'] = target
                    result = proxy_request(port, url, directory, expected, marker)
                    transfer_url = result.pop('transfer_url', None) or transfer_url
                    report['checks'].append({'target': target, 'round': round_number, **result})
                    if result['failure']:
                        report['failure'] = result['failure']
                        return report
                    timings.append(result['duration_ms'])
                if round_number == 2:
                    # An uncapped transfer measures speed; a separate paced transfer
                    # keeps a real proxy connection active for several seconds.
                    if not transfer_url:
                        report.update({'phase': 'download', 'failure': 'missing_transfer_resource'})
                        return report
                    reference = None
                    for phase, rate in (('download', None), ('sustained_transfer', '128K')):
                        report['phase'] = phase
                        result = proxy_request(port, transfer_url, directory, expected=(200, 206), rate=rate, ranged=True)
                        result.pop('transfer_url', None)
                        report['checks'].append({'target': phase, **result})
                        if result['failure'] or result['bytes'] < TRANSFER_BYTES:
                            report['failure'] = result['failure'] or 'incomplete_transfer'
                            return report
                        if phase == 'download':
                            reference = (result['bytes'], result['sha256'])
                            report['download_kib_s'] = result['speed_kib_s']
                            if result['speed_kib_s'] < 64:
                                report['failure'] = 'slow_transfer'
                                return report
                        else:
                            if reference != (result['bytes'], result['sha256']):
                                report['failure'] = 'transfer_content_mismatch'
                                return report
                            report['sustained_seconds'] = round(result['duration_ms']/1000, 1)
                elif round_number == 1:
                    time.sleep(1)
            report.update({'passed': True, 'phase': 'complete', 'success_rate': 1.0,
                           'proxy_max_ms': max(timings), 'proxy_median_ms': round(statistics.median(timings), 1)})
            report['quality'] = query_quality(port, directory)
            return report
        except Exception:
            # Keep runtime logs, URLs and auth-bearing configuration out of public diagnostics.
            report['failure'] = 'probe_internal_error'
            return report
        finally:
            if process:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def ranking_key(row):
    quality = row.get('quality', {})
    scored = quality.get('state') == 'scored' and isinstance(quality.get('quality_score'), (int, float))
    return (-row.get('success_rate', 0), 0 if scored else 1,
            -quality['quality_score'] if scored else 0, row.get('proxy_max_ms', float('inf')),
            row.get('proxy_median_ms', float('inf')), -row.get('download_kib_s', 0), row['max_ms'])
