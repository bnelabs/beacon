# Beacon Capability Review vs. "Comprehensive Guide to Open Data Sources for Temporal GNN-Based Financial Contagion and Liquidity Risk Prediction"

## 1. Paper Baseline
The paper prescribes a cost-free data engineering strategy for temporal GNNs built on two pillars:
1. **Bulk-download-first** for static historical corpora (e.g., Kaggle mirrors of OHLCV, Finnhub financials, SEC metadata).
2. **Generous-access institutional APIs** for incremental updates (e.g., SEC EDGAR, FRED, BIS, OFR) paired with multi-frequency integration to support contagion and liquidity stress testing.
It also stresses the need for interbank and corporate graph construction, heterogeneous temporal GNN architectures, and robust scenario analysis for "what-if" assessments.

## 2. Data Acquisition and Management
| Paper Expectation | Beacon Implementation | Assessment | Evidence |
| --- | --- | --- | --- |
| Replace rate-limited retail APIs with institutional feeds (SEC, FRED, BIS, ECB) | Beacon ships dedicated plugins for SEC, FRED, BIS, ECB, IMF, World Bank, FDIC, and AI4Risk, delivering institutional-scale ingestion | ✅ Exceeds | `backend/plugins/sec_plugin.py`, `backend/plugins/fred_plugin.py`, `backend/plugins/bis_plugin.py`, `backend/plugins/ecb_banking_plugin.py`, `backend/plugins/world_bank_plugin.py`, `backend/plugins/imf_plugin.py`, `backend/plugins/fdic_plugin.py`, `backend/plugins/ai4risk_plugin.py` |
| Use bulk Kaggle downloads for historical OHLCV and fundamentals | No bulk-download pipeline exists; Yahoo Finance (yfinance) remains the default historical price source | ⚠️ Gap | `backend/plugins/yfinance_plugin.py`
| Secure repo/liquidity data from OFR | No OFR integration is present | ❌ Missing | absence of OFR plugin in `backend/plugins/`
| Include policy indices (GPR/EPU) as contextual features | Not implemented in configuration or plugins | ❌ Missing | `configs/config.yaml`
| Maintain configurable economic indicator list with TED spread, funding spreads | FRED plugin is integrated and configures TEDRATE and other macro series, but omits CPFF and STLFSI3 defaults | ⚠️ Partial | `backend/plugins/fred_plugin.py`, `configs/config.yaml`

**Implications**
- Institutional API coverage is strong and aligns with the recommended second pillar.
- Reliance on yfinance conflicts with the paper’s warning about rate limits and scraping fragility, motivating a bulk-ingestion task.
- Missing OFR, GPR, and EPU sources limit liquidity contagion fidelity and what-if scenario richness.

## 3. Graph Construction and Scenario Toolkit
| Paper Expectation | Beacon Implementation | Assessment | Evidence |
| --- | --- | --- | --- |
| Construct interbank contagion networks from BIS/FFIEC data | Beacon integrates BIS, FDIC, ECB banking, and AI4Risk datasets, enabling real exposure-driven graphs | ✅ Aligns | `backend/plugins/bis_plugin.py`, `backend/plugins/fdic_plugin.py`, `backend/plugins/ecb_banking_plugin.py`, `backend/plugins/ai4risk_plugin.py`
| Support corporate ownership and supply chain edges (SEC + OpenCorporates) | SEC filings are available, but OpenCorporates/supply-chain extraction are absent | ⚠️ Gap | `backend/plugins/sec_plugin.py`
| Provide pre-built crisis and policy scenarios for analysis | A scenario library includes historical crises (Lehman, COVID) and policy shocks | ✅ Aligns | `configs/scenario_library.json`

## 4. Temporal GNN and Multi-Frequency Modeling
| Paper Expectation | Beacon Implementation | Assessment | Evidence |
| --- | --- | --- | --- |
| Deploy advanced temporal GNN capable of heterogeneous message passing | Beacon’s `HeterogeneousGraphTransformer` combines per-source LSTMs, HGT layers, and attention pooling | ✅ Exceeds | `backend/modules/engine/models.py`
| Handle multi-frequency alignment (daily, quarterly, annual) | Multi-scale trainer normalizes per source, builds sequences, and manages forward-fill/downsample workflows | ✅ Aligns | `backend/modules/engine/multi_scale_trainer.py`
| Offer 30-day liquidity risk horizon | Configuration supports multiple horizons with 30-day default | ✅ Aligns | `configs/config.yaml`

## 5. Capability Gaps and Recommended Enhancements
1. **Bulk Historical Data Ingestion** – Introduce Kaggle-based loaders for OHLCV and Finnhub “Financials as Reported” datasets, then demote yfinance to incremental updates to match the bulk-download pillar.
2. **Liquidity Market Depth** – Add OFR short-term funding monitor endpoints to capture repo and funding market contagion channels missing from current plugins.
3. **Policy & Sentiment Context** – Implement plugins for GPR/EPU indices and optional news sentiment datasets to enable the paper’s recommended exogenous shock modeling.
4. **Corporate Network Coverage** – Extend ingestion to OpenCorporates or comparable sources plus NLP pipelines on 10-K/10-Q filings to surface supply-chain and related-party links.
5. **Macro Indicator Completeness** – Enrich the default FRED series list with CPFF, STLFSI3, and BAMLH0A0HYM2 to align with the proposed liquidity and credit risk proxies.

## 6. Action Plan for Closing Gaps

The table below translates the identified enhancements into concrete implementation workstreams so that Beacon can reach feature parity with the paper’s recommended framework.

| Priority | Workstream | Key Tasks | Impacted Artifacts |
| --- | --- | --- | --- |
| P1 | Bulk Kaggle ingestion | Build reusable Kaggle download helper, add OHLCV + Finnhub loaders, switch historical backfills away from `yfinance_plugin.py` | `backend/plugins/` (new Kaggle plugin), `scripts/` ETL jobs, `configs/config.yaml` defaults |
| P1 | OFR liquidity feeds | Implement OFR repo and funding data plugin with caching, expose new data products in configuration | `backend/plugins/ofr_plugin.py` (new), `configs/config.yaml`, `backend/modules/engine/data_pipeline.py` |
| P2 | Policy indices | Add lightweight plugins for GPR/EPU bulk files, wire into global feature ingestion schedule | `backend/plugins/gpr_plugin.py`, `backend/plugins/epu_plugin.py`, `configs/config.yaml` |
| P2 | Corporate network expansion | Integrate OpenCorporates academic API client, extend SEC parsing for related-party NLP extraction | `backend/plugins/opencorporates_plugin.py`, `backend/modules/etl/sec_nlp.py`, documentation |
| P3 | Macro default set | Extend FRED configuration to include CPFF, STLFSI3, BAMLH0A0HYM2, and update scenario templates to use them | `configs/config.yaml`, `backend/plugins/fred_plugin.py`, `configs/scenario_library.json` |

**Execution Guidance**
- Tackle P1 items first to eliminate the paper’s most serious data acquisition risks (rate limits and missing liquidity data).
- Schedule P2 streams alongside scenario enhancements so that “what-if” tooling can consume policy shocks end-to-end.
- Revisit the scenario library once new indicators arrive to ensure stress templates incorporate the richer macro context.

Overall, Beacon already satisfies the core architectural and modeling requirements outlined in the paper while leaving targeted data-ingestion enhancements to achieve full parity with the recommended open-data framework.
