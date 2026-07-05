"""
swarm_handler.py — Generic Swarm Research Tool

Orchestrates parallel research agents to research N entities on a topic,
verify results against a checklist, retry failures, and assemble a report.
"""

import json
import re
import time
import uuid
import concurrent.futures
import traceback
from datetime import datetime
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Callable

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from agent_handler import web_search, fetch_url, _unload_ollama_model

# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class MetricValue:
    value: float | str | None = None
    unit: str = ""
    year: int | str = ""
    source_url: str = ""
    verified: bool = False
    notes: str = ""

    def is_filled(self) -> bool:
        return self.value is not None and bool(self.source_url)


@dataclass
class CompanyResult:
    company: str
    ticker: str = ""
    revenue: MetricValue = field(default_factory=MetricValue)
    margin: MetricValue = field(default_factory=MetricValue)
    other_metrics: list[MetricValue] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    status: str = "pending"
    errors: list[str] = field(default_factory=list)
    retry_count: int = 0

    def to_summary(self) -> dict:
        return {
            "company": self.company,
            "ticker": self.ticker,
            "revenue": asdict(self.revenue) if self.revenue.is_filled() else None,
            "margin": asdict(self.margin) if self.margin.is_filled() else None,
            "metric_count": len(self.other_metrics),
            "source_count": len(self.sources),
            "status": self.status,
            "errors": self.errors[:3],
            "retry_count": self.retry_count,
        }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _parse_json_from_llm(content: str) -> dict | list | None:
    idx = content.find("[")
    if idx < 0:
        idx = content.find("{")
    if idx < 0:
        return None
    bracket = content[idx]
    end_char = "]" if bracket == "[" else "}"
    end = content.rfind(end_char)
    if end < 0:
        return None
    content = content[idx:end+1]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    try:
        content = re.sub(r",\s*([}\]])", r"\1", content)
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def _make_llm(upstream: str, api_key: str | None, model: str) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        openai_api_base=upstream + "/v1",
        openai_api_key=api_key or "not-needed",
        temperature=0.0,
        extra_body={"keep_alive": 0},
    )


# ── Phase 1: Discovery ──────────────────────────────────────────────────────

def discover_companies(
    topic: str,
    count: int,
    upstream: str,
    api_key: str | None,
    model: str,
    emit: Callable[[dict], None] | None = None,
) -> list[str]:
    """Search the web and compile a list of {topic} companies."""
    queries = [
        f"top {count} {topic} list 2025",
        f"largest {topic} companies by revenue",
        f"{topic} industry company rankings",
    ]
    all_text = ""
    for q in queries:
        if emit:
            emit({"type": "progress", "phase": "discovery",
                   "message": f"Searching: {q[:60]}..."})
        result = web_search.invoke({"query": q, "max_results": 5})
        all_text += f"\n--- Search: {q} ---\n{result}\n"

    if emit:
        emit({"type": "progress", "phase": "discovery",
               "message": f"Extracting company names from search results..."})

    llm = _make_llm(upstream, api_key, model)
    prompt = f"""Extract a deduplicated list of {topic} companies from these search results.

Return ONLY a valid JSON array of strings (company names). No other text.
Example: ["Tesla, Inc.", "BYD Company Ltd.", ...]

Include as many companies as you can find in the results. Be thorough.

Search results:
{all_text}"""

    try:
        resp = llm.invoke([HumanMessage(content=prompt)],
                          timeout=120, max_tokens=4096)
        content = resp.content.strip()
        parsed = _parse_json_from_llm(content)
        if isinstance(parsed, list):
            companies = [str(c).strip() for c in parsed if str(c).strip()]
            return companies[:count]
        return []
    except Exception as e:
        print(f"[Swarm] discover_companies error: {e}", flush=True)
        return []


# ── Helper: Extract ticker ──────────────────────────────────────────────────

