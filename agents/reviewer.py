"""
agents/reviewer.py
~~~~~~~~~~~~~~~~~~
AI reviewer — calls the Claude API with program.md as the system prompt,
passes structured model diagnostics and attribution results, and writes a
structured JSON verdict to outputs/{client_id}/reviewer_report.json.

Usage
-----
    python agents/reviewer.py --client northspore --run-id prod_2026-06-15
    python agents/reviewer.py --client freedom_power --outputs-dir outputs/freedom_power
    python agents/reviewer.py --client northspore --dry-run   # prints prompts, no API call

The script loads:
  1. program.md       — expert judgment system prompt (repo root)
  2. diagnostics.json — convergence metrics from the MCMC run
  3. contributions.csv — channel-level ROI and attribution

It returns structured JSON:
  {
    "overall_verdict": "pass" | "review" | "fail",
    "client_ready": true | false,
    "flags": [{"severity": "...", "parameter": "...", "message": "..."}],
    "framework_agreement": "...",
    "summary": "...",
    "recommendations": [...]
  }

Requirements
------------
  pip install anthropic pandas python-dotenv
  ANTHROPIC_API_KEY must be set in environment or .env file
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

# Load .env if present (ANTHROPIC_API_KEY lives here)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic package not installed. Run: pip install anthropic")
    sys.exit(1)

# ── Constants ──────────────────────────────────────────────────────────────────

REPO_ROOT  = Path(__file__).parent.parent
PROGRAM_MD = REPO_ROOT / "program.md"
MODEL_NAME = "claude-opus-4-5"   # Opus for judgment-heavy reviewer task
MAX_TOKENS = 2048

# ── Formatting helpers ─────────────────────────────────────────────────────────

def _fmt_diagnostics(diag: dict[str, Any]) -> str:
    """Format diagnostics.json into a readable block for the reviewer prompt."""
    lines = [
        f"Client:       {diag.get('client_id', 'unknown')}",
        f"Run ID:       {diag.get('run_id', 'unknown')}",
        f"Completed:    {diag.get('completed_at', 'unknown')}",
        f"Model type:   {diag.get('model_type', 'unknown')} "
        f"({diag.get('n_chains', '?')} chains, "
        f"{diag.get('n_adapt', '?')} adapt, "
        f"{diag.get('n_burnin', '?')} burnin, "
        f"{diag.get('n_keep', '?')} keep)",
        f"Runtime:      {diag.get('runtime_minutes', '?')} min",
        "",
        "CONVERGENCE",
        f"  max r-hat:  {diag.get('rhat_max', 'null')}",
        f"  min ESS:    {diag.get('ess_min', 'null')}",
        f"  converged:  {diag.get('converged', 'unknown')}",
        "",
        "R-HAT BY CHANNEL",
    ]
    rhat_by_ch = diag.get("rhat_by_channel", {})
    for ch, r in rhat_by_ch.items():
        flag = ""
        if r is not None:
            if r > 1.10:
                flag = "  ← FAIL"
            elif r > 1.05:
                flag = "  ← WARNING"
        lines.append(f"  {ch:<22} {r}{flag}")

    lines += ["", "ESS BY CHANNEL"]
    ess_by_ch = diag.get("ess_by_channel", {})
    for ch, e in ess_by_ch.items():
        flag = ""
        if e is not None:
            if e < 100:
                flag = "  ← FAIL"
            elif e < 200:
                flag = "  ← WARNING"
        lines.append(f"  {ch:<22} {e}{flag}")

    return "\n".join(lines)


def _fmt_contributions(df: pd.DataFrame | None) -> str:
    """Format contributions.csv into a channel-level summary."""
    if df is None or df.empty:
        return "No contributions data available."

    agg = (
        df.groupby(["channel", "channel_type"])
        .agg(
            total_contribution=("contribution", "sum"),
            total_spend=("spend", "sum"),
            roi=("roi", "first"),
            roi_lower_90=("roi_lower_90", "first"),
            roi_upper_90=("roi_upper_90", "first"),
        )
        .reset_index()
    )
    grand_total = agg["total_contribution"].sum()
    agg["contribution_pct"] = (agg["total_contribution"] / grand_total * 100).round(1)
    agg = agg.sort_values("contribution_pct", ascending=False)

    lines = [
        f"{'Channel':<22} {'Type':<10} {'Contrib%':>9} {'ROI':>7} {'CI-lo':>7} {'CI-hi':>7}",
        "-" * 65,
    ]
    for _, row in agg.iterrows():
        roi_str = f"{row['roi']:.2f}"            if pd.notna(row.get("roi"))           else "—"
        lo_str  = f"{row['roi_lower_90']:.2f}"   if pd.notna(row.get("roi_lower_90"))  else "—"
        hi_str  = f"{row['roi_upper_90']:.2f}"   if pd.notna(row.get("roi_upper_90"))  else "—"
        lines.append(
            f"{row['channel']:<22} {row['channel_type']:<10} "
            f"{row['contribution_pct']:>8.1f}% {roi_str:>7} {lo_str:>7} {hi_str:>7}"
        )

    # Attribution split summary
    paid     = agg[agg["channel_type"] == "paid"]["contribution_pct"].sum()
    organic  = agg[agg["channel_type"] == "organic"]["contribution_pct"].sum()
    baseline = agg[agg["channel_type"] == "baseline"]["contribution_pct"].sum()
    lines += [
        "",
        f"SPLIT: Paid {paid:.1f}%  |  Organic {organic:.1f}%  |  Baseline {baseline:.1f}%",
    ]
    return "\n".join(lines)


def _build_user_prompt(
    client_id: str,
    diagnostics: dict[str, Any],
    contributions_df: pd.DataFrame | None,
) -> str:
    diag_block    = _fmt_diagnostics(diagnostics)
    contrib_block = _fmt_contributions(contributions_df)

    return f"""You are reviewing a Meridian Marketing Mix Model run for client: **{client_id}**.

