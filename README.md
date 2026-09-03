# TTB Label Verifier

An AI-powered prototype for the US Treasury's Alcohol and Tobacco Tax and Trade Bureau (TTB) that automates alcohol beverage label compliance review.

Upload a label image and application form data. The app reads the label using AI, compares every field against the application, and returns a clear pass or fail result — in seconds.

**Live app:** http://localhost:8000

---

## What Was Built (Plain English)

Before diving into files and code, here is what actually exists and what role each piece plays.

### You built ONE service

There is a single Python program (`backend/main.py`) that does everything:

```
┌─────────────────────────────────────────────────────────┐
│              YOUR ONE PYTHON SERVICE                    │
│                  (backend/main.py)                      │
│                                                         │
│  1. Serves the web page (frontend/index.html)           │
│  2. Receives the uploaded label image + form data       │
│  3. Calls the external AI to read the label image       │
│  4. Runs the comparison rules (brand, ABV, warning...)  │
│  5. Returns the pass/fail result as JSON                │
└─────────────────────────────────────────────────────────┘
```

### What FastAPI is

FastAPI is a Python library — not a separate service. Think of it the same way you would think of Spring Boot in Java. It gives the Python program the ability to listen for HTTP requests on port 8000, parse JSON bodies, and return JSON responses. Without it you would have to write all of that yourself.

### What the AI Vision Service is

The AI (`genai-api.visa.com`) is an **external** service that you call — you did not build it. Your Python program sends the label image to it and receives back a JSON object with the text it read off the label. That is the only thing the external AI does. All the actual compliance checking (does the brand name match? is the government warning word-for-word correct?) is done by your Python code, not the AI.

### What the frontend is

`frontend/index.html` is a single HTML file. It is not a service. It is served by your Python program when someone opens a browser. It contains the form, the drag-and-drop upload zone, and the JavaScript that sends requests to your Python service and displays the results.

---

## How It All Fits Together (Sequence Diagram)

This shows exactly what happens from the moment a reviewer clicks "Verify Label" to seeing the result on screen.

```
┌──────────────┐      ┌──────────────────────────────────────┐      ┌──────────────────┐
│   Browser    │      │     YOUR PYTHON SERVICE              │      │  External AI     │
│  (Reviewer)  │      │       backend/main.py                │      │  Vision Service  │
└──────┬───────┘      └────────────────┬─────────────────────┘      └────────┬─────────┘
       │                               │                                      │
       │  Opens http://localhost:8000  │                                      │
       │ ─────────────────────────────>│                                      │
       │<─ Sends back index.html ──────│                                      │
       │   (the web page)              │                                      │
       │                               │                                      │
       │  Reviewer fills in the form:  │                                      │
       │  Brand Name, ABV, Volume etc  │                                      │
       │  and picks a label image file │                                      │
       │                               │                                      │
       │  Clicks "Verify Label"        │                                      │
       │  (browser converts image to   │                                      │
       │   base64 text automatically)  │                                      │
       │                               │                                      │
       │ ── POST /api/verify ─────────>│                                      │
       │   {                           │                                      │
       │     image_b64: "...",         │                                      │
       │     brand_name: "...",        │                                      │
       │     alcohol_content: "...",   │                                      │
       │     ...                       │                                      │
       │   }                           │                                      │
       │                               │                                      │
       │                               │  POST /v1/chat/completions           │
       │                               │  "Here is a label image.            │
       │                               │   Extract all fields as JSON"       │
       │                               │ ────────────────────────────────────>│
       │                               │                                      │
       │                               │                                      │  AI reads the
       │                               │                                      │  image, returns:
       │                               │                                      │  {
       │                               │                                      │    brand_name:
       │                               │                                      │    "EAGLE RIDGE",
       │                               │                                      │    alcohol_content:
       │                               │                                      │    "45% ALC./VOL",
       │                               │                                      │    government_warning:
       │                               │                                      │    "GOVERNMENT WARNING:
       │                               │                                      │     ..."
       │                               │                                      │  }
       │                               │<────────────────────────────────────
       │                               │                                      │
       │                               │  Python comparison rules run:        │
       │                               │  ┌─────────────────────────────┐    │
       │                               │  │ Brand:   case-insensitive   │    │
       │                               │  │ ABV:     extract number %   │    │
       │                               │  │ Volume:  normalize units    │    │
       │                               │  │ Warning: ALL CAPS required  │    │
       │                               │  │          + exact wording    │    │
       │                               │  └─────────────────────────────┘    │
       │                               │                                      │
       │<── JSON result ───────────────│                                      │
       │  {                            │                                      │
       │    overall_pass: true/false,  │                                      │
       │    fields: [                  │                                      │
       │      { field: "Brand Name",   │                                      │
       │        match: true,           │                                      │
       │        expected: "...",       │                                      │
       │        extracted: "..." },    │                                      │
       │      ...                      │                                      │
       │    ]                          │                                      │
       │  }                            │                                      │
       │                               │                                      │
       │  Browser renders the table:   │                                      │
       │  GREEN = APPROVED             │                                      │
       │  RED   = REJECTED             │                                      │
```

