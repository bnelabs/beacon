# Mixture-of-Experts (MoE) Feasibility Memo

## Context
Phase 5/6 parked feature: MoE architecture for regime-aware prediction blending.

## Prerequisite Now Available
**Labelled regime history** — the platform now produces regime labels on every prediction pass via:
- `backend.modules.engine.hidden_markov` (HMM-based regime detection)
- `backend.modules.engine.prediction_engine` (regime-annotated predictions)
- Persistence in prediction store with `regime_label` field

## MoE Architecture Proposal

### Expert Specialization by Regime
Each expert model specializes in one market regime:
1. **Calm Expert**: Low volatility, trend-following patterns
2. **Stress Expert**: High volatility, flight-to-quality dynamics  
3. **Transition Expert**: Regime-switching periods, elevated uncertainty
4. **Crisis Expert**: Extreme tail events, correlation breakdown

### Gating Mechanism
Current HMM posterior probabilities → soft gating weights:
```python
# P(regime_t | history) from HMM becomes gate weights
gate_weights = hmm.posterior_probs  # shape: (n_regimes,)
prediction = sum(w_i * expert_i(x) for i, w_i in enumerate(gate_weights))
```

### Training Strategy
**Option A: Retrospective labelling** (recommended)
1. Backfill regime labels on historical predictions (already available)
2. Train each expert on regime-filtered training data
3. Validate out-of-sample by regime

**Option B: Joint training**
1. End-to-end MoE with HMM gate frozen
2. Experts learn regime-specific residuals
3. More complex, harder to debug

## Data Requirements

### Current State ✅
- Regime labels produced per-prediction
- Historical predictions stored with regime context
- Model registry tracks performance by regime

### Missing Pieces ⚠️
- Expert model checkpoints (one per regime)
- Gating combiner module
- MoE evaluation harness (by-regime metrics)

## Implementation Phases

### Phase 1: Evidence Gathering (1 week)
1. Query prediction store for regime distribution
2. Analyze per-regime prediction error (existing models)
3. Quantify regime-specific error patterns
4. Decision gate: does MoE promise exceed complexity cost?

### Phase 2: Prototype (2 weeks)
1. Train 3 regime-specialized experts (simple architectures first)
2. Implement HMM-probability gating
3. Backtest vs single-model baseline
4. Equivalence harness: MoE should beat baseline in ≥2 regimes without losing in others

### Phase 3: Production Integration (1 week)
1. Add MoE option to model registry
2. Update prediction engine to route through MoE when selected
3. Monitoring dashboard: gate weights over time, expert contributions

## Complexity Assessment

### Benefits
- **Interpretability**: "Model is 70% Stress Expert, 30% Transition Expert"
- **Adaptivity**: Automatic regime-weighted blending
- **Performance**: Potential improvement in high-stress regimes where single models struggle

### Costs
- **Training overhead**: 3-4× more model training compute
- **Inference latency**: Multiple forward passes (mitigated by parallel execution)
- **Operational complexity**: More checkpoints, version combinations
- **Debugging surface**: Which expert failed? Was it the gate or the expert?

## Recommendation

**Proceed to Phase 1 (Evidence Gathering)** if:
- Per-regime error analysis shows >15% variance in MAE/RMSE across regimes
- Stress regime has worst performance (highest business value to improve)
- Team capacity allows 1-week investigation sprint

**Defer indefinitely** if:
- Single-model baseline already achieves consistent error across regimes
- Operational complexity exceeds team's risk tolerance
- Regulatory scrutiny of "blended" predictions is a concern

## Next Steps

1. Run regime-stratified error analysis on last 90 days predictions
2. Document findings in `/docs/moe-evidence.md`
3. Schedule go/no-go decision meeting

---
*Phase 5/6 deliverable — feasibility assessment with labelled regime history now available*
