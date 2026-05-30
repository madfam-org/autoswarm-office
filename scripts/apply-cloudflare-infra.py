#!/usr/bin/env python3
"""Apply infra/cloudflare/*.yaml to Cloudflare (DNS + tunnel ingress).

Idempotent upsert — safe to re-run after adding hostnames to the YAML.

Requires:
  CLOUDFLARE_API_TOKEN   — Zone:DNS:Edit + Account:Cloudflare Tunnel:Edit
  CLOUDFLARE_ACCOUNT_ID  — MADFAM Cloudflare account

Optional:
  CLOUDFLARE_ZONE_ID     — skip zone lookup for selva.town

Usage:
  python3 scripts/apply-cloudflare-infra.py --dry-run
  python3 scripts/apply-cloudflare-infra.py --dns
  python3 scripts/apply-cloudflare-infra.py --tunnel
  python3 scripts/apply-cloudflare-infra.py --dns --tunnel
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    print("error: PyYAML required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[1]
DNS_FILE = REPO_ROOT / "infra" / "cloudflare" / "dns-records.yaml"
TUNNEL_FILE = REPO_ROOT / "infra" / "cloudflare" / "tunnel-routes.yaml"
CF_API = "https://api.cloudflare.com/client/v4"


def _headers() -> dict[str, str]:
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if not token:
        print("error: CLOUDFLARE_API_TOKEN must be set", file=sys.stderr)
        sys.exit(2)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _account_id() -> str:
    aid = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    if not aid:
        print("error: CLOUDFLARE_ACCOUNT_ID must be set", file=sys.stderr)
        sys.exit(2)
    return aid


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{CF_API}/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        print(f"error: CF API {method} {path} -> HTTP {exc.code}: {detail}", file=sys.stderr)
        sys.exit(1)


def _zone_id(zone_name: str) -> str:
    env_zid = os.environ.get("CLOUDFLARE_ZONE_ID", "")
    if env_zid:
        return env_zid
    body = _request("GET", f"zones?name={zone_name}&status=active")
    zones = body.get("result") or []
    if not zones:
        print(f"error: no active Cloudflare zone named {zone_name!r}", file=sys.stderr)
        sys.exit(1)
    return str(zones[0]["id"])


def _tunnel_id_by_name(name: str) -> str:
    account = _account_id()
    body = _request("GET", f"accounts/{account}/cfd_tunnel?is_deleted=false")
    for tunnel in body.get("result") or []:
        if tunnel.get("name") == name:
            return str(tunnel["id"])
    print(f"error: tunnel {name!r} not found in account", file=sys.stderr)
    sys.exit(1)


def apply_dns(*, dry_run: bool) -> None:
    spec = yaml.safe_load(DNS_FILE.read_text(encoding="utf-8"))
    zone_name = spec.get("zone", "selva.town")
    records: list[dict[str, Any]] = spec.get("records") or []
    if dry_run:
        print(f"[dry-run] zone={zone_name} records={len(records)}")
        for rec in records:
            print(
                f"  - {rec['type']} {rec['name']} -> {rec['content']} "
                f"(proxied={rec.get('proxied', True)})"
            )
        return

    zid = _zone_id(zone_name)

    for rec in records:
        rtype = rec["type"]
        name = rec["name"]
        content = rec["content"]
        proxied = rec.get("proxied", True)
        existing = _request(
            "GET",
            f"zones/{zid}/dns_records?type={rtype}&name={name}",
        )
        matches = existing.get("result") or []
        payload = {
            "type": rtype,
            "name": name,
            "content": content,
            "proxied": proxied,
        }
        if matches:
            rid = matches[0]["id"]
            cur = matches[0]
            if cur.get("content") == content and cur.get("proxied") == proxied:
                print(f"OK   DNS unchanged: {name}")
            else:
                _request("PATCH", f"zones/{zid}/dns_records/{rid}", payload)
                print(f"OK   DNS updated: {name}")
        else:
            _request("POST", f"zones/{zid}/dns_records", payload)
            print(f"OK   DNS created: {name}")


def apply_tunnel(*, dry_run: bool) -> None:
    spec = yaml.safe_load(TUNNEL_FILE.read_text(encoding="utf-8"))
    tunnel_name = spec.get("tunnel", "autoswarm-office")
    ingress: list[dict[str, Any]] = spec.get("ingress") or []
    if not ingress or ingress[-1].get("hostname"):
        print("error: tunnel ingress must end with hostname-less catch-all", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        print(f"[dry-run] tunnel {tunnel_name}: {len(ingress)} ingress rule(s)")
        for rule in ingress:
            host = rule.get("hostname") or "(catch-all)"
            print(f"  - {host} -> {rule.get('service')}")
        return

    tid = _tunnel_id_by_name(tunnel_name)
    account = _account_id()
    body = _request(
        "PUT",
        f"accounts/{account}/cfd_tunnel/{tid}/configurations",
        {"config": {"ingress": ingress}},
    )
    if not body.get("success"):
        print(f"error: tunnel PUT failed: {body.get('errors')}", file=sys.stderr)
        sys.exit(1)
    print(f"OK   tunnel {tunnel_name}: {len(ingress)} ingress rule(s) applied")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Cloudflare DNS + tunnel ingress")
    parser.add_argument("--dns", action="store_true", help="Apply dns-records.yaml")
    parser.add_argument("--tunnel", action="store_true", help="Apply tunnel-routes.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Print actions only")
    args = parser.parse_args()
    if not args.dns and not args.tunnel:
        args.dns = True
        args.tunnel = True
    if args.dns:
        apply_dns(dry_run=args.dry_run)
    if args.tunnel:
        apply_tunnel(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
