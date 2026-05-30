#!/usr/bin/env python3
"""Apply infra/cloudflare/*.yaml to Cloudflare (DNS + tunnel ingress).

Idempotent upsert — safe to re-run after adding hostnames to the YAML.

Requires:
  CLOUDFLARE_API_TOKEN   — Zone:DNS:Edit + Account:Cloudflare Tunnel:Edit
  CLOUDFLARE_ACCOUNT_ID  — MADFAM Cloudflare account

Optional:
  CLOUDFLARE_ZONE_ID     — skip zone lookup for selva.town
  CLOUDFLARE_TUNNEL_ID   — tunnel UUID (or TUNNEL_ID from ~/.enclii/credentials)

Usage:
  python3 scripts/apply-cloudflare-infra.py --dry-run
  python3 scripts/apply-cloudflare-infra.py --dns
  python3 scripts/apply-cloudflare-infra.py --tunnel --merge
  # merge = safe default for shared enclii-prod tunnel
  python3 scripts/apply-cloudflare-infra.py --dns --tunnel --merge
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


def _dns_cname_target(spec: dict[str, Any]) -> str:
    """Resolve tunnel CNAME target for proxied hostnames."""
    if spec.get("cname_target"):
        return str(spec["cname_target"])
    tunnel_spec = yaml.safe_load(TUNNEL_FILE.read_text(encoding="utf-8"))
    tunnel_name = spec.get("tunnel") or tunnel_spec.get("tunnel", "enclii-prod")
    tid = _tunnel_id(str(tunnel_name))
    return f"{tid}.cfargotunnel.com"


def apply_dns(*, dry_run: bool) -> None:
    spec = yaml.safe_load(DNS_FILE.read_text(encoding="utf-8"))
    zone_name = spec.get("zone", "selva.town")
    records: list[dict[str, Any]] = spec.get("records") or []
    cname_target = _dns_cname_target(spec)
    if dry_run:
        print(f"[dry-run] zone={zone_name} records={len(records)} cname_target={cname_target}")
        for rec in records:
            content = rec.get("content") or cname_target
            print(
                f"  - {rec['type']} {rec['name']} -> {content} "
                f"(proxied={rec.get('proxied', True)})"
            )
        return

    zid = _zone_id(zone_name)

    for rec in records:
        rtype = rec["type"]
        name = rec["name"]
        content = rec.get("content") or cname_target
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


def _tunnel_id(tunnel_name: str) -> str:
    env_tid = os.environ.get("CLOUDFLARE_TUNNEL_ID") or os.environ.get("TUNNEL_ID", "")
    if env_tid:
        return env_tid
    return _tunnel_id_by_name(tunnel_name)


def apply_tunnel(*, dry_run: bool, merge: bool) -> None:
    spec = yaml.safe_load(TUNNEL_FILE.read_text(encoding="utf-8"))
    tunnel_name = spec.get("tunnel", "enclii-prod")
    desired: list[dict[str, Any]] = spec.get("ingress") or []
    # Drop catch-all from desired list — live config owns the final rule.
    desired_named = [r for r in desired if r.get("hostname")]

    if dry_run:
        mode = "merge" if merge else "replace"
        print(f"[dry-run] tunnel {tunnel_name} ({mode}): {len(desired_named)} hostname rule(s)")
        for rule in desired_named:
            print(f"  - {rule.get('hostname')} -> {rule.get('service')}")
        return

    tid = _tunnel_id(tunnel_name)
    account = _account_id()

    if merge:
        cfg = _request("GET", f"accounts/{account}/cfd_tunnel/{tid}/configurations")
        ingress: list[dict[str, Any]] = (cfg.get("result") or {}).get("config", {}).get(
            "ingress", []
        )
        if not ingress or ingress[-1].get("hostname"):
            print("error: live tunnel ingress missing catch-all", file=sys.stderr)
            sys.exit(1)
        existing = {r.get("hostname") for r in ingress if r.get("hostname")}
        added: list[str] = []
        for rule in desired_named:
            host = rule.get("hostname")
            if host in existing:
                continue
            ingress.insert(-1, rule)
            added.append(str(host))
        if not added:
            print(f"OK   tunnel {tunnel_name}: all {len(desired_named)} hostname rule(s) present")
            return
        payload_ingress = ingress
        summary = f"added {len(added)} rule(s): {', '.join(added)}"
    else:
        if not desired or desired[-1].get("hostname"):
            print(
                "error: --replace requires catch-all as final ingress rule in YAML",
                file=sys.stderr,
            )
            sys.exit(1)
        payload_ingress = desired
        summary = f"replaced with {len(desired)} rule(s)"

    body = _request(
        "PUT",
        f"accounts/{account}/cfd_tunnel/{tid}/configurations",
        {"config": {"ingress": payload_ingress}},
    )
    if not body.get("success"):
        print(f"error: tunnel PUT failed: {body.get('errors')}", file=sys.stderr)
        sys.exit(1)
    print(f"OK   tunnel {tunnel_name}: {summary}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Cloudflare DNS + tunnel ingress")
    parser.add_argument("--dns", action="store_true", help="Apply dns-records.yaml")
    parser.add_argument("--tunnel", action="store_true", help="Apply tunnel-routes.yaml")
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge hostname rules into live tunnel config (default when --tunnel set)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace full tunnel ingress (dangerous on shared enclii-prod tunnel)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions only")
    args = parser.parse_args()
    if not args.dns and not args.tunnel:
        args.dns = True
        args.tunnel = True
    merge = not args.replace
    if args.tunnel and not args.replace and not args.merge:
        merge = True
    if args.dns:
        apply_dns(dry_run=args.dry_run)
    if args.tunnel:
        apply_tunnel(dry_run=args.dry_run, merge=merge)


if __name__ == "__main__":
    main()
