from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import os, json, re, time, pathlib
from dotenv import load_dotenv
from openai import OpenAI

# ── ENV / CONFIG ──────────────────────────────────────────────────────
load_dotenv()  # .env: OPENAI_API_KEY=..., OD_URL=..., OD_EMAIL=..., OD_PASS=...
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OD_URL   = os.getenv("OD_URL",   "https://greatamerican.steersman.io/web/login")
OD_EMAIL = os.getenv("OD_EMAIL", "shenry@greatamericaninc.com")
OD_PASS  = os.getenv("OD_PASS",  "Sheriloye123.")
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
SLOWMO   = int(os.getenv("SLOWMO_MS", "200"))
TEST_QUERY = os.getenv("TEST_QUERY", 'Milwaukee 0240-20 3/8" Drill')

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing in .env")

oa = OpenAI(api_key=OPENAI_API_KEY)
OUTDIR = pathlib.Path("run_artifacts"); OUTDIR.mkdir(exist_ok=True)

# ── OPENAI PROMPTS ────────────────────────────────────────────────────
def sanitize_slug(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\- ]+", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")

def gen_override_and_meta(product_name: str) -> dict:
    prompt = f"""
Return ONLY valid JSON with keys:
{{
  "override_preview_description": "",
  "override_summary_description": "",
  "override_full_description": "",
  "website_slug": "",
  "meta_title": "",
  "meta_description": ""
}}

RULES
- override_preview_description: <= 2 sentences.
- override_summary_description: 4–5 sentences.
- override_full_description: use EXACTLY this plain-text template (keep headings & asterisks):

**{product_name}**

**INCLUDES**
(1) (Item Name Here)
(1) (Item Name Here)
(1) (Item Name Here)

**PRODUCT OVERVIEW**
(Brief blurb of the product here)

**KEY FEATURES**
- (Key feature 1)
- (Key feature 2)

- meta_title: <= 60 chars; include brand/model only if natural in the name.
- meta_description: <= 155 chars; catchy and SEO-friendly.
- website_slug: lowercase, hyphenated, no special chars.
If info isn’t explicit in the name, keep it generic and factual. Only output JSON.
"""
    r = oa.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.3,
        response_format={"type":"json_object"},
        messages=[
            {"role":"system","content":"You are a precise ecommerce content assistant. Output strict JSON only."},
            {"role":"user","content":prompt},
        ],
    )
    data = json.loads(r.choices[0].message.content)
    # guardrails
    data["meta_title"] = (data.get("meta_title") or "").strip()[:60].rstrip()
    data["meta_description"] = (data.get("meta_description") or "").strip()[:155].rstrip()
    data["website_slug"] = sanitize_slug(data.get("website_slug") or product_name)
    for k in ("override_preview_description","override_summary_description","override_full_description"):
        if data.get(k): data[k] = data[k].strip()
    return data

# ── PLAYWRIGHT HELPERS ────────────────────────────────────────────────
def wait_and_click_text(page, text, tries=3):
    for _ in range(tries):
        try:
            page.get_by_text(text, exact=False).first.click(timeout=2000)
            return True
        except PWTimeout:
            pass
        page.wait_for_timeout(400)
    return False

def get_product_name(page) -> str:
    probes = [
        "h1", ".o_breadcrumb .active",
        "[name='name'] input", ".o_field_widget[name='name'] input",
        "[name='name'] .o_input",
    ]
    for css in probes:
        try:
            t = page.locator(css).first.text_content(timeout=600)
            if t and t.strip(): return t.strip()
        except:
            try:
                v = page.locator(css).first.input_value(timeout=600)
                if v and v.strip(): return v.strip()
            except: pass
    return TEST_QUERY

def get_current_text(page, el):
    try:
        # prefer value for inputs/textareas
        return el.input_value(timeout=400)
    except:
        try:
            return el.inner_text(timeout=400)
        except:
            try:
                return el.text_content(timeout=400)
            except:
                return ""

def clear_with_cmd_a(page):
    try:
        page.keyboard.press("Meta+a"); page.keyboard.press("Backspace")
    except: pass

def fill_input_or_textarea_by_label(page, label_text, new_value):
    """Idempotent fill of input/textarea following exact label."""
    if new_value is None: return False
    # input
    try:
        el = page.locator(f"//label[normalize-space(.)={json.dumps(label_text)}]/following::input[1]").first
        el.scroll_into_view_if_needed(); el.click()
        cur = get_current_text(page, el)
        if cur == new_value: return True
        clear_with_cmd_a(page); el.fill(new_value); return True
    except: pass
    # textarea
    try:
        el = page.locator(f"//label[normalize-space(.)={json.dumps(label_text)}]/following::textarea[1]").first
        el.scroll_into_view_if_needed(); el.click()
        cur = get_current_text(page, el)
        if cur == new_value: return True
        clear_with_cmd_a(page); el.fill(new_value); return True
    except: pass
    return False