EXCHANGE_SUFFIXES = {
    ".SS": "Shanghai", ".SZ": "Shenzhen", ".HK": "Hong Kong",
    ".TO": "Toronto", ".V": "TSX Venture", ".L": "London",
    ".PA": "Paris", ".DE": "Xetra/Dusseldorf", ".MI": "Milan",
    ".MC": "Madrid", ".CO": "Copenhagen", ".ST": "Stockholm",
    ".OL": "Oslo", ".HE": "Helsinki", ".AS": "Amsterdam",
    ".BR": "Brussels", ".AX": "Australia", ".SI": "Singapore",
    ".KL": "Malaysia", ".JK": "Indonesia", ".KS": "Korea",
    ".KQ": "Kosdaq", ".T": "Tokyo", ".TW": "Taiwan",
    ".BO": "BSE India", ".NS": "NSE India", ".SA": "Sao Paulo",
    ".TA": "Tel Aviv", ".SR": "Saudi",
}

def _extract_ticker(
    company: str,
    upstream: str,
    api_key: str | None,
    model: str,
) -> str | None:
    """Search the web for the company's ticker symbol, including exchange suffix."""
    try:
        sr = web_search.invoke(
            {"query": f"{company} stock ticker symbol exchange", "max_results": 5}
        )
        llm = _make_llm(upstream, api_key, model)
        prompt = f"""Extract the stock ticker symbol for {company} from these search results.

Return ONLY the ticker symbol with the exchange suffix if applicable
(e.g., "TSLA" for US-listed, "600104.SS" for Shanghai, "0700.HK" for Hong Kong,
"TM" for Toyota on NYSE, "SFTBY" for SoftBank OTC).
If none found or unclear, return "UNKNOWN".

Search results:
{sr}"""
        resp = llm.invoke([HumanMessage(content=prompt)], timeout=30, max_tokens=30)
        ticker = resp.content.strip().strip('"').strip("'").upper()
        return ticker if ticker and ticker != "UNKNOWN" else None
    except Exception as e:
        print(f"[Swarm] ticker fetch error for {company}: {e}", flush=True)
        return None


# ── Phase 2: Research single company ────────────────────────────────────────