**For batch uploads (200–300 labels):** the Python service fires all AI calls at the same time using `asyncio.gather()`. Instead of waiting 5 seconds × 300 labels = 25 minutes, it waits roughly 5 seconds total because all requests run in parallel.

---

## Project Files Explained

```
ttb-label-verifier/
│
├── backend/
│   └── main.py              ← THE ENTIRE BACKEND (one file, ~450 lines)
│                              Contains everything:
│                              - Web server setup (FastAPI)
│                              - API endpoints (/api/verify, /api/verify-batch)
│                              - AI vision call (extract_label_fields)
│                              - All comparison rules (brand, ABV, volume, warning)
│                              - Result builder
│
├── frontend/
│   └── index.html           ← THE ENTIRE FRONTEND (one file)
│                              Contains everything:
│                              - The web page layout and styling
│                              - The form (brand name, ABV, volume, etc.)
│                              - Drag-and-drop image upload
│                              - JavaScript that sends requests and shows results
│
├── tests/
│   └── test_verification.py ← 30 unit tests for the comparison rules
│                              No AI calls made — pure logic tests
│
├── eagle_ridge_bourbon_label.png  ← Sample test label image
│
├── requirements.txt         ← Python packages needed to run the backend
├── .env.example             ← Template for setting the AI service token
├── Dockerfile               ← Instructions to package the app in a container
├── docker-compose.yml       ← One-command local setup
└── README.md                ← This file
```

---

## What the Python Service Does (Inside main.py)

### Step 1 — Receive the request

The Python service listens on port 8000. When a reviewer submits a label, it receives a JSON body containing the image (as base64 text) and all the form fields.

### Step 2 — Send image to AI (`extract_label_fields`)

The image bytes are sent to the external AI Vision service with a prompt:

> "You are an OCR assistant. Extract brand name, class/type, alcohol content, net contents, bottler name, country of origin, government warning, and all full text. Return ONLY valid JSON."

The AI returns a JSON object with whatever it could read from the label.

### Step 3 — Compare fields (`build_verification_results`)

Five comparison functions run against the AI's extracted values:

| Function | What it checks | How |
|---|---|---|
| `compare_name_field` | Brand name | Case-insensitive. `"EAGLE RIDGE"` = `"Eagle Ridge"`. Also passes if one contains the other. |
| `compare_abv` | Alcohol content | Pulls just the number using regex. `"45% Alc./Vol."` and `"45% alc/vol (90 proof)"` both contain `45` — they match. Tolerance: ±0.1%. |
| `compare_net_contents` | Volume | Normalizes units first: `ml`, `mL`, `ML`, `milliliter` all become the same before comparing. |
| `compare_generic_field` | Class/type, bottler, country | Case-insensitive, with containment check for extra label text. |
| `verify_government_warning` | Mandatory health warning | Three rules: (1) warning must exist, (2) `GOVERNMENT WARNING:` must be in ALL CAPS, (3) full text must match the exact TTB wording word-for-word. |

