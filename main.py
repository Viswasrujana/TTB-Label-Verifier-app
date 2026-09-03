"""
TTB Alcohol Label Verification API
Receives label images, calls the AI vision service to read text,
then compares extracted fields against the submitted application data.
"""

import asyncio
import base64
import json
import os
import re
import time
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="TTB Label Verifier", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# ── Configuration ─────────────────────────────────────────────────────────────

# The exact government health warning required on every US alcohol label.
GOVERNMENT_WARNING_EXACT = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, "
    "women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, "
    "and may cause health problems."
)

GENAI_API_URL = os.environ.get("GENAI_API_URL", "https://api.openai.com/v1/chat/completions")
GENAI_MODEL   = os.environ.get("GENAI_MODEL",   "gpt-4o-mini")


# ── Data shapes ───────────────────────────────────────────────────────────────

class ApplicationData(BaseModel):
    """Fields submitted by the applicant on the COLA application form."""
    brand_name: str
    class_type: str
    alcohol_content: str
    net_contents: str
    bottler_name: Optional[str] = None
    country_of_origin: Optional[str] = None


class FieldResult(BaseModel):
    """Pass/fail result for a single label field."""
    field: str
    expected: Optional[str]
    extracted: Optional[str]
    match: bool
    notes: str


class VerificationResult(BaseModel):
    """Complete verification result returned to the caller."""
    filename: str
    overall_pass: bool
    processing_time_ms: int
    fields: list[FieldResult]
    raw_extracted_text: Optional[str] = None
    error: Optional[str] = None


class VerifyRequest(BaseModel):
    """Request body for single-label verification."""
    filename: str
    image_b64: str
    brand_name: str
    class_type: str
    alcohol_content: str
    net_contents: str
    bottler_name: Optional[str] = None
    country_of_origin: Optional[str] = None


class BatchVerifyRequest(BaseModel):
    """Request body for batch verification."""
    items: list[VerifyRequest]


# ── AI Vision call ────────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are an OCR assistant for alcohol beverage label compliance review.

Analyze this label image and extract the following fields. Return ONLY valid JSON with exactly these keys:
{
  "brand_name": "...",
  "class_type": "...",
  "alcohol_content": "...",
  "net_contents": "...",
  "bottler_name": "...",
  "country_of_origin": "...",
  "government_warning": "...",
  "full_text": "..."
}

Rules:
- Extract the government warning statement verbatim — copy it character-for-character from the label.
- If a field is not visible or not present, use null.
- "full_text" should contain all readable text from the label concatenated.
- Do not interpret or paraphrase — extract exactly what is printed.
"""


async def extract_label_fields(image_bytes: bytes, filename: str) -> dict:
    """
    Send the label image to the AI vision service.
    Returns a dict with the extracted field values.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not set. Add it to your .env file or Streamlit secrets.",
        )

    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    # Detect image format from the first few bytes
    if image_bytes[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "image/jpeg"

    request_body = {
        "model": GENAI_MODEL,
        "max_tokens": 1024,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACTION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{b64_image}",
                        },
                    },
                ],
            }
        ],
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            GENAI_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"AI service error {response.status_code}: {response.text[:300]}",
        )

    content = response.json()["choices"][0]["message"]["content"]
    # Strip markdown code fences if the AI wraps its response in them
    content = re.sub(r"^```(?:json)?\s*", "", content.strip())
    content = re.sub(r"\s*```$", "", content.strip())

    return json.loads(content)


# ── Field comparison logic ────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Collapse extra whitespace and trim edges."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def compare_name_field(expected: str, extracted: str) -> tuple[bool, str]:
    """
    Compare brand names case-insensitively.
    'STONE'S THROW' and 'Stone's Throw' are treated as the same.
    Also passes if the label includes extra sub-brand text alongside the name.
    """
    if not extracted:
        return False, "Field not found on label"
    norm_exp = normalize(expected).lower()
    norm_ext = normalize(extracted).lower()
    if norm_exp == norm_ext:
        return True, "Exact match (case-insensitive)"
    if norm_exp in norm_ext or norm_ext in norm_exp:
        return True, "Match (label may include additional text)"
    return False, f"Mismatch: expected '{expected}', found '{extracted}'"


