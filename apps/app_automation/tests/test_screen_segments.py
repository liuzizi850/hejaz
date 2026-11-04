from apps.app_automation.runners.event_chain_runner import segment_count

def test_segment_count_splits_at_180_seconds():
    assert segment_count(0) == 0
    assert segment_count(1) == 1
    assert segment_count(180) == 1
    assert segment_count(181) == 2
    assert segment_count(360) == 2
