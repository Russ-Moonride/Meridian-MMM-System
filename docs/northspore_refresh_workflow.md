# NorthSpore — Data Refresh & Modeling Workflow

## Steps

| Step | What you do | Time |
|---|---|---|
| 1. Drop manual files | Copy the files listed below into `data/raw/northspore/` | 5 min |
| 2. Refresh data | `python scripts/refresh_northspore.py --prod` | ~5 min |
| 3. Experiment locally | Open `notebooks/modeling/NorthSpore/northspore_model.ipynb`, run in dev mode, tune priors. Run the Save Settings cell when happy. | 30 min – 2 hrs |
| 4. Push to GitHub | `git push` — Colab always clones fresh from main | 1 min |
| 5. Production run | Open `notebooks/colab_runner.ipynb` in Colab → set `CLIENT = "northspore"`, `MODE = "prod"` → Run All | 30–45 min (unattended) |
| 6. Review results | Check `reviewer_report.json` in GCS. Results are live in the Dash app via BigQuery. | — |

## Manual files required before running the refresh script

Drop these into `data/raw/northspore/` — the script will tell you exactly which are missing if any are absent.

| File pattern | Source | Notes |
|---|---|---|
| `NS_IG_data_{vintage}.csv` | Instagram Insights export | Views column |
| `NS_FB_data_{vintage}.csv` | Facebook Insights export | Organic Impressions column |
| `NS_YT_data_{vintage}.csv` | YouTube Studio export | Views column |
| `NS_Promos_{vintage}.csv` | Maintained manually | Promo Intensity (%) and Product Launch columns |
| `Tiktok Ads_Untitled report_North Spore_{dates}.xlsx` | TikTok Ads Manager export | Optional — weeks with no file get 0 |

The script auto-detects all files matching each pattern and combines them. Just drop a new vintage file alongside the old ones — no config change needed.

## What's automated vs. manual

| Source | How it's handled |
|---|---|
| Paid media (all channels) | Pulled automatically from BigQuery |
| Pmax | Pulled from BigQuery, allocated to states by population weight |
| Temperature + rainfall | Pulled automatically from Open-Meteo (most populous city per state) |
| Organic views (IG/FB/YT) | **Manual upload** — allocated to states by population weight |
| Promo intensity | **Manual upload** — applied at national level |
| TikTok spend/impressions | **Manual upload** — Unknown geo redistributed proportionally |

## Notes

- The notebook automatically loads the newest processed file — no path update needed after a data refresh.
- Test mode (`python scripts/refresh_northspore.py`) pulls only the last 16 weeks and writes to `test_refresh.csv`. Use this to validate a new data pull before committing to a full run. Manual files are still required even in test mode.
- Temperature data uses Open-Meteo's ERA5-based historical archive — free, no API key, covers all 50 states and DC. One representative city per state (most populous).
- Billboard corrections and channel consolidations (Brand + Brand Shopping, Non-Brand + Competitors) are applied automatically inside the script.
