#!/usr/bin/env python3
"""Bounded CFData scan; country comes from colo, never source loc/GeoIP."""
import concurrent.futures
import csv
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import random
import re
import statistics
import subprocess
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
try:
    from .node_probe import check_node, load_profile, prepare_runtime, ranking_key
    from .exit_lookup import cross_check_exits
except ImportError:
    from node_probe import check_node, load_profile, prepare_runtime, ranking_key
    from exit_lookup import cross_check_exits

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.work'
LIST_SIZE = 9
PROBE_LIMIT = 60
VERSION = 'v1.8.3'


def fetch(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def prepare():
    WORK.mkdir(exist_ok=True)
    platform = 'darwin-arm64' if os.uname().sysname == 'Darwin' else 'linux-amd64'
    name = 'cfdata-' + platform
    base = f'https://github.com/PoemMisty/CFData-WEB/releases/download/{VERSION}/{name}'
    payload = fetch(base)
    expected = fetch(base + '.sha256').decode().split()[0]
    if hashlib.sha256(payload).hexdigest() != expected:
        raise RuntimeError('CFData checksum mismatch')
    binary = WORK / 'cfdata'
    binary.write_bytes(payload)
    binary.chmod(0o755)
    # The speed-test locations endpoint currently rejects unattended requests.
    # Official status names include city, country and IATA colo, without auth.
    components = json.loads(fetch('https://www.cloudflarestatus.com/api/v2/components.json'))['components']
    codes = {'Japan': 'JP', 'South Korea': 'KR', 'Singapore': 'SG', 'United States': 'US',
             'Canada': 'CA', 'United Kingdom': 'GB', 'Germany': 'DE', 'Netherlands': 'NL',
             'France': 'FR', 'Australia': 'AU', 'Hong Kong': 'HK', 'Taiwan': 'TW',
             'India': 'IN', 'Brazil': 'BR', 'Spain': 'ES', 'Italy': 'IT', 'Sweden': 'SE',
             'Poland': 'PL', 'Switzerland': 'CH', 'Finland': 'FI', 'Norway': 'NO',
             'Belgium': 'BE', 'Ireland': 'IE', 'Austria': 'AT', 'Denmark': 'DK'}
    locations = []
    for component in components:
        match = re.fullmatch(r'(.+?),\s*([^,]+?)\s*-\s*\(([A-Z0-9]{3})\)', component['name'])
        if match:
            city, country, colo = match.groups()
            locations.append({'iata': colo, 'cca2': codes.get(country.strip(), 'OTHER'),
                              'city': city, 'region': country.strip()})
    (WORK / 'locations.json').write_text(json.dumps(locations))
    ranges = json.loads(fetch('https://api.cloudflare.com/client/v4/ips'))
    if not ranges.get('success'):
        raise RuntimeError('Official IP ranges API failed')
    networks = [ipaddress.ip_network(line) for line in ranges['result']['ipv4_cidrs']]
    # Equal samples per published prefix, at most 32 per prefix (~480 total).
    candidates = set()
    for network in networks:
        span = network.num_addresses // 32
        for bucket in range(32):
            offset = bucket * span + random.randrange(1, max(2, span - 1))
            candidates.add(str(network.network_address + offset))
    # Carry previous good candidates forward for revalidation.
    for filename in ('ip.txt', 'global.txt'):
        path = ROOT / filename
        if path.exists():
            for line in path.read_text().splitlines():
                try:
                    address = ipaddress.ip_address(line.split(':')[0])
                    if address.version == 4 and any(address in net for net in networks):
                        candidates.add(str(address))
                except ValueError:
                    pass
    (WORK / 'candidates.txt').write_text('\n'.join(sorted(candidates)) + '\n')
    (WORK / 'cli.json').write_text('{}')
    return binary, locations, len(candidates)


def probe(ip):
    samples = []
    colos = []
    for _ in range(3):
        # Disable environment proxies so --resolve really measures this entrance.
        result = subprocess.run([
            'curl', '--silent', '--show-error', '--fail', '--noproxy', '*',
            '--connect-timeout', '4', '--max-time', '8',
            '--resolve', f'speed.cloudflare.com:443:{ip}',
            'https://speed.cloudflare.com/cdn-cgi/trace', '-w', '\nTIME:%{time_total}'
        ], capture_output=True, text=True)
        if result.returncode:
            return None
        trace = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        colo = trace.get('colo')
        if not colo or 'TIME:' not in result.stdout:
            return None
        samples.append(float(result.stdout.rsplit('TIME:', 1)[1]) * 1000)
        colos.append(colo)
    if len(set(colos)) != 1 or max(samples) > 1500:
        return None
    return {'ip': ip, 'colo': colos[0], 'median_ms': round(statistics.median(samples), 1),
            'max_ms': round(max(samples), 1), 'samples_ms': [round(s, 1) for s in samples]}


def write_list(name, rows):
    # Keep the source URL stable; unknown quality is never presented as zero risk.
    if rows:
        lines = []
        for i, row in enumerate(rows[:LIST_SIZE], 1):
            score = row.get('quality', {}).get('quality_score')
            label = f'Q{score:g}' if score is not None else 'Q-Unknown'
            lines.append(f"{row['ip']}:443#CF-{i:02d}-{label}\n")
        (ROOT / name).write_text(''.join(lines))


def select_best(rows):
    selected, seen = [], set()
    for row in sorted(rows, key=ranking_key):
        if row.get('node_passed') and row['ip'] not in seen:
            selected.append(row)
            seen.add(row['ip'])
            if len(selected) == LIST_SIZE:
                break
    return selected


def main():
    started = time.monotonic()
    WORK.mkdir(exist_ok=True)
    profile = load_profile(WORK)
    node_binary = prepare_runtime(WORK)
    binary, locations, count = prepare()
    location_map = {row['iata'].upper(): row['cca2'].upper() for row in locations}
    result_file = WORK / 'scan.csv'
    result_file.unlink(missing_ok=True)
    with (WORK / 'scan.log').open('w') as log:
        subprocess.run([str(binary), '-cli', '-config', 'cli.json', '-mode', 'nsb',
                        '-nsbfile', 'candidates.txt', '-scanmode', 'httping',
                        '-nsbfallbackport', '443', '-nsbthreads', '24', '-nsbtls=true',
                        '-nsbspeedtest', '0', '-nsbresultlimit', '1000', '-nsbdelay', '1500',
                        '-out', 'scan', '-outformat', 'csv', '-outfields', 'ip,port,dc,latency',
                        '-outendrow', '0', '-skipgeo', '-nocolor', '-progress=false'],
                       cwd=WORK, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600,
                       env={k: v for k, v in os.environ.items() if k != 'NODE_PROFILE_JSON'})
    rows = []
    if result_file.exists():
        with result_file.open(encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
    countries = Counter(location_map.get(row['数据中心'].upper(), 'UNKNOWN') for row in rows)
    # One global budget, with no country filter or regional quota.
    chosen = {r['IP地址'] for r in rows[:PROBE_LIMIT]}
    validated = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for row in pool.map(probe, sorted(chosen)):
            if row:
                row['country'] = location_map.get(row['colo'].upper(), 'UNKNOWN')
                validated.append(row)
    validated.sort(key=lambda r: (r['max_ms'], r['median_ms']))
    print(f'Entrance validation: {len(validated)} passed; starting full proxy checks', flush=True)
    # Exercise actual nodes before either public list can be replaced.
    node_reports = []
    usable = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        checks = pool.map(lambda row: check_node(row['ip'], profile, node_binary, WORK), validated)
        for entrance, report in zip(validated, checks):
            node_reports.append(report)
            print(f"Node check {len(node_reports)}/{len(validated)}: {report['phase']} "
                  f"{'passed' if report['passed'] else report.get('failure', 'failed')}", flush=True)
            if report['passed']:
                usable.append({**entrance, 'node_passed': True,
                               **{k: report[k] for k in ('success_rate', 'proxy_max_ms', 'proxy_median_ms',
                                                        'download_kib_s', 'sustained_seconds', 'quality')}})
    exit_summary = cross_check_exits(usable)
    by_ip = {r['ip']: r['exit_check'] for r in usable}
    for report in node_reports:
        if report['ip'] in by_ip:
            report['exit_check'] = by_ip[report['ip']]
    (WORK / 'node-checks.json').write_text(json.dumps(node_reports, indent=2) + '\n')
    usable.sort(key=ranking_key)
    selected = select_best(usable)
    write_list('ip.txt', selected)
    write_list('global.txt', selected)
    previous = json.loads((ROOT / 'status.json').read_text()) if (ROOT / 'status.json').exists() else {}
    now = datetime.now(timezone.utc).isoformat()
    status = {'checked_at': now,
              'last_list_update': now if selected else previous.get('last_list_update'),
              'state': 'updated' if len(selected) == LIST_SIZE else 'partial' if selected else 'no_candidates',
              'scanner': 'CFData-WEB ' + VERSION, 'candidate_count': count,
              'reachable_count': len(rows), 'observed_countries': dict(countries),
              'validated_count': len(validated),
              'node_checked_count': len(node_reports), 'node_passed_count': len(usable),
              'node_failures': dict(Counter(r['phase']+':'+r.get('failure', 'unknown') for r in node_reports if not r['passed'])),
              'validation_level': 'real_proxy_requests_and_transfer',
              'selected_count': len(selected), 'selected_countries': dict(Counter(r['country'] for r in selected)),
              'selection_policy': 'global_quality_then_proxy_performance',
              'quality_scored_count': sum(r['quality']['state'] == 'scored' for r in usable),
              'quality_unknown_count': sum(r['quality']['state'] != 'scored' for r in usable),
              'quality_provider': 'IPPure',
              'exit_cross_check': exit_summary,
              'quality_score_definition': '100 - IPPure fraudScore; higher is lower reported risk',
              'elapsed_seconds': round(time.monotonic()-started),
              'measurement_origin': 'GitHub hosted runner' if os.getenv('GITHUB_ACTIONS') else 'local',
              'validated': validated, 'selected': selected,
              'note': 'Entrance countries are diagnostic only. IPPure describes the exit to its own endpoint, not every destination. Unknown quality remains eligible; all checks reflect runner conditions, not home-line or AI eligibility.'}
    (ROOT / 'status.json').write_text(json.dumps(status, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({k: v for k, v in status.items() if k not in ('validated', 'selected')}, ensure_ascii=False))
    summary = os.getenv('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as handle:
            handle.write(f"## Cloudflare entrance scan\n\n{count} candidates; {len(rows)} reachable; "
                         f"{len(usable)}/{len(node_reports)} passed real proxy checks; {len(selected)} selected by quality and proxy performance.\n\nObserved countries: {dict(countries)}\n\n"
                         f"IPPure scored: {status['quality_scored_count']}; unknown: {status['quality_unknown_count']}.\n\n"
                         f"IP2Location.io: {exit_summary['checked_exit_count']}/{exit_summary['unique_exit_count']} unique exits checked; "
                         f"{exit_summary['mismatched_node_count']} nodes with metadata differences.\n\n"
                         'No country quotas. Higher quality means lower reported exit risk. Unknown scores use proxy performance; empty results preserve previous files.\n')
    if not selected:
        raise RuntimeError('No nodes passed full proxy checks; existing lists preserved')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        path = ROOT / 'status.json'
        previous = json.loads(path.read_text()) if path.exists() else {}
        failure = {**previous, 'checked_at': datetime.now(timezone.utc).isoformat(), 'state': 'failed',
                   'error': str(error),
                   'last_list_update': previous.get('last_list_update')}
        path.write_text(json.dumps(failure, indent=2, ensure_ascii=False) + '\n')
        raise