def fill_rich_or_textarea_by_label(page, label_text, new_value):
    """Idempotent fill for contenteditable/Summernote or textarea under exact label."""
    if new_value is None: return False

    # rich editor
    try:
        rich = page.locator(
            f"//label[normalize-space(.)={json.dumps(label_text)}]"
            f"/following::*[self::div[@contenteditable='true'] or contains(@class,'note-editable')][1]"
        ).first
        rich.scroll_into_view_if_needed(); rich.click()
        cur = get_current_text(page, rich)
        if cur.strip() == new_value.strip(): return True
        clear_with_cmd_a(page); rich.type(new_value, delay=1); return True
    except: pass

    # textarea fallback
    return fill_input_or_textarea_by_label(page, label_text, new_value)

def click_save_and_verify(page):
    # click save
    try:
        page.get_by_role("button", name="Save").click(timeout=3000)
    except:
        try:
            page.locator("button.o_form_button_save, button:has-text('Save')").first.click(timeout=3000)
        except: pass
    # verify: Edit button visible again (read-only state)
    try:
        page.get_by_role("button", name="Edit").wait_for(timeout=10000)
        return True
    except PWTimeout:
        return False

# ── MAIN ──────────────────────────────────────────────────────────────
def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOWMO)
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            # 1) Login
            page.goto(OD_URL, timeout=60_000)
            page.fill("input[name='login'], input[name='email']", OD_EMAIL)
            page.fill("input[name='password']", OD_PASS)
            page.click("button[type='submit']")
            page.wait_for_timeout(2500)

            # 2) Open PIM (text, tile, or waffle)
            if not wait_and_click_text(page, "PIM"):
                try:
                    page.locator(".o_app .o_caption:has-text('PIM'), .o_app:has-text('PIM')").first.click(timeout=2000)
                except:
                    try:
                        page.locator(".o_menu_apps, .o_app_switcher").first.click(timeout=2000)
                        wait_and_click_text(page, "PIM")
                    except: pass
            page.wait_for_timeout(1200)

            # 3) Search and open the product
            try:
                search = page.locator("input.o_searchview_input, input[placeholder='Search...']").first
                search.click(); search.fill(TEST_QUERY); search.press("Enter")
            except: pass
            try:
                page.locator(".o_kanban_record", has_text=TEST_QUERY).first.click(timeout=4000)
            except:
                try:
                    page.get_by_text(TEST_QUERY, exact=False).first.click(timeout=4000)
                except: pass
            page.wait_for_timeout(800)

            # 4) Website tab → Edit mode
            try:
                page.get_by_role("tab", name="Website").click(timeout=3000)
            except:
                try:
                    page.locator("a[role='tab']:has-text('Website'), .nav-link:has-text('Website')").first.click(timeout=3000)
                except: pass
            try:
                page.get_by_role("button", name="Edit").click(timeout=3000)
            except:
                try:
                    page.locator("button.o_form_button_edit, button:has-text('Edit')").first.click(timeout=3000)
                except: pass
            page.wait_for_timeout(600)

            # 5) Build context from the page and generate content
            product_name = get_product_name(page)
            data = gen_override_and_meta(product_name)

            # 6) Fill fields (idempotent; only changes if different)
            # Override Preview Description
            fill_rich_or_textarea_by_label(page, "Override Preview Description",
                                           data.get("override_preview_description"))

            # Override Summary Description
            fill_rich_or_textarea_by_label(page, "Override Summary Description",
                                           data.get("override_summary_description"))

            # Override Full Description (template)
            fill_rich_or_textarea_by_label(page, "Override Full Description",
                                           data.get("override_full_description"))

            # Slug (or Website URL)
            if not fill_input_or_textarea_by_label(page, "Website Slug", data.get("website_slug")):
                fill_input_or_textarea_by_label(page, "Website URL", data.get("website_slug"))

            # Meta Title / Meta Description
            fill_input_or_textarea_by_label(page, "Meta Title",       data.get("meta_title"))
            fill_input_or_textarea_by_label(page, "Meta Description", data.get("meta_description"))

            # 7) Save & verify
            ok = click_save_and_verify(page)
            if not ok:
                page.screenshot(path=str(OUTDIR / "save_failed.png"), full_page=True)
                print("⚠️ Save verification failed (screenshot saved).")
            else:
                print("✅ Saved and verified.")

            page.wait_for_timeout(1500)

        except Exception as e:
            # emergency screenshot
            ts = int(time.time())
            page.screenshot(path=str(OUTDIR / f"error_{ts}.png"), full_page=True)
            print("❌ Run error:", e)

        finally:
            browser.close()

if __name__ == "__main__":
    main()
