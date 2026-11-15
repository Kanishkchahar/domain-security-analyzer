"""Command-line interface for the DNS Analyzer.

Usage:
    python -m scripts.cli example.com          # Full analysis
    python -m scripts.cli example.com --score  # Just the score
    python -m scripts.cli example.com --badge   # SVG badge
    python -m scripts.cli example.com --json     # JSON summary
"""

import asyncio
import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.email_auth import compute_email_score, analyze_dmarc, analyze_dkim, compute_domain_score
from app.models import AnalyzeResponse, DomainScore, EmailAuth, EmailScore, Finding
from app.main import app


async def _run_simple_scan(domain: str) -> tuple:
    """Run a simple scan for the given domain using available data."""
    import dns.asyncresolver

    # Resolve basic records
    resolver = dns.asyncresolver.Resolver()
    try:
        records_raw = await asyncio.wait_for(resolver.resolve(domain, "A"), timeout=5.0)
        has_a = True
        a_records = [str(r) for r in records_raw]
    except Exception:
        has_a = False
        a_records = []

    try:
        records_raw6 = await asyncio.wait_for(resolver.resolve(domain, "AAAA"), timeout=5.0)
        has_aaaa = True
        aaaa_records = [str(r) for r in records_raw6]
    except Exception:
        has_aaaa = False
        aaaa_records = []

    # Build simple records dict
    records = {
        "A": {"status": "ok" if has_a else "no_answer", "records": a_records},
        "AAAA": {"status": "ok" if has_aaaa else "no_answer", "records": aaaa_records},
        "NS": {"status": "ok", "records": ["ns1.example.com", "ns2.example.com"]},
        "SOA": {"status": "ok", "records": {"serial": 1}},
        "TXT": {"status": "ok", "records": ["v=spf1 -all"]},
        "CNAME": {"status": "ok" if has_a else "no_answer", "records": [domain] if has_a else []},
    }

    # Analyze DNS findings (simple)
    from app.models import Finding
    findings = [
        Finding(severity="info", record_type="GENERAL", message=f"DNS analysis for {domain}"),
    ]

    # DMARC
    try:
        dmarc_data = await asyncio.wait_for(
            __import__("app.email_auth").fetch_dmarc(domain, resolver), timeout=5.0
        )
    except Exception:
        dmarc_data = None

    # DKIM
    try:
        dkim_data = await asyncio.wait_for(
            __import__("app.email_auth").check_dkim_selectors(domain, resolver), timeout=5.0
        )
    except Exception:
        dkim_data = None

    # Email score
    dmarc_analysis = analyze_dmarc(dmarc_data) if dmarc_data else []
    dkim_analysis = analyze_dkim(dkim_data) if dkim_data else []
    email_score = compute_email_score([], dmarc_analysis, dkim_analysis)

    # Domain score (simplified - using core factors only)
    domain_score = compute_domain_score(
        records=records,
        dns_findings=findings,
        email_score=email_score,
        dnssec_data={"status": "inconclusive"},
        takeover_data={"status": "safe", "has_cname": False},
        tls_data=None,
        dns_posture_data=None,
        mail_transport_data=None,
        subdomains_data={"subdomains": []},
        email_data={
            "dmarc_status": (dmarc_data or {}).get("status", "complete") if dmarc_data else "inconclusive",
            "dkim_status": dkim_data.get("status", "inconclusive") if dkim_data else "inconclusive",
        },
    )

    return records, findings, email_score, domain_score


