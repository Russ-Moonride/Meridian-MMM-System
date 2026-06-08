# Freedom Power — Data Refresh & Modeling Workflow

## Steps

| Step | What you do | Time |
|---|---|---|
| 1. Refresh data | `python scripts/refresh_freedom_power.py --prod` | ~2 min |
| 2. Experiment locally | Open `notebooks/modeling/Freedom_Power/Freedom_Power_model.ipynb`, run in dev mode, tune priors. Run the Save Settings cell when happy. | 30 min – 2 hrs |
| 3. Push to GitHub | `git push` — Colab always clones fresh from main | 1 min |
| 4. Production run | Open `notebooks/colab_runner.ipynb` in Colab → set `CLIENT = "freedom_power"`, `MODE = "prod"` → Run All | 30–45 min (unattended) |
| 5. Review results | Check `reviewer_report.json` in GCS. Results are live in the Dash app via BigQuery. | — |

## Notes

- The notebook automatically loads the newest processed file — no path update needed after a data refresh.
- Test mode (`python scripts/refresh_freedom_power.py`) pulls only the last 16 weeks and writes to `test_refresh.csv`. Use this to validate a new data pull before committing to a full run.
- GQV data lives at `gs://freedom_power_mmm/google-mmm/data/google-mmm-gqv/`. New exports are picked up automatically — just upload using the existing naming convention (`...{Month}{Year}Refresh.csv`).
- Billboard corrections are hardcoded in `src/transforms/freedom_billboard_correction.py`. Update that file when board schedules change.