def compare_abv(expected: str, extracted: str) -> tuple[bool, str]:
    """
    Compare alcohol content by extracting just the number.
    '45% Alc./Vol.' and '45% alc/vol (90 proof)' both contain 45 — they match.
    Allows up to 0.1% difference to handle rounding.
    """
    if not extracted:
        return False, "Field not found on label"

    def extract_pct(s: str) -> Optional[float]:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
        return float(m.group(1)) if m else None

    exp_pct = extract_pct(expected)
    ext_pct = extract_pct(extracted)

    if exp_pct is not None and ext_pct is not None:
        if abs(exp_pct - ext_pct) < 0.1:
            return True, f"ABV match ({ext_pct}%)"
        return False, f"ABV mismatch: expected {exp_pct}%, found {ext_pct}%"

    if normalize(expected).lower() == normalize(extracted).lower():
        return True, "Exact match"
    return False, f"Mismatch: expected '{expected}', found '{extracted}'"


def compare_net_contents(expected: str, extracted: str) -> tuple[bool, str]:
    """
    Compare net contents with unit normalization.
    '750 mL', '750 ml', '750mL', '750 milliliter' all compare as equal.
    """
    if not extracted:
        return False, "Field not found on label"

    def normalize_volume(s: str) -> str:
        s = s.lower().strip()
        s = re.sub(r"\s+", " ", s)
        s = s.replace("milliliter", "ml").replace("millilitre", "ml")
        s = s.replace("fl. oz.", "fl oz").replace("fl.oz.", "fl oz").replace("fl oz.", "fl oz")
        s = re.sub(r"(\d)\s+(ml|fl oz|l\b|oz)", r"\1\2", s)
        return s

    if normalize_volume(expected) == normalize_volume(extracted):
        return True, "Match"
    if normalize(expected).lower() in normalize(extracted).lower():
        return True, "Match (label contains additional packaging info)"
    return False, f"Mismatch: expected '{expected}', found '{extracted}'"


def compare_generic_field(field_name: str, expected: str, extracted: str) -> tuple[bool, str]:
    """Case-insensitive comparison for class/type, bottler name, country of origin."""
    if not extracted:
        return False, "Field not found on label"
    if normalize(expected).lower() == normalize(extracted).lower():
        return True, "Exact match"
    if normalize(expected).lower() in normalize(extracted).lower():
        return True, "Match (label contains additional text)"
    return False, f"Mismatch: expected '{expected}', found '{extracted}'"


def verify_government_warning(extracted_warning: Optional[str]) -> tuple[bool, str]:
    """
    Verify the mandatory government health warning statement.

    Three rules must all be satisfied:
      1. The warning must be present on the label.
      2. 'GOVERNMENT WARNING:' must appear in ALL CAPS.
      3. The full text must match the standard TTB wording word-for-word
         (whitespace differences are ignored).
    """
    if not extracted_warning:
        return False, "Government warning statement not found on label"

    norm_extracted = normalize(extracted_warning)
    norm_expected  = normalize(GOVERNMENT_WARNING_EXACT)

    has_allcaps = "GOVERNMENT WARNING:" in norm_extracted
    has_any     = bool(re.search(r"government warning:", norm_extracted, re.IGNORECASE))

    if not has_any:
        return False, "FAIL: Government warning statement not found on label"

    if not has_allcaps:
        return (
            False,
            "FAIL: 'GOVERNMENT WARNING:' must be in ALL CAPS. "
            f"Found: '{norm_extracted[:60]}...'",
        )

    if norm_extracted == norm_expected:
        return True, "Government warning present and correct"
    if norm_expected in norm_extracted:
        return True, "Government warning present and correct (embedded in surrounding text)"

    return (
        False,
        f"Government warning text does not match required wording. "
        f"Extracted: '{norm_extracted[:120]}...'",
    )


# ── Result builder ────────────────────────────────────────────────────────────