def _research_company(
    company: str,
    topic: str,
    upstream: str,
    api_key: str | None,
    model: str,
    timeout: int = 60,
) -> CompanyResult:
    """Research one company: try yfinance first, fall back to web+LLM."""
    result = CompanyResult(company=company)

    # Phase 2a: Try yfinance for public companies
    ticker = _extract_ticker(company, upstream, api_key, model)
    if ticker:
        result.ticker = ticker
        try:
            import yfinance as yf
            import re

            cleaned = ticker.split(".")[0] if "." in ticker else ticker
            cleaned = re.sub(r"[^A-Z0-9]", "", cleaned)
            if len(cleaned) < 1 or len(cleaned) > 6:
                cleaned = ticker

            def _fetch_info(t: str) -> dict | None:
                try:
                    tk = yf.Ticker(t)
                    info = tk.info or {}
                    if info.get("totalRevenue") is not None or info.get("profitMargins") is not None:
                        return info
                except Exception:
                    pass
                return None

            info = _fetch_info(ticker)
            if info is None:
                has_suffix = any(ticker.endswith(s) for s in EXCHANGE_SUFFIXES)
                if not has_suffix:
                    for suffix in EXCHANGE_SUFFIXES:
                        suffixed = ticker + suffix
                        info = _fetch_info(suffixed)
                        if info is not None:
                            result.ticker = suffixed
                            break

            if info:
                rev = info.get("totalRevenue")
                if rev is not None and rev > 0:
                    result.revenue = MetricValue(
                        value=round(rev / 1_000_000),
                        unit="million USD",
                        year=datetime.now().year - 1,
                        source_url=f"https://finance.yahoo.com/quote/{result.ticker}/key-statistics/",
                    )

                margin = info.get("profitMargins")
                if margin is not None:
                    result.margin = MetricValue(
                        value=round(margin * 100, 1),
                        unit="net profit margin",
                        year=datetime.now().year - 1,
                        source_url=f"https://finance.yahoo.com/quote/{result.ticker}/key-statistics/",
                    )

                if result.revenue.is_filled() and result.margin.is_filled():
                    result.sources.append({
                        "url": f"https://finance.yahoo.com/quote/{result.ticker}/",
                        "title": f"{company} ({result.ticker}) on Yahoo Finance",
                    })
                    return result
                elif result.revenue.is_filled() or result.margin.is_filled():
                    result.sources.append({
                        "url": f"https://finance.yahoo.com/quote/{result.ticker}/",
                        "title": f"{company} ({result.ticker}) on Yahoo Finance (partial)",
                    })
        except ImportError:
            pass
        except Exception as e:
            result.errors.append(f"yfinance error: {e}")

    # Phase 2b: Fallback — web search + LLM extraction with training knowledge
    searches = [
        f"{company} annual revenue {datetime.now().year - 1} financial results",
        f"{company} profit margin operating margin",
        f"{company} stock ticker symbol",
    ]

    search_texts = {}
    for q in searches:
        try:
            sr = web_search.invoke({"query": q, "max_results": 5})
            search_texts[q] = sr
        except Exception as e:
            search_texts[q] = f"Search error: {e}"

    all_results = "\n\n".join(
        f"Query: {q}\nResults:\n{txt}" for q, txt in search_texts.items()
    )

    llm = _make_llm(upstream, api_key, model)

    user_prompt = f"""Extract financial data for {company} in the {topic} sector.

Search results:
{all_results}

Return valid JSON with this exact schema (use null for truly unknown private companies):
{{
  "company": "{company}",
  "ticker": "stock ticker symbol or null",
  "revenue": {{"value": number or null, "unit": "million USD or null", "year": 2024 or null, "source_url": "url or null"}},
  "margin": {{"value": number or null, "type": "operating/profit or null", "year": 2024 or null, "source_url": "url or null"}},
  "other_metrics": [{{"name": "...", "value": "...", "source_url": "..."}}],
  "sources": [{{"url": "source url", "title": "page title"}}]
}}

Rules:
- Use data from search results when possible.
- If search results lack the data but this is a well-known public company
  whose financials you know from training, provide the figure and set
  source_url to "knowledge_base". Only use null for genuinely unknown
  private companies.
- Include at least 1-2 additional metrics if available."""

    try:
        resp = llm.invoke([
            HumanMessage(content=user_prompt),
        ], timeout=90, max_tokens=2048)
        content = resp.content.strip()
        _unload_ollama_model(model, upstream)
        parsed = _parse_json_from_llm(content)

        if isinstance(parsed, dict):
            if parsed.get("ticker") and not result.ticker:
                result.ticker = str(parsed["ticker"])
            rev = parsed.get("revenue") or {}
            if rev.get("value") is not None and not result.revenue.is_filled():
                result.revenue = MetricValue(
                    value=rev["value"],
                    unit=rev.get("unit", "million USD") or "million USD",
                    year=rev.get("year", "") or "",
                    source_url=rev.get("source_url", "") or "",
                )
            marg = parsed.get("margin") or {}
            if marg.get("value") is not None and not result.margin.is_filled():
                result.margin = MetricValue(
                    value=marg["value"],
                    unit=marg.get("type", "operating") or "operating",
                    year=marg.get("year", "") or "",
                    source_url=marg.get("source_url", "") or "",
                )
            for m in parsed.get("other_metrics") or []:
                if isinstance(m, dict) and m.get("name"):
                    result.other_metrics.append(MetricValue(
                        value=m.get("value"),
                        unit=m.get("name", ""),
                        source_url=m.get("source_url", ""),
                    ))
            for s in parsed.get("sources") or []:
                if isinstance(s, dict) and s.get("url"):
                    if s["url"] not in [x["url"] for x in result.sources]:
                        result.sources.append(s)
    except Exception as e:
        result.errors.append(f"Extraction error: {e}")

    return result