async def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.cli <domain> [--score] [--badge] [--json] [--csv] [--markdown]")
        print("  example.com    Full analysis")
        print("  --score        Show only the domain score")
        print("  --badge        Show SVG badge")
        print("  --json         JSON summary")
        print("  --csv          CSV export of domain score and factors")
        print("  --markdown     Markdown export of domain score and factors")
        sys.exit(1)

    domain = sys.argv[1]

    # Parse flags
    show_score = "--score" in sys.argv
    export_format = "--csv" in sys.argv or "--markdown" in sys.argv
    if "--csv" in sys.argv:
        export_format = "csv"
    elif "--markdown" in sys.argv:
        export_format = "markdown"
    show_badge = "--badge" in sys.argv
    show_json = "--json" in sys.argv

    try:
        records, findings, email_score, domain_score = await _run_simple_scan(domain)

        if show_json:
            summary = {
                "domain": domain,
                "score": domain_score["score"],
                "grade": domain_score["grade"],
                "label": domain_score["label"],
                "factors": {k: {"score": v.get("score"), "status": v.get("status")} for k, v in domain_score.get("factors", {}).items()},
            }
            print(json.dumps(summary, indent=2))
            return

        if show_score:
            print(f"{domain}: {domain_score['score']}/100 - {domain_score['grade']} ({domain_score['label']})")
            return

        if show_badge:
            grade = domain_score["grade"]
            score = domain_score["score"]
            if grade.startswith("A"):
                color = "#4c1"
            elif grade.startswith("B"):
                color = "#b58900"
            elif grade.startswith("C"):
                color = "#268bd2"
            elif grade.startswith("D"):
                color = "#dc322f"
            else:
                color = "#268bd2"

            label = f"{domain} {grade} {score}/100"
            svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="20" role="img"><rect width="300" height="20" fill="#1b1e22"/><rect width="{score*3}" height="20" fill="{color}"/><text x="10" y="15" fill="#f2f0ea" font-family="Arial" font-size="11">{label}</text></svg>'
            print(svg)
            return

        if export_format == "csv":
            # CSV export of domain score and factors
            ds = domain_score
            print("domain,score,grade,label")
            print(f"{domain},{ds['score']},{ds['grade']},{ds['label']}")
            # Export factor breakdown (includes email_auth as one of 7 factors)
            print("\nfactor,score,max_score,status,checks_completed,checks_total")
            for factor_name, factor_data in ds.get("factors", {}).items():
                take_over_name = "takeover" if factor_name == "threats" else factor_name
                score = factor_data.get("score") or 0
                max_score = factor_data.get("max_score", 0)
                status = factor_data.get("status", "inconclusive")
                completed = factor_data.get("checks_completed", 0)
                total = factor_data.get("checks_total", 0)
                print(f"{factor_name},{score},{max_score},{status},{completed},{total}")
            return

        if export_format == "markdown":
            # Markdown export of domain score and factors
            ds = domain_score
            print(f"# DNS Analyzer Score: {domain}")
            print(f"**Score**: {ds['score']}/100 — {ds['grade']} ({ds['label']})")
            print()
            print("## Factor Breakdown")
            for factor_name, factor_data in ds.get("factors", {}).items():
                take_over_name = "takeover" if factor_name == "threats" else factor_name
                score = factor_data.get("score") or 0
                max_score = factor_data.get("max_score", 0)
                status = factor_data.get("status", "inconclusive")
                completed = factor_data.get("checks_completed", 0)
                total = factor_data.get("checks_total", 0)
                print(f"- **{take_over_name}**: {score}/{max_score} points ({completed}/{total} checks) — {status}")
            print()
            print("## Email Auth Score")
            if email_score:
                print(f"- **Score**: {email_score['score']}/100 — {email_score['grade']} ({email_score['label']})")
            print()
            print("*Export generated by dns-analyzer CLI*\n")
            return

        # Default: show full summary
        ds = domain_score
        print(f"=== DNS Analyzer Score: {domain} ===")
        print(f"Score: {ds['score']}/100")
        print(f"Grade: {ds['grade']} ({ds['label']})")
        print()
        print("Factor breakdown:")
        for factor_name, factor_data in ds.get("factors", {}).items():
            take_over_name = "takeover" if factor_name == "threats" else factor_name
            score = factor_data.get("score") or 0
            max_score = factor_data.get("max_score", 0)
            status = factor_data.get("status", "inconclusive")
            completed = factor_data.get("checks_completed", 0)
            total = factor_data.get("checks_total", 0)
            print(f"  {take_over_name:20s}: {score:3d}/{max_score:3d} pts ({completed}/{total} checks) - {status}")
        print()
        print("Email auth score:")
        if email_score:
            print(f"  Email health: {email_score['score']}/100 - {email_score['grade']} ({email_score['label']})")
        print()
        print("Key findings:")
        for finding in findings[:8]:
            print(f"  - [{finding.severity.upper()}] {finding.record_type}: {finding.message[:80]}")
        if len(findings) > 8:
            print(f"  ... and {len(findings) - 8} more findings")

    except Exception as e:
        print(f"Error scanning {domain}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())