def build_verification_results(
    app_data: ApplicationData,
    extracted: dict,
    filename: str,
    processing_time_ms: int,
) -> VerificationResult:
    """
    Compare every field from the application form against what the AI read off the label.
    Returns a VerificationResult with a pass/fail per field and an overall verdict.
    """
    fields: list[FieldResult] = []

    match, notes = compare_name_field(app_data.brand_name, extracted.get("brand_name") or "")
    fields.append(FieldResult(field="Brand Name", expected=app_data.brand_name,
                              extracted=extracted.get("brand_name"), match=match, notes=notes))

    match, notes = compare_generic_field("class_type", app_data.class_type, extracted.get("class_type") or "")
    fields.append(FieldResult(field="Class/Type", expected=app_data.class_type,
                              extracted=extracted.get("class_type"), match=match, notes=notes))

    match, notes = compare_abv(app_data.alcohol_content, extracted.get("alcohol_content") or "")
    fields.append(FieldResult(field="Alcohol Content", expected=app_data.alcohol_content,
                              extracted=extracted.get("alcohol_content"), match=match, notes=notes))

    match, notes = compare_net_contents(app_data.net_contents, extracted.get("net_contents") or "")
    fields.append(FieldResult(field="Net Contents", expected=app_data.net_contents,
                              extracted=extracted.get("net_contents"), match=match, notes=notes))

    match, notes = verify_government_warning(extracted.get("government_warning"))
    fields.append(FieldResult(field="Government Warning",
                              expected="[Standard TTB government warning]",
                              extracted=extracted.get("government_warning"), match=match, notes=notes))

    if app_data.bottler_name:
        match, notes = compare_generic_field("bottler_name", app_data.bottler_name, extracted.get("bottler_name") or "")
        fields.append(FieldResult(field="Bottler Name", expected=app_data.bottler_name,
                                  extracted=extracted.get("bottler_name"), match=match, notes=notes))

    if app_data.country_of_origin:
        match, notes = compare_generic_field("country_of_origin", app_data.country_of_origin, extracted.get("country_of_origin") or "")
        fields.append(FieldResult(field="Country of Origin", expected=app_data.country_of_origin,
                                  extracted=extracted.get("country_of_origin"), match=match, notes=notes))

    return VerificationResult(
        filename=filename,
        overall_pass=all(f.match for f in fields),
        processing_time_ms=processing_time_ms,
        fields=fields,
        raw_extracted_text=extracted.get("full_text"),
    )


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/verify", response_model=VerificationResult)
async def verify_single_label(req: VerifyRequest):
    """
    Verify one label image against application form data.
    The image is sent as a base64 string inside a JSON body.
    """
    start = time.monotonic()

    try:
        image_bytes = base64.b64decode(req.image_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="image_b64 is not valid base64")

    if len(image_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large (max 20 MB)")

    app_data = ApplicationData(
        brand_name=req.brand_name,
        class_type=req.class_type,
        alcohol_content=req.alcohol_content,
        net_contents=req.net_contents,
        bottler_name=req.bottler_name or None,
        country_of_origin=req.country_of_origin or None,
    )

    try:
        extracted = await extract_label_fields(image_bytes, req.filename)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"Could not parse AI response as JSON: {e}")

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return build_verification_results(app_data, extracted, req.filename, elapsed_ms)


@app.post("/api/verify-batch")
async def verify_batch(req: BatchVerifyRequest):
    """
    Verify up to 300 labels at once. All labels are sent to the AI service
    concurrently so the total wait time is roughly equal to one label, not 300.
    """
    if len(req.items) > 300:
        raise HTTPException(status_code=400, detail="Maximum 300 labels per batch")

    async def process_one(item: VerifyRequest) -> VerificationResult:
        start = time.monotonic()
        try:
            image_bytes = base64.b64decode(item.image_b64)
        except Exception:
            return VerificationResult(filename=item.filename, overall_pass=False,
                                      processing_time_ms=0, fields=[], error="Invalid base64 image data")
        app_data = ApplicationData(
            brand_name=item.brand_name, class_type=item.class_type,
            alcohol_content=item.alcohol_content, net_contents=item.net_contents,
            bottler_name=item.bottler_name or None, country_of_origin=item.country_of_origin or None,
        )
        try:
            extracted = await extract_label_fields(image_bytes, item.filename)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return build_verification_results(app_data, extracted, item.filename, elapsed_ms)
        except Exception as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return VerificationResult(filename=item.filename, overall_pass=False,
                                      processing_time_ms=elapsed_ms, fields=[], error=str(e))

    results = await asyncio.gather(*[process_one(item) for item in req.items])
    total_pass = sum(1 for r in results if r.overall_pass)
    return {"total": len(results), "passed": total_pass,
            "failed": len(results) - total_pass, "results": results}


@app.get("/api/health")
async def health():
    """Quick check that the service is up and the AI token is configured."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    return {"status": "ok", "ai_configured": bool(api_key)}