# ── Phase 3: Verification ───────────────────────────────────────────────────

def _verify_company(
    result: CompanyResult,
    upstream: str,
    api_key: str | None,
    model: str,
) -> CompanyResult:
    """Verify a company result against the checklist.
    
    Two-tier:
      pass — real resolvable URL, all fields filled
      warn — knowledge_base or unresolvable URL, still has data
      fail — genuinely missing data
    """
    errors = []
    warnings = []

    if not result.revenue.is_filled():
        errors.append("Revenue: missing or no source URL")
    elif result.revenue.source_url == "knowledge_base":
        warnings.append("Revenue: from LLM knowledge (not web-verified)")
    elif not result.revenue.source_url.startswith("http"):
        errors.append(f"Revenue source URL invalid: {result.revenue.source_url}")

    if not result.margin.is_filled():
        errors.append("Margin: missing or no source URL")
    elif result.margin.source_url == "knowledge_base":
        warnings.append("Margin: from LLM knowledge (not web-verified)")
    elif not result.margin.source_url.startswith("http"):
        errors.append(f"Margin source URL invalid: {result.margin.source_url}")

    if not result.ticker:
        errors.append("Ticker symbol: missing")

    for field, val in [("revenue", result.revenue), ("margin", result.margin)]:
        if val.is_filled() and val.source_url.startswith("http"):
            try:
                page = fetch_url.invoke({"url": val.source_url, "timeout": 10})
                if "error" in page.lower() and ("not found" in page.lower() or "404" in page.lower()):
                    warnings.append(f"{field} source URL not resolvable: {val.source_url}")
                else:
                    val.verified = True
            except Exception:
                warnings.append(f"{field} source URL fetch failed, using data anyway: {val.source_url}")

    if not result.sources:
        warnings.append("No web sources attached (data from LLM knowledge)")

    result.errors = errors + warnings
    result.status = "fail" if errors else "pass"
    return result


# ── Phase 5: Report Assembly ────────────────────────────────────────────────

def _build_html_matrix(results: list[CompanyResult]) -> str:
    rows = []
    for r in sorted(results, key=lambda x: x.company.lower()):
        rev_str = ""
        if r.revenue.is_filled():
            rev_val = r.revenue.value
            rev_str = f'{rev_val:,}' if isinstance(rev_val, (int, float)) and rev_val > 1000 else str(rev_val)
            rev_str += f' {r.revenue.unit}' if r.revenue.unit else ''
            if r.revenue.source_url:
                rev_str = f'<a href="{r.revenue.source_url}" target="_blank">{rev_str}</a>'
            if not r.revenue.verified:
                rev_str += ' <span style="color:orange">⚠</span>'
        elif r.revenue.value is not None:
            rev_str = str(r.revenue.value)
        else:
            rev_str = '<span style="color:var(--muted)">—</span>'

        mar_str = ""
        if r.margin.is_filled():
            mar_val = r.margin.value
            mar_str = f'{mar_val}%' if mar_val is not None else ''
            if r.margin.source_url:
                mar_str = f'<a href="{r.margin.source_url}" target="_blank">{mar_str}</a>'
            if not r.margin.verified:
                mar_str += ' <span style="color:orange">⚠</span>'
        else:
            mar_str = '<span style="color:var(--muted)">—</span>'

        status_icon = '\u2705' if r.status == 'pass' else '\u274c'
        ticker = f'<span style="color:var(--muted);font-size:10px">{r.ticker}</span>' if r.ticker else ''

        rows.append(f'''<tr>
  <td style="padding:4px 8px;border-bottom:1px solid var(--border)">{r.company} {ticker}</td>
  <td style="padding:4px 8px;border-bottom:1px solid var(--border);text-align:right;font-variant-numeric:tabular-nums">{rev_str}</td>
  <td style="padding:4px 8px;border-bottom:1px solid var(--border);text-align:right;font-variant-numeric:tabular-nums">{mar_str}</td>
  <td style="padding:4px 8px;border-bottom:1px solid var(--border);text-align:center">{status_icon}</td>
</tr>''')

    return f'''<div style="overflow-x:auto">
<table style="width:100%;border-collapse:collapse;font-size:11px;font-family:'JetBrains Mono',monospace">
<thead>
<tr style="background:var(--surf2);position:sticky;top:0">
  <th style="padding:6px 8px;text-align:left;border-bottom:2px solid var(--border)">Company</th>
  <th style="padding:6px 8px;text-align:right;border-bottom:2px solid var(--border)">Revenue</th>
  <th style="padding:6px 8px;text-align:right;border-bottom:2px solid var(--border)">Margin</th>
  <th style="padding:6px 8px;text-align:center;border-bottom:2px solid var(--border)">✓</th>
</tr>
</thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</div>'''


