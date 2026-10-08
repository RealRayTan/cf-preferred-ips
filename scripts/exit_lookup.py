"""Cross-check an observed exit by explicit IP; do not measure a second exit."""
import copy
import ipaddress
import json
import re
import time
import urllib.error
import urllib.request

PROVIDER = 'IP2Location.io'


def parse_location(payload, requested_ip):
    if not isinstance(payload, dict) or payload.get('error'):
        raise ValueError('Invalid lookup response')
    address = ipaddress.ip_address(payload.get('ip'))
    if address != ipaddress.ip_address(requested_ip) or not address.is_global:
        raise ValueError('Lookup returned a different IP')
    country = payload.get('country_code')
    asn = payload.get('asn')
    if not isinstance(country, str) or not re.fullmatch('[A-Z]{2}', country):
        raise ValueError('Invalid country')
    if isinstance(asn, bool) or not isinstance(asn, (str, int)) or not str(asn).isdigit():
        raise ValueError('Invalid ASN')
    asn = int(asn)
    if not 0 < asn <= 4294967295:
        raise ValueError('Invalid ASN')
    return {'state': 'checked', 'provider': PROVIDER, 'exit_ip': str(address),
            'exit_country': country, 'asn': asn,
            'is_public_proxy': payload.get('is_proxy') if type(payload.get('is_proxy')) is bool else None}


def lookup_exit(address):
    unknown = {'state': 'unknown', 'provider': PROVIDER}
    try:
        address = ipaddress.ip_address(address)
        if not address.is_global:
            return {**unknown, 'failure': 'invalid_exit_ip'}
        request = urllib.request.Request(
            f'https://api.ip2location.io/?ip={address}&format=json',
            headers={'Accept': 'application/json', 'User-Agent': 'cf-preferred-ips/1.0'})
        # Explicit IP lookup: the request origin has no role in the result.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=15) as response:
            body = response.read(65537)
            if len(body) > 65536:
                return {**unknown, 'failure': 'oversized_response'}
        return parse_location(json.loads(body), address)
    except urllib.error.HTTPError as error:
        return {**unknown, 'failure': 'rate_limited' if error.code == 429 else 'http_error'}
    except Exception:
        return {**unknown, 'failure': 'invalid_or_unavailable_response'}


def cross_check_exits(rows):
    cache = {}
    for row in rows:
        quality = row.get('quality', {})
        address = quality.get('exit_ip')
        if not address:
            row['exit_check'] = {'state': 'skipped', 'provider': PROVIDER,
                                 'failure': 'missing_observed_exit'}
            continue
        if address not in cache:
            if cache:
                time.sleep(1)
            cache[address] = lookup_exit(address)
        result = copy.deepcopy(cache[address])
        if result['state'] == 'checked':
            mismatches, compared = [], []
            for field in ('exit_country', 'asn'):
                if quality.get(field) is not None:
                    compared.append(field)
                    if quality[field] != result[field]:
                        mismatches.append(field)
            result['compared_fields'] = compared
            result['mismatched_fields'] = mismatches
            result['consistent'] = not mismatches if compared else None
        row['exit_check'] = result
    return {'provider': PROVIDER, 'unique_exit_count': len(cache), 'request_count': len(cache),
            'checked_exit_count': sum(v['state'] == 'checked' for v in cache.values()),
            'unknown_exit_count': sum(v['state'] != 'checked' for v in cache.values()),
            'mismatched_node_count': sum(bool(r['exit_check'].get('mismatched_fields')) for r in rows)}
