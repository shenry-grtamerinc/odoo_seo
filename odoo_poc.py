from playwright.sync_api import sync_playwright
import os, json, re
from dotenv import load_dotenv
from openai import OpenAI

# ── ENV / OPENAI ─────────────────────────────────────────────────────
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing in .env")
oa = OpenAI(api_key=OPENAI_API_KEY)

# ── CONFIG ───────────────────────────────────────────────────────────
OD_URL   = "https://greatamerican.steersman.io/web/login"
OD_EMAIL = "shenry@greatamericaninc.com"
OD_PASS  = "Sheriloye123."
TEST_QUERY = 'Milwaukee 0940-20 M18 FUEL™ Compact Vacuum'  # used only to find the product

# ── HELPERS ──────────────────────────────────────────────────────────
def sanitize_slug(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\- ]+", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")

def get_product_name(page) -> str:
    # try several common places (header, breadcrumb, name input)
    css_candidates = [
        "h1", ".o_breadcrumb .active",
        "[name='name'] input", ".o_field_widget[name='name'] input",
        "[name='name'] .o_input", ".o_form_view h1",
    ]
    for css in css_candidates:
        try:
            t = page.locator(css).first.text_content(timeout=800)
            if t and t.strip(): return t.strip()
        except:
            try:
                v = page.locator(css).first.input_value(timeout=800)
                if v and v.strip(): return v.strip()
            except:
                pass
    return TEST_QUERY

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

STRICT RULES:
- for Milwaukee products you can reference the official milwaukee.com site for specs.
- for other brands/products, keep specs generic if not known or cannot find any website reference.
- override_preview_description: <= 2 sentences, concise.
- override_summary_description: 4–5 sentences.
- override_full_description: MUST follow this plain-text template (keep headings & asterisks):

**{product_name}** (Make sure you do not include any other texts than the product name here and the sku number Make sure to delete the "Name will be generated after saving".)

**INCLUDES** (ENSURE THIS PARAMETER IN WITH THE ITEMS IF THE PRODUCT COMES WITH ACCESSORIES; IF NOT, LEAVE THIS SECTION OUT)
(1) (Item Name Here)
(1) (Item Name Here)
(1) (Item Name Here)

**PRODUCT OVERVIEW**
(Brief blurb of the product here)

**KEY FEATURES** (Bullet list with at least 2 features always and the bulet list should be short phrases)
- (Key feature 1)
- (Key feature 2)

