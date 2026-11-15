"""Performance benchmarks for the DNS Analyzer.

Run with: python -m scripts.bench example.com
          python -m scripts.bench --iterations 5 example.com
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dns.asyncresolver
from app.work_budget import ScanWorkBudget


async def bench_single(domain: str, iterations: int = 1) -> dict:
    """Benchmark a single domain scan over multiple iterations."""
    results = []
    for i in range(iterations):
        start = time.time()
        resolver = dns.asyncresolver.Resolver()
        records = await asyncio.wait_for(resolver.resolve(domain, "A"), timeout=5.0)
        elapsed = time.time() - start
        results.append({"iteration": i + 1, "resolution_time": elapsed})

    avg_resolution = sum(r["resolution_time"] for r in results) / len(results)
    min_resolution = min(r["resolution_time"] for r in results)
    max_resolution = max(r["resolution_time"] for r in results)

    return {
        "domain": domain,
        "iterations": iterations,
        "avg_resolution_time": avg_resolution,
        "min_resolution_time": min_resolution,
        "max_resolution_time": max_resolution,
    }


async def main():
    """Main benchmark entry point."""
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.bench <domain> [--iterations N]")
        print("  example.com    Benchmark single domain scan")
        print("  --iterations N Run N iterations (default: 1)")
        sys.exit(1)

    domain = sys.argv[1]
    iterations = 1

    if "--iterations" in sys.argv:
        idx = sys.argv.index("--iterations")
        if idx + 1 < len(sys.argv):
            iterations = int(sys.argv[idx + 1])

    print(f"=== DNS Analyzer Benchmark ===")
    print(f"Domain: {domain}")
    print(f"Iterations: {iterations}")
    print()

    result = await bench_single(domain, iterations)

    print(f"Results:")
    print(f"  Average resolution time: {result['avg_resolution_time']:.3f}s")
    print(f"  Min resolution time: {result['min_resolution_time']:.3f}s")
    print(f"  Max resolution time: {result['max_resolution_time']:.3f}s")
    print()

    # Test concurrency
    print(f"=== Concurrency Test ({8} concurrent scans) ===")
    start = time.time()
    tasks = [asyncio.wait_for(dns.asyncresolver.Resolver().resolve(domain, "A"), timeout=5.0) for _ in range(8)]
    await asyncio.gather(*tasks)
    concurrency_time = time.time() - start
    print(f"  8 concurrent A-record resolutions: {concurrency_time:.3f}s")
    print(f"  Average per scan: {concurrency_time / 8:.3f}s")
    print()

    # Test budget awareness
    print(f"=== Budget Awareness Test ===")
    budget = ScanWorkBudget()
    base_resolver = dns.asyncresolver.Resolver()
    budgeted_resolver = budget.resolver_for(base_resolver, "records")
    start = time.time()
    for _ in range(5):
        await asyncio.wait_for(budgeted_resolver.resolve(domain, "A"), timeout=5.0)
    budget_time = time.time() - start
    print(f"  5 scans with budget awareness: {budget_time:.3f}s")
    print(f"  Average per scan: {budget_time / 5:.3f}s")
    print(f"  Budget profile: {budget.__class__.__name__}")
    print(f"  Budget HTTP budget: {budget.http_budget if hasattr(budget, 'http_budget') else 'N/A'}")


if __name__ == "__main__":
    asyncio.run(main())