Apply your expert judgment from the system prompt (program.md) to assess this run.

---
## DIAGNOSTICS

{diag_block}

---
## ATTRIBUTION SUMMARY

{contrib_block}

---
## YOUR TASK

Respond with a single valid JSON object. No prose outside the JSON. Schema:

{{
  "overall_verdict": "pass" | "review" | "fail",
  "client_ready": true | false,
  "flags": [
    {{
      "severity": "info" | "warning" | "critical",
      "parameter": "<channel or metric name>",
      "message": "<specific issue and recommended action>"
    }}
  ],
  "framework_agreement": "<brief assessment: are results internally consistent and plausible?>",
  "summary": "<2-3 sentence plain-English summary for a non-technical colleague>",
  "recommendations": [
    "<specific next action, ordered by priority>"
  ]
}}

Verdict rules:
- overall_verdict = "fail" if r-hat > 1.10 on ANY channel, or negative baseline > 0.8, or n_chains < 4 with converged=false
- overall_verdict = "review" if any warning-level issue exists but no critical failures
- overall_verdict = "pass" only if convergence is clean AND attribution is plausible
- client_ready = false when overall_verdict is "fail" OR when model_type is "dev" (n_chains < 4)
- Flags must name the specific channel/metric and the threshold breached
- Recommendations must be actionable — specify what to change, not just "investigate"
"""


# ── Core review function ───────────────────────────────────────────────────────

def run_review(
    client_id: str,
    outputs_dir: Path,
    model: str = MODEL_NAME,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Load artifacts, call the Claude reviewer, write reviewer_report.json.

    Parameters
    ----------
    client_id   : Client identifier (e.g. "northspore")
    outputs_dir : Path to the run's output directory
    model       : Claude model string to use
    dry_run     : If True, print prompts without calling the API

    Returns
    -------
    dict with the reviewer's structured verdict
    """
    # ── Load program.md ───────────────────────────────────────────────────────
    if not PROGRAM_MD.exists():
        raise FileNotFoundError(
            f"program.md not found at {PROGRAM_MD}. "
            "Create it first — it is the reviewer's system prompt."
        )
    system_prompt = PROGRAM_MD.read_text()

    # ── Load diagnostics ──────────────────────────────────────────────────────
    diag_path = outputs_dir / "diagnostics.json"
    if not diag_path.exists():
        raise FileNotFoundError(
            f"diagnostics.json not found at {diag_path}. "
            "Run extract_outputs() first."
        )
    with open(diag_path) as f:
        diagnostics = json.load(f)

    # ── Load contributions ────────────────────────────────────────────────────
    contrib_path = outputs_dir / "contributions.csv"
    contributions_df = pd.read_csv(contrib_path) if contrib_path.exists() else None
    if contributions_df is None:
        print("WARNING: contributions.csv not found — reviewer will proceed without it.")

    # ── Build prompts ─────────────────────────────────────────────────────────
    user_prompt = _build_user_prompt(client_id, diagnostics, contributions_df)

    if dry_run:
        print("=== SYSTEM PROMPT (first 800 chars) ===")
        print(system_prompt[:800])
        print("\n=== USER PROMPT ===")
        print(user_prompt)
        return {}

    # ── Call Claude API ───────────────────────────────────────────────────────
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not set. Add it to your .env file or environment."
        )

    client_api = anthropic.Anthropic(api_key=api_key)
    print(f"Calling {model} to review {client_id} ({diagnostics.get('run_id', '?')})...")

    message = client_api.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_response = message.content[0].text.strip()

    # ── Parse JSON ────────────────────────────────────────────────────────────
    # Strip markdown fences if the model added them
    if raw_response.startswith("```"):
        lines = raw_response.split("\n")
        raw_response = "\n".join(
            l for l in lines
            if not l.startswith("```")
        )

    try:
        verdict = json.loads(raw_response)
    except json.JSONDecodeError as e:
        print(f"WARNING: Claude response was not valid JSON ({e})")
        raw_path = outputs_dir / "reviewer_report_raw.txt"
        raw_path.write_text(raw_response)
        print(f"Raw response saved → {raw_path}")
        verdict = {
            "overall_verdict": "review",
            "client_ready": False,
            "flags": [{
                "severity": "warning",
                "parameter": "reviewer",
                "message": "Reviewer returned non-JSON — check reviewer_report_raw.txt",
            }],
            "framework_agreement": "Unable to parse reviewer response.",
            "summary": "Reviewer returned a non-JSON response. Check reviewer_report_raw.txt.",
            "recommendations": ["Re-run reviewer; inspect raw output for malformed JSON."],
        }

    # Stamp metadata
    verdict["_meta"] = {
        "client_id": client_id,
        "run_id": diagnostics.get("run_id", "unknown"),
        "reviewed_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "reviewer_model": model,
    }

    # ── Write report ──────────────────────────────────────────────────────────
    report_path = outputs_dir / "reviewer_report.json"
    with open(report_path, "w") as f:
        json.dump(verdict, f, indent=2)

    # ── Print summary ─────────────────────────────────────────────────────────
    verdict_color = {
        "pass": "\033[92m",    # green
        "review": "\033[93m",  # yellow
        "fail": "\033[91m",    # red
    }
    reset = "\033[0m"
    v = verdict.get("overall_verdict", "?")
    color = verdict_color.get(v, "")

    print(f"\n{'='*60}")
    print(f"VERDICT:      {color}{v.upper()}{reset}")
    print(f"CLIENT READY: {verdict.get('client_ready', '?')}")
    print(f"\nSUMMARY:\n  {verdict.get('summary', '')}")
    flags = verdict.get("flags", [])
    if flags:
        print(f"\nFLAGS ({len(flags)}):")
        for flag in flags:
            sev = flag.get("severity", "?").upper()
            print(f"  [{sev}] {flag.get('parameter', '?')}: {flag.get('message', '')}")
    recs = verdict.get("recommendations", [])
    if recs:
        print(f"\nRECOMMENDATIONS:")
        for i, r in enumerate(recs, 1):
            print(f"  {i}. {r}")
    print(f"\nReport → {report_path}")
    print("="*60)

    return verdict


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the AI reviewer on a Meridian model output."
    )
    parser.add_argument("--client",      required=True,
                        help="Client ID (e.g. northspore, freedom_power)")
    parser.add_argument("--run-id",      default=None,
                        help="Run ID for logging (optional; pulled from diagnostics.json if omitted)")
    parser.add_argument("--outputs-dir", default=None,
                        help="Path to outputs dir (default: outputs/{client})")
    parser.add_argument("--model",       default=MODEL_NAME,
                        help=f"Claude model to use (default: {MODEL_NAME})")
    parser.add_argument("--dry-run",     action="store_true",
                        help="Print prompts without calling the API")
    args = parser.parse_args()

    outputs_dir = (
        Path(args.outputs_dir)
        if args.outputs_dir
        else REPO_ROOT / "outputs" / args.client
    )
    if not outputs_dir.exists():
        print(f"ERROR: outputs directory not found: {outputs_dir}")
        sys.exit(1)

    run_review(
        client_id=args.client,
        outputs_dir=outputs_dir,
        model=args.model,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