def _build_markdown_report(results: list[CompanyResult]) -> str:
    passed = [r for r in results if r.status == "pass"]
    failed = [r for r in results if r.status == "fail"]

    lines = ["# Swarm Research Report", ""]
    lines.append(f"**Companies researched:** {len(results)}")
    lines.append(f"**Passed verification:** {len(passed)}")
    lines.append(f"**Failed verification:** {len(failed)}")
    if failed:
        lines.append(f"**Failed:** {', '.join(r.company for r in failed)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for r in results:
        lines.append(f"## {r.company}")
        if r.ticker:
            lines.append(f"**Ticker:** {r.ticker}")
        lines.append("")

        if r.revenue.is_filled():
            rev = r.revenue
            src = f" [source]({rev.source_url})" if rev.source_url else ""
            verified = " ✓" if rev.verified else " ⚠ unverified"
            lines.append(f"- **Revenue:** {rev.value:,} {rev.unit} ({rev.year}){src}{verified}")
        elif r.revenue.value is not None:
            lines.append(f"- **Revenue:** {r.revenue.value} {r.revenue.unit}")
        else:
            lines.append("- **Revenue:** not found")

        if r.margin.is_filled():
            mar = r.margin
            src = f" [source]({mar.source_url})" if mar.source_url else ""
            verified = " ✓" if mar.verified else " ⚠ unverified"
            lines.append(f"- **Margin:** {mar.value}{'%' if mar.value is not None else ''} ({mar.unit}{', ' + str(mar.year) if mar.year else ''}){src}{verified}")
        elif r.margin.value is not None:
            lines.append(f"- **Margin:** {r.margin.value}")
        else:
            lines.append("- **Margin:** not found")

        for m in r.other_metrics:
            src = f" [source]({m.source_url})" if m.source_url else ""
            lines.append(f"- **{m.unit}:** {m.value}{src}")

        if r.sources:
            lines.append("")
            lines.append("**Sources:**")
            for s in r.sources:
                lines.append(f"- [{s.get('title', s['url'])}]({s['url']})")

        if r.errors:
            lines.append("")
            lines.append(f"**Errors:** {'; '.join(r.errors)}")

        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ── Main Orchestrator ────────────────────────────────────────────────────────

def run_swarm(
    topic: str,
    count: int = 100,
    parallel: int = 5,
    max_retries: int = 3,
    timeout: int = 60,
    upstream: str = None,
    api_key: str = None,
    model: str = None,
    emit: Callable[[dict], None] = print,
) -> dict:
    """Run the full swarm research pipeline. Calls emit(event_dict) for SSE."""
    from agent_handler import _SCAN_MODEL
    model = model or _SCAN_MODEL or "qwen3:14b-q8_0"
    start_time = time.time()

    emit({"type": "progress", "phase": "discovery",
          "message": f"Discovering top {count} {topic} companies..."})

    companies = discover_companies(topic, count, upstream, api_key, model, emit=emit)
    if not companies:
        emit({"type": "error", "message": f"No companies found for topic: {topic}"})
        return {"error": "No companies found"}

    companies = companies[:count]
    emit({"type": "progress", "phase": "discovery",
          "message": f"Found {len(companies)} companies", "companies": companies})

    results: dict[str, CompanyResult] = {}
    failed_queue: list[str] = list(companies)
    retry_counts: dict[str, int] = {}
    phase = "research"

    def _research_and_store(company: str, retry: int = 0) -> CompanyResult:
        r = _research_company(company, topic, upstream, api_key, model, timeout)
        r.retry_count = retry
        r = _verify_company(r, upstream, api_key, model)
        return r

    while failed_queue:
        batch = failed_queue[:parallel]
        del failed_queue[:parallel]

        emit({"type": "progress", "phase": phase,
              "message": f"Researching {len(batch)} companies...",
              "done": len([r for r in results.values() if r.status != "pending"]),
              "total": len(companies)})

        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as pool:
            fut_map = {}
            for company in batch:
                retry = retry_counts.get(company, 0)
                fut = pool.submit(_research_and_store, company, retry)
                fut_map[fut] = company

            for fut in concurrent.futures.as_completed(fut_map):
                company = fut_map[fut]
                try:
                    r = fut.result(timeout=timeout + 30)
                    results[company] = r

                    if r.status == "pass":
                        emit({"type": "company_result", "company": company,
                              "ticker": r.ticker,
                              "revenue": str(r.revenue.value) if r.revenue.is_filled() else None,
                              "margin": str(r.margin.value) if r.margin.is_filled() else None,
                              "status": "pass"})
                    else:
                        emit({"type": "company_failed", "company": company,
                              "errors": r.errors[:3],
                              "retry": r.retry_count})

                        if r.retry_count < max_retries:
                            retry_counts[company] = r.retry_count + 1
                            failed_queue.append(company)
                            emit({"type": "company_retry", "company": company,
                                  "retry": r.retry_count + 1,
                                  "max": max_retries})
                        else:
                            emit({"type": "company_exhausted", "company": company,
                                  "errors": r.errors[:3]})
                except concurrent.futures.TimeoutError:
                    results[company] = CompanyResult(
                        company=company, status="fail",
                        errors=[f"Research timed out after {timeout}s"])
                    if retry_counts.get(company, 0) < max_retries:
                        retry_counts[company] = retry_counts.get(company, 0) + 1
                        failed_queue.append(company)
                        emit({"type": "company_retry", "company": company,
                              "retry": retry_counts[company], "max": max_retries,
                              "reason": "timeout"})
                except Exception as e:
                    results[company] = CompanyResult(
                        company=company, status="fail",
                        errors=[f"Research error: {e}"])

        done_count = len([r for r in results.values() if r.status != "pending"])
        emit({"type": "progress", "phase": phase,
              "message": f"{done_count}/{len(companies)} companies processed, {len(failed_queue)} remaining in queue",
              "done": done_count, "total": len(companies)})

        if not failed_queue:
            break

    elapsed = time.time() - start_time
    passed = [r for r in results.values() if r.status == "pass"]
    failed = [r for r in results.values() if r.status == "fail"]

    emit({"type": "progress", "phase": "assembly",
          "message": "Assembling report..."})

    html_matrix = _build_html_matrix(list(results.values()))
    markdown_report = _build_markdown_report(list(results.values()))

    summary = {
        "total": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "elapsed_seconds": round(elapsed, 1),
        "elapsed": f"{int(elapsed // 60)}m {int(elapsed % 60)}s",
    }

    emit({"type": "done",
          "matrix": html_matrix,
          "report": markdown_report,
          "summary": summary})

    return {
        "results": {c: r.to_summary() for c, r in results.items()},
        "summary": summary,
    }