(Expand bullet count only if obviously helpful; keep headings exactly.)
- meta_title: ≤ 60 chars; include brand/model if naturally present in the name.
- meta_description: ≤ 155 chars; catchy and SEO-friendly.
- website_slug: SEO-friendly, lowercase, hyphen-separated, no special chars.
If details are not explicit in the name, keep language generic without inventing specs.
Only output JSON.
"""
    resp = oa.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.3,
        response_format={"type":"json_object"},
        messages=[
            {"role":"system","content":"You are a precise ecommerce content assistant. Output strict JSON only."},
            {"role":"user","content":prompt}
        ],
    )
    data = json.loads(resp.choices[0].message.content)
    # guardrails
    mt = (data.get("meta_title") or "").strip()
    md = (data.get("meta_description") or "").strip()
    if len(mt) > 60: mt = mt[:60].rstrip()
    if len(md) > 155: md = md[:155].rstrip()
    data["meta_title"] = mt
    data["meta_description"] = md
    data["website_slug"] = sanitize_slug(data.get("website_slug") or product_name)
    for k in ("override_preview_description","override_summary_description","override_full_description"):
        if data.get(k): data[k] = data[k].strip()
    return data

def clear_input_or_textarea(page, el):
    try:
        el.click()
        page.keyboard.press("Meta+a")
        page.keyboard.press("Backspace")
    except:
        pass

def fill_input_or_textarea_by_exact_label(page, label_text: str, value: str) -> bool:
    """Fill input/textarea that follows a label with exact text."""
    if not value: return False
    # input
    try:
        el = page.locator(f"//label[normalize-space(.)={json.dumps(label_text)}]/following::input[1]").first
        el.scroll_into_view_if_needed()
        clear_input_or_textarea(page, el)
        el.fill(value)
        return True
    except:
        pass
    # textarea
    try:
        el = page.locator(f"//label[normalize-space(.)={json.dumps(label_text)}]/following::textarea[1]").first
        el.scroll_into_view_if_needed()
        clear_input_or_textarea(page, el)
        el.fill(value)
        return True
    except:
        return False

def fill_rich_or_textarea_by_exact_label(page, label_text: str, value: str) -> bool:
    """
    Fill a rich editor (contenteditable / Summernote) OR textarea that follows the exact label text.
    """
    if not value: return False

    # 1) try rich editor
    try:
        rich = page.locator(
            f"//label[normalize-space(.)={json.dumps(label_text)}]"
            f"/following::*[self::div[@contenteditable='true'] or contains(@class,'note-editable')][1]"
        ).first
        rich.scroll_into_view_if_needed()
        rich.click()
        # clear existing
        try:
            page.keyboard.press("Meta+a"); page.keyboard.press("Backspace")
        except: pass
        # type (safer than fill for contenteditable)
        rich.type(value, delay=1)
        return True
    except:
        pass

    # 2) fallback to textarea
    try:
        ta = page.locator(
            f"//label[normalize-space(.)={json.dumps(label_text)}]/following::textarea[1]"
        ).first
        ta.scroll_into_view_if_needed()
        clear_input_or_textarea(page, ta)
        ta.fill(value)
        return True
    except:
        return False

# ── MAIN ──────────────────────────────────────────────────────────────
def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=250)
        context = browser.new_context()
        page = context.new_page()

        # 1) Login
        page.goto(OD_URL, timeout=60_000)
        page.fill("input[name='login'], input[name='email']", OD_EMAIL)
        page.fill("input[name='password']", OD_PASS)
        page.click("button[type='submit']")
        page.wait_for_timeout(3000)

        # 2) Open PIM
        for _ in range(3):
            try:
                page.get_by_text("PIM", exact=False).first.click(); break
            except:
                try:
                    page.locator(".o_app .o_caption:has-text('PIM'), .o_app:has-text('PIM')").first.click(); break
                except:
                    try:
                        page.locator(".o_menu_apps, .o_app_switcher").first.click()
                    except:
                        pass
            page.wait_for_timeout(600)
        page.wait_for_timeout(2000)

        # 3) Search & open product
        try:
            search = page.locator("input.o_searchview_input, input[placeholder='Search...']").first
            search.click(); search.fill(TEST_QUERY); search.press("Enter")
        except: pass
        try:
            page.locator(".o_kanban_record", has_text=TEST_QUERY).first.click()
        except:
            try:
                page.get_by_text(TEST_QUERY, exact=False).first.click()
            except: pass
        page.wait_for_timeout(1200)

        # 4) Website tab → Edit
        try:
            page.get_by_role("tab", name="Website").click()
        except:
            try:
                page.locator("a[role='tab']:has-text('Website'), .nav-link:has-text('Website')").first.click()
            except: pass
        try:
            page.get_by_role("button", name="Edit").click()
        except:
            try:
                page.locator("button.o_form_button_edit, button:has-text('Edit')").first.click()
            except: pass
        page.wait_for_timeout(600)

        # 5) Build context from page (product name only) and get content
        product_name = get_product_name(page)
        data = gen_override_and_meta(product_name)

        # 6) Fill EXACTLY these fields by label (names as shown in your UI)
        #    (a) Override Preview Description (≤2 sentences)
        fill_rich_or_textarea_by_exact_label(page, "Override Preview Description",
                                             data.get("override_preview_description"))

        #    (b) Override Summary Description (4–5 sentences)
        fill_rich_or_textarea_by_exact_label(page, "Override Summary Description",
                                             data.get("override_summary_description"))

        #    (c) Override Full Description (template form)
        fill_rich_or_textarea_by_exact_label(page, "Override Full Description",
                                             data.get("override_full_description"))

        # 7) Also set Slug + Meta fields (these already worked for you)
        if not fill_input_or_textarea_by_exact_label(page, "Website Slug", data.get("website_slug")):
            fill_input_or_textarea_by_exact_label(page, "Website URL", data.get("website_slug"))
        fill_input_or_textarea_by_exact_label(page, "Meta Title", data.get("meta_title"))
        fill_input_or_textarea_by_exact_label(page, "Meta Description", data.get("meta_description"))

        # 8) Save
        try:
            page.get_by_role("button", name="Save").click()
        except:
            try:
                page.locator("button.o_form_button_save, button:has-text('Save')").first.click()
            except: pass

        page.wait_for_timeout(4000)
        browser.close()

if __name__ == "__main__":
    main()

