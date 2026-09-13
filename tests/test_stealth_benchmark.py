"""Tests — Empirical Anti-Bot Stealth Benchmark Suite."""
import pytest
from ironcore.browser.benchmark import (
    evaluate_heuristic_vectors,
    run_synthetic_benchmark,
    StealthBenchmarkReport,
)


def test_synthetic_stealth_benchmark_metrics():
    report = run_synthetic_benchmark()
    assert isinstance(report, StealthBenchmarkReport)
    assert report.vectors_tested == 6
    # Vanilla should be detected across vectors (evasion rate 0%)
    assert report.vanilla_detections == 6
    assert report.vanilla_evasion_rate_pct == 0.0

    # IronCore spoofed should evade all detection vectors (evasion rate 100%)
    assert report.spoofed_detections == 0
    assert report.spoofed_evasion_rate_pct == 100.0

    # Summary table must render correctly
    summary = report.summary_table()
    assert "RFC-BOT-HEURISTIC-V1" in summary
    assert "100.0%" in summary
    assert "PASS ✅" in summary


def test_custom_evasion_computation():
    vanilla = {
        "webdriver": True,
        "webgl_renderer": "Mesa OffScreen",
        "canvas_noise_detected": False,
        "audio_noise_detected": False,
        "has_chrome_object": False,
        "device_memory": 0,
    }
    partial_spoofed = {
        "webdriver": None,
        "webgl_renderer": "NVIDIA GeForce RTX 4090",
        "canvas_noise_detected": True,
        "audio_noise_detected": False,  # un-spoofed audio
        "has_chrome_object": True,
        "device_memory": 16,
    }
    report = evaluate_heuristic_vectors(vanilla, partial_spoofed)
    assert report.vectors_tested == 6
    assert report.vanilla_detections == 6
    assert report.spoofed_detections == 1  # only audio was caught
    assert report.spoofed_evasion_rate_pct == 83.3
