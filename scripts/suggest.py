#!/usr/bin/env python3
"""Optional, manually triggered LLM step for content opportunity hypotheses.

Only public competitor metadata and approved public positioning are sent.
No user inquiries, legal conversations, or case documents are included.
"""
from __future__ import annotations
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PROMPT = ROOT / "prompts" / "opportunity-generator.md"


def read_json(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def main():
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL")
    if not api_key or not model:
        print("AI generation skipped: add LLM_API_KEY secret and LLM_MODEL repository variable before manually enabling it.")
        return 0

    base = (os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    pages = read_json("competitor_content.json")
    news = read_json("competitor_news.json")
    inventory = (DATA / "content_inventory.csv").read_text(encoding="utf-8")
    positioning = (DATA / "positioning.md").read_text(encoding="utf-8")
    config = read_json("config.json")

    source_urls = {x.get("url") for x in pages} | {x.get("url") for x in news}
    source_urls |= {line.split(",", 1)[0] for line in inventory.splitlines()[1:] if line.strip()}
    public_pages = [{k: row.get(k) for k in (
        "competitor", "url", "title", "page_type", "query_cluster", "seed_query",
        "published_date", "last_updated", "observed_summary", "relevance_reason",
        "response_hypothesis", "change_status", "last_checked"
    )} for row in pages]
    input_data = {
        "pilot_location": config.get("pilot_location"),
        "snapshot_date": config.get("snapshot_date"),
        "ranking_caveat": config.get("ranking_caveat"),
        "competitor_page_observations": public_pages,
        "competitor_company_news": [{k: row.get(k) for k in ("competitor", "url", "title", "published_date", "news_type", "summary")} for row in news],
        "legalyti_positioning_and_guardrails": positioning,
        "legalyti_content_inventory": inventory,
    }
    system = PROMPT.read_text(encoding="utf-8")
    body = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(input_data, ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        rows = parsed.get("opportunities", [])
        safe_rows = []
        for n, row in enumerate(rows[:5], start=1):
            evidence = [u for u in row.get("evidence_urls", []) if u in source_urls]
            if not evidence:
                continue
            priority = row.get("priority", "Medium")
            if priority not in {"High", "Medium", "Low"}:
                priority = "Medium"
            row["id"] = f"ai-{n}"
            row["priority"] = priority
            row["evidence_urls"] = evidence
            row["search_demand"] = "Unverified unless separate keyword evidence is attached"
            review_required = row.get("review_required", [])
            if isinstance(review_required, str):
                review_required = [review_required]
            elif not isinstance(review_required, list):
                review_required = []
            row["review_required"] = list(dict.fromkeys(review_required + ["Attorney review for legal claims", "Marketing review for fit and CTA"]))
            row["status"] = "AI-generated hypothesis; human review required"
            safe_rows.append(row)
        output = DATA / "generated_opportunities.json"
        output.write_text(json.dumps(safe_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Generated {len(safe_rows)} review-only hypotheses.")
    except (urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"Opportunity generation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