### Step 4 — Return result

The service returns a JSON response with:
- `overall_pass` — true only if every field passed
- `fields` — one entry per field with expected value, extracted value, pass/fail, and a plain-English explanation
- `processing_time_ms` — how long it took in milliseconds
- `raw_extracted_text` — everything the AI read off the label

---

## The Government Warning Check (Most Important Rule)

Every US alcohol label must carry the exact government health warning, word for word. The check is strict by design:

**Required text (verbatim):**
```
GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink
alcoholic beverages during pregnancy because of the risk of birth defects.
(2) Consumption of alcoholic beverages impairs your ability to drive a car or
operate machinery, and may cause health problems.
```

**Rules enforced:**
- `GOVERNMENT WARNING:` must be in ALL CAPS — title case (`Government Warning:`) fails
- The full body text must match word-for-word (whitespace differences are ignored)
- The warning may appear embedded in other text — that still passes
- Missing or truncated text fails

---

## Sample Test Label

The file `eagle_ridge_bourbon_label.png` in this folder is a ready-made test image. Use it to try the app immediately.

**Form values to use with it:**

| Field | Value |
|---|---|
| Brand Name | `EAGLE RIDGE DISTILLERY` |
| Class / Type | `Kentucky Straight Bourbon Whiskey` |
| Alcohol Content | `45% Alc./Vol.` |
| Net Contents | `750 mL` |
| Bottler Name | `Eagle Ridge Distilling Co.` |
| Country of Origin | `USA` |

---

## Running the App

### Prerequisites
- Python 3.11 or higher
- An OpenAI API key — get one at https://platform.openai.com/api-keys

### Start

```bash
cd ttb-label-verifier

# Add your OpenAI key to .env
cp .env.example .env
# Open .env and set: OPENAI_API_KEY=sk-...

# Load the key and start the service
export $(cat .env | xargs)
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000**

### Or with Docker

```bash
cp .env.example .env
# Open .env and set: OPENAI_API_KEY=sk-...

docker compose up --build
```

---

## Running the Tests

The tests check all comparison rules without making any AI calls.

```bash
pytest tests/ -v
```

All 30 tests pass. They cover:
- Brand name: exact, case-insensitive, mismatch, containment
- ABV: format variants, numeric tolerance, mismatch
- Volume: unit normalization (mL/ml/milliliter)
- Government warning: exact match, all-caps enforcement, title case rejection, truncated text rejection, embedded text pass

---

## Assumptions and Known Limitations

| Item | Detail |
|---|---|
| No COLA integration | Standalone prototype. Connecting to the real COLA system was explicitly out of scope (per Marcus Williams interview). |
| No login / authentication | Prototype only. Production deployment would need auth. |
| No data storage | Results are returned in memory only. Nothing is saved to a database. |
| SSL verification | Disabled for local development (`verify=False` in httpx) because the Zscaler certificate chain is not fully trusted by the Python HTTP client. A production deployment would use the correct CA bundle. |
| AI service dependency | If `genai-api.visa.com` is unavailable, the service returns a 502 error. There is no offline fallback. |
| Batch speed | 300 labels run concurrently. Wall-clock time is roughly the same as one label, not 300× longer. Rate limits on the AI service are the only constraint. |
| Government warning wording | The exact TTB text is hardcoded. If TTB ever updates the official wording, `GOVERNMENT_WARNING_EXACT` in `main.py` must be updated to match. |

---

## What "AI Vision" Means Here

The AI is used purely for **reading text off an image** (OCR — Optical Character Recognition). It is not making any compliance decisions. It just returns what it sees on the label as structured JSON.

All compliance decisions — does the brand name match, is the ABV correct, is the government warning exactly right — are made by plain Python rules that you can read, audit, and change at any time.

This separation is intentional: AI is good at reading messy, imperfect images. Python rules are good at being precise, auditable, and consistent. Each does what it is best at.
