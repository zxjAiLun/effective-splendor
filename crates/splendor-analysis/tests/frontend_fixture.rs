use splendor_analysis::AnalysisTraceV1;

#[test]
fn frontend_golden_is_a_rust_valid_analysis_trace() {
    let bytes =
        include_str!("../../../apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json");
    let trace: AnalysisTraceV1 = serde_json::from_str(bytes).expect("strict Rust fixture parse");
    trace.validate().expect("Rust fixture validation");
    assert_eq!(trace.frames.len(), 1);
    assert_eq!(trace.catalog.cards.len(), splendor_catalog::CARD_COUNT);
    assert_eq!(trace.catalog.nobles.len(), splendor_catalog::NOBLE_COUNT);
}
