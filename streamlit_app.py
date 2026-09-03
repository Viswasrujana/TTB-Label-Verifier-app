"""
TTB Label Verifier — Streamlit UI
Wraps backend/main.py comparison logic directly (no HTTP roundtrip).
"""

import asyncio
import json
import os
import sys
import time

import streamlit as st
from PIL import Image

# ── Inject OpenAI key from Streamlit Secrets (Streamlit Cloud) or env var ──
if "OPENAI_API_KEY" in st.secrets:
    os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]
if "GENAI_API_URL" in st.secrets:
    os.environ["GENAI_API_URL"] = st.secrets["GENAI_API_URL"]
if "GENAI_MODEL" in st.secrets:
    os.environ["GENAI_MODEL"] = st.secrets["GENAI_MODEL"]

# ── Pull in the comparison logic from the backend directly ─────────────────
sys.path.insert(0, os.path.dirname(__file__))
from backend.main import (
    ApplicationData,
    extract_label_fields,
    build_verification_results,
)

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TTB Label Verifier",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Header banner */
    .ttb-header {
        background: #1a3a5c;
        color: white;
        padding: 18px 28px;
        border-radius: 10px;
        margin-bottom: 28px;
        display: flex;
        align-items: center;
        gap: 14px;
    }
    .ttb-header h1 { font-size: 1.5rem; margin: 0; font-weight: 700; }
    .ttb-header p  { font-size: 0.85rem; opacity: 0.8; margin: 4px 0 0; }

    /* Result cards */
    .result-pass {
        background: #e8f5e9;
        border-left: 6px solid #2e7d32;
        border-radius: 8px;
        padding: 14px 18px;
        margin-bottom: 10px;
    }
    .result-fail {
        background: #fce4ec;
        border-left: 6px solid #c62828;
        border-radius: 8px;
        padding: 14px 18px;
        margin-bottom: 10px;
    }
    .verdict-pass { color: #1b5e20; font-size: 1.3rem; font-weight: 800; }
    .verdict-fail { color: #880e4f; font-size: 1.3rem; font-weight: 800; }

    /* Batch summary */
    .batch-stat {
        background: #1a3a5c;
        color: white;
        border-radius: 10px;
        padding: 18px;
        text-align: center;
    }
    .batch-stat .num { font-size: 2.2rem; font-weight: 800; }
    .batch-stat .lbl { font-size: 0.75rem; opacity: 0.75; text-transform: uppercase; letter-spacing: 0.05em; }

    /* Section divider */
    .section-title {
        font-size: 0.85rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #1a3a5c;
        border-bottom: 2px solid #dce3ed;
        padding-bottom: 6px;
        margin: 6px 0 16px;
    }

    /* hide streamlit default header padding */
    .block-container { padding-top: 1.5rem; }

    /* make file uploader look cleaner */
    [data-testid="stFileUploader"] { border: 2px dashed #a0b0c8; border-radius: 8px; padding: 8px; }
</style>
""", unsafe_allow_html=True)

# ── Header ─────────────────────────────────────────────────────────────────
st.markdown("""
<div class="ttb-header">
  <div style="font-size:2.2rem">🏛️</div>
  <div>
    <h1>TTB Label Verifier</h1>
    <p>Alcohol &amp; Tobacco Tax and Trade Bureau — AI-Powered Label Compliance Tool</p>
  </div>
</div>
""", unsafe_allow_html=True)


# ── Helper: run async function from sync Streamlit context ─────────────────
def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ── Helper: render a single verification result ────────────────────────────
def render_result(result, show_filename: bool = False):
    is_pass = result.overall_pass
    verdict = "✅ APPROVED" if is_pass else "❌ REJECTED"
    css_cls = "result-pass" if is_pass else "result-fail"
    verdict_cls = "verdict-pass" if is_pass else "verdict-fail"

    header_text = f"{result.filename} — " if show_filename else ""
    st.markdown(
        f'<div class="{css_cls}"><span class="{verdict_cls}">{header_text}{verdict}</span>'
        f' &nbsp; <span style="font-size:0.8rem;color:#556;">{result.processing_time_ms} ms</span></div>',
        unsafe_allow_html=True,
    )

    # Build table data
    table_rows = []
    for f in result.fields:
        status = "✅ Pass" if f.match else "❌ Fail"
        table_rows.append({
            "Field": f.field,
            "Expected (Application)": f.expected or "—",
            "Found on Label": f.extracted or "—",
            "Status": status,
            "Notes": f.notes,
        })

    import pandas as pd
    df = pd.DataFrame(table_rows)

    # Color the Status column
    def color_status(val):
        if "Pass" in val:
            return "color: #2e7d32; font-weight: bold"
        return "color: #c62828; font-weight: bold"

    st.dataframe(
        df.style.applymap(color_status, subset=["Status"]),
        use_container_width=True,
        hide_index=True,
    )

    if result.raw_extracted_text:
        with st.expander("View raw extracted text from label"):
            st.code(result.raw_extracted_text, language=None)


# ── Tabs ───────────────────────────────────────────────────────────────────
tab_single, tab_batch = st.tabs(["📋 Single Label", "📁 Batch Upload"])


# ════════════════════════════════════════════════════════════════
# SINGLE LABEL TAB
# ════════════════════════════════════════════════════════════════
with tab_single:
    col_form, col_img = st.columns([1, 1], gap="large")

    with col_form:
        st.markdown('<div class="section-title">Application Form Data</div>', unsafe_allow_html=True)

        brand_name      = st.text_input("Brand Name *",        placeholder="e.g. OLD TOM DISTILLERY")
        class_type      = st.text_input("Class / Type *",       placeholder="e.g. Kentucky Straight Bourbon Whiskey")

        c1, c2 = st.columns(2)
        with c1:
            alcohol_content = st.text_input("Alcohol Content *", placeholder="e.g. 45% Alc./Vol.")
        with c2:
            net_contents    = st.text_input("Net Contents *",    placeholder="e.g. 750 mL")

        c3, c4 = st.columns(2)
        with c3:
            bottler_name    = st.text_input("Bottler Name",      placeholder="Optional")
        with c4:
            country         = st.text_input("Country of Origin", placeholder="Optional")

    with col_img:
        st.markdown('<div class="section-title">Label Image</div>', unsafe_allow_html=True)
        uploaded = st.file_uploader(
            "Upload label image (JPG, PNG, WEBP — max 20 MB)",
            type=["jpg", "jpeg", "png", "webp"],
            key="single_upload",
            label_visibility="collapsed",
        )
        if uploaded:
            img = Image.open(uploaded)
            st.image(img, caption=uploaded.name, use_container_width=True)

    st.markdown("---")
    verify_btn = st.button("🔍 Verify Label", type="primary", use_container_width=True, key="single_verify")

    if verify_btn:
        # Validation
        errors = []
        if not brand_name.strip():   errors.append("Brand Name is required.")
        if not class_type.strip():   errors.append("Class / Type is required.")
        if not alcohol_content.strip(): errors.append("Alcohol Content is required.")
        if not net_contents.strip(): errors.append("Net Contents is required.")
        if not uploaded:             errors.append("Please upload a label image.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            with st.spinner("Analyzing label image with AI… this takes about 3–5 seconds."):
                try:
                    uploaded.seek(0)
                    image_bytes = uploaded.read()

                    app_data = ApplicationData(
                        brand_name=brand_name.strip(),
                        class_type=class_type.strip(),
                        alcohol_content=alcohol_content.strip(),
                        net_contents=net_contents.strip(),
                        bottler_name=bottler_name.strip() or None,
                        country_of_origin=country.strip() or None,
                    )

                    start = time.monotonic()
                    extracted = run_async(extract_label_fields(image_bytes, uploaded.name))
                    elapsed_ms = int((time.monotonic() - start) * 1000)

                    result = build_verification_results(app_data, extracted, uploaded.name, elapsed_ms)
                    st.markdown("### Verification Result")
                    render_result(result)

                except Exception as ex:
                    st.error(f"Error: {ex}")


# ════════════════════════════════════════════════════════════════
# BATCH UPLOAD TAB
# ════════════════════════════════════════════════════════════════
with tab_batch:
    st.markdown(
        "Upload up to **300 label images** along with a JSON array of matching application data. "
        "All labels are processed in parallel.",
        unsafe_allow_html=False,
    )

    st.markdown('<div class="section-title">Label Images</div>', unsafe_allow_html=True)
    batch_files = st.file_uploader(
        "Select label images",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key="batch_upload",
        label_visibility="collapsed",
    )
    if batch_files:
        st.caption(f"{len(batch_files)} image(s) selected: {', '.join(f.name for f in batch_files[:5])}"
                   + (" …" if len(batch_files) > 5 else ""))

    st.markdown('<div class="section-title" style="margin-top:18px">Application Data (JSON array)</div>', unsafe_allow_html=True)
    st.caption("One entry per image, in the same order as the uploaded files. "
               "Fields: `brand_name`, `class_type`, `alcohol_content`, `net_contents` (required); "
               "`bottler_name`, `country_of_origin` (optional).")

    default_json = json.dumps([
        {
            "brand_name": "EAGLE RIDGE DISTILLERY",
            "class_type": "Kentucky Straight Bourbon Whiskey",
            "alcohol_content": "45% Alc./Vol.",
            "net_contents": "750 mL",
            "bottler_name": "Eagle Ridge Distilling Co.",
            "country_of_origin": "USA"
        }
    ], indent=2)

    batch_json_text = st.text_area(
        "Application JSON",
        value=default_json,
        height=220,
        label_visibility="collapsed",
    )

    batch_btn = st.button("🔍 Verify All Labels", type="primary", use_container_width=True, key="batch_verify")

    if batch_btn:
        # Validation
        if not batch_files:
            st.error("Please select at least one label image.")
        else:
            try:
                app_data_list = json.loads(batch_json_text)
                if not isinstance(app_data_list, list):
                    raise ValueError("Must be a JSON array")
            except Exception as e:
                st.error(f"Invalid JSON: {e}")
                app_data_list = None

            if app_data_list is not None:
                if len(app_data_list) != len(batch_files):
                    st.error(
                        f"JSON has {len(app_data_list)} entries but {len(batch_files)} images were uploaded. "
                        "They must match."
                    )
                elif len(batch_files) > 300:
                    st.error("Maximum 300 labels per batch.")
                else:
                    progress = st.progress(0, text="Processing labels in parallel…")

                    async def process_all():
                        async def process_one(idx, f, app_dict):
                            f.seek(0)
                            image_bytes = f.read()
                            app = ApplicationData(
                                brand_name=app_dict.get("brand_name", ""),
                                class_type=app_dict.get("class_type", ""),
                                alcohol_content=app_dict.get("alcohol_content", ""),
                                net_contents=app_dict.get("net_contents", ""),
                                bottler_name=app_dict.get("bottler_name") or None,
                                country_of_origin=app_dict.get("country_of_origin") or None,
                            )
                            start = time.monotonic()
                            try:
                                extracted = await extract_label_fields(image_bytes, f.name)
                                elapsed_ms = int((time.monotonic() - start) * 1000)
                                return build_verification_results(app, extracted, f.name, elapsed_ms)
                            except Exception as ex:
                                from backend.main import VerificationResult
                                return VerificationResult(
                                    filename=f.name, overall_pass=False,
                                    processing_time_ms=0, fields=[], error=str(ex)
                                )

                        tasks = [
                            process_one(i, batch_files[i], app_data_list[i])
                            for i in range(len(batch_files))
                        ]
                        return await asyncio.gather(*tasks)

                    with st.spinner(f"Processing {len(batch_files)} label(s) in parallel…"):
                        try:
                            results = run_async(process_all())
                            progress.progress(100, text="Done!")

                            total  = len(results)
                            passed = sum(1 for r in results if r.overall_pass)
                            failed = total - passed

                            # Summary stats
                            st.markdown("### Batch Summary")
                            s1, s2, s3 = st.columns(3)
                            with s1:
                                st.markdown(
                                    f'<div class="batch-stat"><div class="num">{total}</div><div class="lbl">Total</div></div>',
                                    unsafe_allow_html=True)
                            with s2:
                                st.markdown(
                                    f'<div class="batch-stat"><div class="num" style="color:#69f0ae">{passed}</div><div class="lbl">Passed</div></div>',
                                    unsafe_allow_html=True)
                            with s3:
                                st.markdown(
                                    f'<div class="batch-stat"><div class="num" style="color:#ff5252">{failed}</div><div class="lbl">Failed</div></div>',
                                    unsafe_allow_html=True)

                            st.markdown("---")
                            st.markdown("### Individual Results")
                            for r in results:
                                if r.error:
                                    st.error(f"❌ **{r.filename}** — Error: {r.error}")
                                else:
                                    render_result(r, show_filename=True)

                        except Exception as ex:
                            st.error(f"Batch processing error: {ex}")

# ── Footer ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "TTB Label Verifier · AI reads the label image · Python rules make compliance decisions · "
    "No data is stored · Prototype only"
)
