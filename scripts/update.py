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

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.work'
REGIONS = {'JP', 'KR', 'SG'}
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
    if not all(any(r['cca2'] == code for r in locations) for code in REGIONS):
        raise RuntimeError('Official location metadata is missing target countries')
    (WORK / 'locations.json').write_text(json.dumps(locations))
    networks = [ipaddress.ip_network(line) for line in fetch('https://www.cloudflare.com/ips-v4').decode().split()]
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
    # Never replace a previous usable list with an empty one.
    if rows:
        (ROOT / name).write_text(''.join(
            f"{r['ip']}:443#CF-{r['country']}-{r['colo']}-{i+1}\n"
            for i, r in enumerate(rows[:20])))


def main():
    started = time.monotonic()
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
                       cwd=WORK, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    rows = []
    if result_file.exists():
        with result_file.open(encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
    countries = Counter(location_map.get(row['数据中心'].upper(), 'UNKNOWN') for row in rows)
    # Validate 40 Asian and 20 unrestricted candidates; preserve both meanings.
    asian = [r for r in rows if location_map.get(r['数据中心'].upper()) in REGIONS][:40]
    chosen = {r['IP地址'] for r in asian + rows[:20]}
    validated = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for row in pool.map(probe, sorted(chosen)):
            if row:
                row['country'] = location_map.get(row['colo'].upper(), 'UNKNOWN')
                if row['country'] != 'UNKNOWN':
                    validated.append(row)
    validated.sort(key=lambda r: (r['max_ms'], r['median_ms']))
    preferred = [r for r in validated if r['country'] in REGIONS]
    write_list('ip.txt', preferred)
    write_list('global.txt', validated)
    previous = json.loads((ROOT / 'status.json').read_text()) if (ROOT / 'status.json').exists() else {}
    now = datetime.now(timezone.utc).isoformat()
    status = {'checked_at': now, 'last_asia_update': now if preferred else previous.get('last_asia_update'),
              'state': 'updated' if preferred else 'no_asian_candidates',
              'scanner': 'CFData-WEB ' + VERSION, 'candidate_count': count,
              'reachable_count': len(rows), 'observed_countries': dict(countries),
              'validated_count': len(validated), 'asia_count': len(preferred),
              'asia_list_available': (ROOT / 'ip.txt').exists(), 'elapsed_seconds': round(time.monotonic()-started),
              'measurement_origin': 'GitHub hosted runner' if os.getenv('GITHUB_ACTIONS') else 'local',
              'validated': validated,
              'note': 'Entrance colo only; not proxy exit country, home-line speed, download speed or AI availability.'}
    (ROOT / 'status.json').write_text(json.dumps(status, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({k: v for k, v in status.items() if k != 'validated'}, ensure_ascii=False))
    summary = os.getenv('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as handle:
            handle.write(f"## Cloudflare entrance scan\n\n{count} candidates; {len(rows)} reachable; "
                         f"{len(preferred)} validated JP/KR/SG.\n\nObserved countries: {dict(countries)}\n\n"
                         'No Asian results: keep previous ip.txt; global.txt is a separate unrestricted list.\n')
    if not rows or not validated:
        raise RuntimeError('No validated entrances; existing lists preserved')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        path = ROOT / 'status.json'
        previous = json.loads(path.read_text()) if path.exists() else {}
        failure = {'checked_at': datetime.now(timezone.utc).isoformat(), 'state': 'failed',
                   'error': str(error), 'last_asia_update': previous.get('last_asia_update'),
                   'asia_list_available': (ROOT / 'ip.txt').exists()}
        path.write_text(json.dumps(failure, indent=2, ensure_ascii=False) + '\n')
        raise
