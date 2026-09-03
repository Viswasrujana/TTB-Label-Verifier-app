"""
Unit tests for label comparison and government warning verification logic.
No OpenAI API calls are made — all tests operate on the pure Python functions.

Run with:
    pip install pytest
    pytest tests/
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.main import (
    ApplicationData,
    GOVERNMENT_WARNING_EXACT,
    build_verification_results,
    compare_abv,
    compare_name_field,
    compare_net_contents,
    verify_government_warning,
)


# ── Brand name comparison ─────────────────────────────────────────────────

class TestBrandName:
    def test_exact_match(self):
        match, _ = compare_name_field("Old Tom Distillery", "Old Tom Distillery")
        assert match is True

    def test_case_insensitive(self):
        # Dave's scenario: all-caps on label vs mixed-case in application
        match, notes = compare_name_field("Stone's Throw", "STONE'S THROW")
        assert match is True
        assert "case-insensitive" in notes.lower()

    def test_mismatch(self):
        match, notes = compare_name_field("Blue Ridge Whiskey", "Red River Spirits")
        assert match is False
        assert "Mismatch" in notes

    def test_empty_extracted(self):
        match, notes = compare_name_field("Old Tom", "")
        assert match is False
        assert "not found" in notes.lower()

    def test_label_contains_extra_subtext(self):
        # Label says "Old Tom Distillery - Small Batch" but app just says "Old Tom Distillery"
        match, _ = compare_name_field("Old Tom Distillery", "Old Tom Distillery - Small Batch")
        assert match is True


# ── ABV comparison ────────────────────────────────────────────────────────

class TestAlcoholContent:
    def test_exact_percentage(self):
        match, _ = compare_abv("45%", "45%")
        assert match is True

    def test_different_format_same_value(self):
        # Application says "45% Alc./Vol." label says "45% alc/vol (90 proof)"
        match, _ = compare_abv("45% Alc./Vol.", "45% alc/vol (90 proof)")
        assert match is True

    def test_mismatch_percentage(self):
        match, notes = compare_abv("40%", "45%")
        assert match is False
        assert "mismatch" in notes.lower()

    def test_tiny_float_difference_within_tolerance(self):
        # 40.0 vs 40.05 — within 0.1 tolerance
        match, _ = compare_abv("40.0%", "40.05%")
        assert match is True

    def test_significant_difference(self):
        match, _ = compare_abv("40%", "80%")
        assert match is False

    def test_missing_extracted(self):
        match, notes = compare_abv("40%", "")
        assert match is False
        assert "not found" in notes.lower()


# ── Net contents comparison ───────────────────────────────────────────────

class TestNetContents:
    def test_exact(self):
        match, _ = compare_net_contents("750 mL", "750 mL")
        assert match is True

    def test_case_ml(self):
        match, _ = compare_net_contents("750 mL", "750 ml")
        assert match is True

    def test_no_space(self):
        match, _ = compare_net_contents("750 mL", "750mL")
        assert match is True

    def test_mismatch_size(self):
        match, notes = compare_net_contents("750 mL", "1000 mL")
        assert match is False

    def test_fl_oz_normalization(self):
        match, _ = compare_net_contents("750 mL", "750 milliliter")
        # milliliter normalizes to ml
        assert match is True

    def test_missing_extracted(self):
        match, _ = compare_net_contents("750 mL", "")
        assert match is False


# ── Government warning ────────────────────────────────────────────────────

class TestGovernmentWarning:
    def test_correct_warning(self):
        match, notes = verify_government_warning(GOVERNMENT_WARNING_EXACT)
        assert match is True

    def test_correct_with_extra_whitespace(self):
        # Normalize internal whitespace
        warning_extra_spaces = GOVERNMENT_WARNING_EXACT.replace("  ", "   ")
        match, _ = verify_government_warning(warning_extra_spaces)
        assert match is True

    def test_title_case_prefix_fails(self):
        # "Government Warning:" instead of "GOVERNMENT WARNING:"
        bad = GOVERNMENT_WARNING_EXACT.replace("GOVERNMENT WARNING:", "Government Warning:")
        match, notes = verify_government_warning(bad)
        assert match is False
        assert "ALL CAPS" in notes

    def test_lowercase_prefix_fails(self):
        bad = GOVERNMENT_WARNING_EXACT.replace("GOVERNMENT WARNING:", "government warning:")
        match, notes = verify_government_warning(bad)
        assert match is False

    def test_missing_warning(self):
        match, notes = verify_government_warning(None)
        assert match is False
        assert "not found" in notes.lower()

    def test_empty_string(self):
        match, notes = verify_government_warning("")
        assert match is False

    def test_truncated_warning(self):
        truncated = "GOVERNMENT WARNING: (1) According to the Surgeon General"
        match, notes = verify_government_warning(truncated)
        assert match is False

    def test_warning_embedded_in_surrounding_text(self):
        # Label has extra text before/after the warning
        surrounded = "Please drink responsibly. " + GOVERNMENT_WARNING_EXACT + " Not for resale."
        match, _ = verify_government_warning(surrounded)
        assert match is True


# ── Full build_verification_results ──────────────────────────────────────

class TestBuildVerificationResults:
    def _app_data(self):
        return ApplicationData(
            brand_name="Old Tom Distillery",
            class_type="Kentucky Straight Bourbon Whiskey",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
        )

    def _good_extracted(self):
        return {
            "brand_name": "Old Tom Distillery",
            "class_type": "Kentucky Straight Bourbon Whiskey",
            "alcohol_content": "45% Alc./Vol. (90 Proof)",
            "net_contents": "750 mL",
            "government_warning": GOVERNMENT_WARNING_EXACT,
            "full_text": "Old Tom Distillery Kentucky Straight Bourbon Whiskey 45% 750mL",
        }

    def test_all_pass(self):
        result = build_verification_results(self._app_data(), self._good_extracted(), "label.jpg", 1200)
        assert result.overall_pass is True
        assert all(f.match for f in result.fields)

    def test_brand_name_mismatch_fails(self):
        extracted = self._good_extracted()
        extracted["brand_name"] = "Wrong Brand"
        result = build_verification_results(self._app_data(), extracted, "label.jpg", 1200)
        assert result.overall_pass is False
        brand_field = next(f for f in result.fields if f.field == "Brand Name")
        assert brand_field.match is False

    def test_bad_warning_fails_overall(self):
        extracted = self._good_extracted()
        extracted["government_warning"] = "Government Warning: (1) Some text..."
        result = build_verification_results(self._app_data(), extracted, "label.jpg", 1200)
        assert result.overall_pass is False
        warn_field = next(f for f in result.fields if f.field == "Government Warning")
        assert warn_field.match is False

    def test_missing_warning_fails(self):
        extracted = self._good_extracted()
        extracted["government_warning"] = None
        result = build_verification_results(self._app_data(), extracted, "label.jpg", 1200)
        assert result.overall_pass is False

    def test_filename_preserved(self):
        result = build_verification_results(self._app_data(), self._good_extracted(), "my_label.png", 800)
        assert result.filename == "my_label.png"

    def test_processing_time_preserved(self):
        result = build_verification_results(self._app_data(), self._good_extracted(), "x.jpg", 4321)
        assert result.processing_time_ms == 4321

    def test_optional_bottler_included_when_provided(self):
        app = ApplicationData(
            brand_name="Old Tom Distillery",
            class_type="Kentucky Straight Bourbon Whiskey",
            alcohol_content="45% Alc./Vol.",
            net_contents="750 mL",
            bottler_name="Old Tom Distilling Co.",
        )
        extracted = self._good_extracted()
        extracted["bottler_name"] = "Old Tom Distilling Co."
        result = build_verification_results(app, extracted, "x.jpg", 1000)
        field_names = [f.field for f in result.fields]
        assert "Bottler Name" in field_names

    def test_optional_bottler_omitted_when_not_in_app(self):
        result = build_verification_results(self._app_data(), self._good_extracted(), "x.jpg", 1000)
        field_names = [f.field for f in result.fields]
        assert "Bottler Name" not in field_names
