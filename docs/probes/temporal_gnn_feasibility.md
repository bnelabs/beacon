# Temporal GNN Feasibility Memo

## Context
Phase 5/6 parked feature: Temporal Graph Neural Network for dynamic systemic risk propagation modeling.

## Prerequisite Now Available
**PIT (Point-in-Time) exposure vintages** — the platform now holds exposure snapshots with:
- Timestamped interbank liability matrices
- Historical exposure networks per prediction cycle
- Versioned balance sheet data in prediction store

## Temporal GNN Architecture Proposal

### Why Temporal GNN?
Current static network analysis:
- Computes centrality, clearing on single-time snapshot
- Misses **evolution patterns**: how distress propagates through time-varying topology
- Cannot capture **anticipatory signals**: topological changes precede stress events

Temporal GNN advantages:
- Models edge weight dynamics (exposure growth/decay)
- Learns temporal motifs (cascading failure patterns)
- Predicts future vulnerability from trajectory, not just state

### Data Structure
```python
# Current PIT store provides:
exposure_vintages = [
    {
        "timestamp": "2024-01-15T00:00:00Z",
        "liability_matrix": np.array([...]),  # n_banks x n_banks
        "node_features": {...},  # capital ratios, liquidity, etc.
    },
    # ... historical snapshots
]

# Temporal GNN consumes:
# - Sequence of adjacency matrices: A_{t-T}, ..., A_t
# - Sequence of node features: X_{t-T}, ..., X_t
# - Target: y_{t+1} (future stress indicator)
```

### Model Options

**Option 1: EvolveGCN** (recommended starting point)
- GCN weights evolve via RNN across time steps
- Handles graph structure changes naturally
- Proven in financial network literature

**Option 2: DyRep / TGN (Temporal Graph Networks)**
- Explicit event-based updates (better for irregular timestamps)
- More complex, higher memory footprint
- Better if exposure updates are asynchronous

**Option 3: ST-GCN (Spatio-Temporal GCN)**
- Separates spatial (GCN) and temporal (1D CNN) processing
- Simpler training, fixed-length windows
- Good baseline for comparison

## Implementation Requirements

### Current State ✅
- PIT exposure vintages stored
- Prediction engine produces timestamped snapshots
- Graph utilities exist (`backend.modules.risk.clearing`)

### Missing Pieces ⚠️
1. **Temporal batch loader**: Sequences of (A_t, X_t, y_t) tuples
2. **GNN architecture**: EvolveGCN or TGN implementation
3. **Training harness**: Temporal train/val/test split (no leakage!)
4. **Evaluation metrics**: Dynamic AUC, early-warning lead time

## Implementation Phases

### Phase 1: Data Preparation (1 week)
1. Query PIT store for exposure sequences (min 90 days, daily snapshots)
2. Construct temporal graph dataset: `(adjacency_sequence, features, labels)`
3. Define prediction task: `P(bank_i stress at t+7 | history up to t)`
4. Create train/val/test splits by time (strict temporal ordering)

### Phase 2: Baseline Models (1 week)
1. **Static GCN baseline**: Train on single-time snapshot (current approach)
2. **LSTM baseline**: Flatten adjacency matrix, feed to sequence model
3. Establish performance floor for temporal GNN comparison

### Phase 3: Temporal GNN Prototype (2 weeks)
1. Implement EvolveGCN-H (hidden state evolution)
2. Train on same task as baselines
3. Equivalence harness requirements:
   - Must beat static GCN on AUC-ROC
   - Must provide ≥3 days early warning vs static model
   - Inference latency < 2× static GCN (acceptable tradeoff)

### Phase 4: Production Integration (1 week)
1. Add TemporalGNN to model registry
2. Update prediction engine to construct temporal inputs
3. Monitoring: attention weights over time, topological feature importance

## Computational Considerations

### Training
- **Memory**: O(T × n²) for T time steps, n banks
  - Mitigation: Subsampling, sparse representations
- **Time**: 5-10× longer than static GCN
  - Mitigation: Gradient accumulation, mixed precision

### Inference
- **Latency**: Sequential processing of T snapshots
  - Mitigation: Parallel batch processing, cached hidden states
- **Freshness**: Requires T historical snapshots per prediction
  - Mitigation: Incremental updates (only newest snapshot needed after warm start)

## Risk Assessment

### Technical Risks
- **Overfitting**: Temporal models have more parameters → stricter regularization needed
- **Data hunger**: Needs longer history than static models → may underperform initially
- **Interpretability**: Harder to explain than centrality metrics → need visualization tools

### Business Value
- **Early warning**: Detect stress propagation patterns before they materialize
- **Policy testing**: Simulate intervention timing ("what if we injected liquidity at t-3?")
- **Differentiation**: Advanced capability vs competitors using static network analysis

## Recommendation

**Proceed to Phase 1 (Data Preparation)** if:
- PIT store has ≥90 days of daily exposure snapshots
- Team has PyTorch Geometric or DGL experience
- Early-warning capability is a strategic priority

**Start with simpler alternative** if:
- Historical exposure data is sparse (<30 days)
- Team lacks GNN expertise
- Regulatory explainability requirements are strict

**Simpler alternative**: Rolling-window static GCN
- Train separate GCN on recent window (e.g., last 7 days)
- Capture some temporal dynamics without full Temporal GNN complexity
- Easier to implement, debug, and explain

## Next Steps

1. Audit PIT store: count available exposure vintages, date range, completeness
2. Document findings in `/docs/temporal-gnn-data-audit.md`
3. If data sufficient: implement Phase 1 data loader
4. Schedule architecture review before Phase 3 commitment

---
*Phase 5/6 deliverable — feasibility assessment with PIT exposure vintages now available*
