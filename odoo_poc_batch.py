import asyncio, os, csv, io, json, re, sys, traceback
from datetime import datetime
from typing import List, Dict, Optional
import requests
from dotenv import load_dotenv
from tqdm import tqdm
from openai import OpenAI
from playwright.async_api import async_playwright, Page, BrowserContext

# ── ENV / OPENAI ─────────────────────────────────────────────────────
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing in .env")
oa = OpenAI(api_key=OPENAI_API_KEY)

OD_URL   = os.getenv("OD_URL", "https://greatamerican.steersman.io/web/login")
OD_EMAIL = os.getenv("OD_EMAIL")
OD_PASS  = os.getenv("OD_PASS")

HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
SLOWMO_MS = int(os.getenv("SLOWMO_MS", "200"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "2"))
BATCH_LIMIT = int(os.getenv("BATCH_LIMIT", "0"))  # 0 = no limit (process all)

BATCH_CSV_PATH = os.getenv("BATCH_CSV_PATH", "").strip()
BATCH_CSV_URL  = os.getenv("BATCH_CSV_URL", "").strip()

# ── HELPERS ──────────────────────────────────────────────────────────
def sanitize_slug(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\- ]+", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")

def gen_override_and_meta_sync(product_name: str) -> dict:
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
- Identify the product name and NEVER mention or reuse text from other brands or products unless that brand name is part of "{product_name}"
- for Milwaukee products you can reference the official milwaukee.com site for specs.
- for other brands/products, keep specs generic if not known or cannot find any website reference.
- override_preview_description: <= 2 sentences, concise.
- override_summary_description: 4–5 sentences.
- override_full_description: MUST follow this plain-text template (keep headings & asterisks):

**{product_name}** (Make sure you do not include any other texts than the product name here and the sku number Make sure to delete the "Name will be generated after saving".)

**INCLUDES** (ENSURE THIS PARAMETER IN WITH THE ITEMS IF THE PRODUCT COMES WITH ACCESSORIES; IF NOT, LEAVE THIS SECTION OUT, Make sure "INCLUDES" is in all caps)
(1) (Item Name Here)
(1) (Item Name Here)
(1) (Item Name Here)

**PRODUCT OVERVIEW** (Make sure "PRODUCT OVERVIEW" is in all caps)
(Brief blurb of the product here)

**KEY FEATURES** (Bullet list with at least 2 features always and the bulet list should be short phrases, Make sure "KEY FEATURES" is in all caps)
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

async def gen_override_and_meta(product_name: str) -> dict:
    return await asyncio.to_thread(gen_override_and_meta_sync, product_name)

# ---------------------------------------------------------------------
# DOM helpers
# ---------------------------------------------------------------------
async def clear_input_or_textarea(page: Page, el):
    try:
        await el.click()
        await page.keyboard.press("Meta+a")
        await page.keyboard.press("Backspace")
    except:
        pass

async def fill_input_or_textarea_by_exact_label(page: Page, label_text: str, value: Optional[str]) -> bool:
    if not value: return False
    try:
        el = page.locator(f"//label[normalize-space(.)={json.dumps(label_text)}]/following::input[1]").first
        await el.scroll_into_view_if_needed()
        await clear_input_or_textarea(page, el)
        await el.fill(value)
        return True
    except:
        pass
    try:
        el = page.locator(f"//label[normalize-space(.)={json.dumps(label_text)}]/following::textarea[1]").first
        await el.scroll_into_view_if_needed()
        await clear_input_or_textarea(page, el)
        await el.fill(value)
        return True
    except:
        return False

async def fill_rich_or_textarea_by_exact_label(page: Page, label_text: str, value: Optional[str]) -> bool:
    if not value: return False
    try:
        rich = page.locator(
            f"//label[normalize-space(.)={json.dumps(label_text)}]"
            f"/following::*[self::div[@contenteditable='true'] or contains(@class,'note-editable')][1]"
        ).first
        await rich.scroll_into_view_if_needed()
        await rich.click()
        try:
            await page.keyboard.press("Meta+a"); await page.keyboard.press("Backspace")
        except: pass
        await rich.type(value, delay=1)
        return True
    except:
        pass
    try:
        ta = page.locator(
            f"//label[normalize-space(.)={json.dumps(label_text)}]/following::textarea[1]"
        ).first
        await ta.scroll_into_view_if_needed()
        await clear_input_or_textarea(page, ta)
        await ta.fill(value)
        return True
    except:
        return False

async def get_text_by_exact_label(page: Page, label_text: str) -> str:
    for xp in ["input","textarea","div[@contenteditable='true']"]:
        try:
            el = page.locator(f"//label[normalize-space(.)={json.dumps(label_text)}]/following::{xp}[1]").first
            await el.scroll_into_view_if_needed()
            v = await el.input_value() if xp!="div[@contenteditable='true']" else await el.text_content()
            if v:
                v = re.sub(r"\s+"," ",v).strip()
                if v and v not in ("<p><br></p>","&nbsp;"):
                    return v
        except:
            pass
    return ""

async def is_all_fields_filled(page: Page) -> bool:
    fields = [
        "Override Preview Description",
        "Override Summary Description",
        "Override Full Description",
        "Meta Title",
        "Meta Description",
    ]
    for f in fields:
        v = await get_text_by_exact_label(page, f)
        if not v:
            return False
    return True

# ---------------------------------------------------------------------
# login + navigation
# ---------------------------------------------------------------------
async def login_and_open_context(p, headless: bool, slow_mo: int):
    browser = await p.chromium.launch(headless=headless, slow_mo=slow_mo)
    ctx = await browser.new_context()
    page = await ctx.new_page()
    await page.goto(OD_URL, timeout=60_000)
    await page.fill("input[name='login'], input[name='email']", OD_EMAIL)
    await page.fill("input[name='password']", OD_PASS)
    await page.click("button[type='submit']")
    await page.wait_for_timeout(3000)
    return ctx, page

async def goto_pim(page: Page):
    for _ in range(3):
        try:
            await page.get_by_text("PIM", exact=False).first.click(); break
        except:
            try:
                await page.locator(".o_app .o_caption:has-text('PIM'), .o_app:has-text('PIM')").first.click(); break
            except:
                try:
                    await page.locator(".o_menu_apps, .o_app_switcher").first.click()
                except:
                    pass
        await page.wait_for_timeout(600)
    await page.wait_for_timeout(1200)

async def search_and_open_product(page: Page, product_name: str) -> bool:
    try:
        s = page.locator("input.o_searchview_input, input[placeholder='Search...']").first
        await s.click(); await s.fill(product_name); await s.press("Enter")
    except:
        pass
    try:
        await page.locator(".o_kanban_record", has_text=product_name).first.click()
        return True
    except:
        try:
            await page.get_by_text(product_name, exact=False).first.click()
            return True
        except:
            return False

async def open_website_edit(page: Page):
    try:
        await page.get_by_role("tab", name="Website").click()
    except:
        try:
            await page.locator("a[role='tab']:has-text('Website'), .nav-link:has-text('Website')").first.click()
        except:
            pass
    try:
        await page.get_by_role("button", name="Edit").click()
    except:
        try:
            await page.locator("button.o_form_button_edit, button:has-text('Edit')").first.click()
        except:
            pass
    await page.wait_for_timeout(600)

async def save_form(page: Page):
    try:
        await page.get_by_role("button", name="Save").click()
    except:
        try:
            await page.locator("button.o_form_button_save, button:has-text('Save')").first.click()
        except:
            pass
    await page.wait_for_timeout(1200)

# ---------------------------------------------------------------------
# product processing
# ---------------------------------------------------------------------
async def process_one(page: Page, product_name: str, sku: Optional[str]) -> str:
    await goto_pim(page)
    found = await search_and_open_product(page, product_name)
    if not found:
        return "not_found"
    await open_website_edit(page)
    if await is_all_fields_filled(page):
        return "skipped"
    data = await gen_override_and_meta(product_name)
    await fill_rich_or_textarea_by_exact_label(page, "Override Preview Description", data.get("override_preview_description"))
    await fill_rich_or_textarea_by_exact_label(page, "Override Summary Description", data.get("override_summary_description"))
    await fill_rich_or_textarea_by_exact_label(page, "Override Full Description", data.get("override_full_description"))
    slug_val = data.get("website_slug")
    ok_slug = await fill_input_or_textarea_by_exact_label(page, "Website Slug", slug_val)
    if not ok_slug:
        await fill_input_or_textarea_by_exact_label(page, "Website URL", slug_val)
    await fill_input_or_textarea_by_exact_label(page, "Meta Title", data.get("meta_title"))
    await fill_input_or_textarea_by_exact_label(page, "Meta Description", data.get("meta_description"))
    await save_form(page)
    return "updated"

# ---------------------------------------------------------------------
# CSV loader (local or url)
# ---------------------------------------------------------------------
def read_sheet_rows(source: str) -> List[Dict[str, str]]:
    """
    Load CSV either from a URL (http/https) or local file path, robust to spaces and case.
    """
    if not source:
        return []

    # load file content (local or URL)
    if os.path.exists(source) and not source.startswith("http"):
        with open(source, "r", encoding="utf-8-sig", newline="") as f:
            raw = f.read().strip()
    else:
        r = requests.get(source, timeout=30)
        r.raise_for_status()
        raw = r.content.decode("utf-8-sig", errors="replace").strip()

    reader = csv.DictReader(io.StringIO(raw))
    rows = []
    for row in reader:
        # normalize all keys (strip and lowercase)
        normalized = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        pn = normalized.get("product name") or normalized.get("name") or normalized.get("product")
        sku = normalized.get("sku")
        if pn:
            rows.append({"Product Name": pn, "SKU": sku})
    return rows

# ---------------------------------------------------------------------
# logging + concurrency
# ---------------------------------------------------------------------
def append_log(name: str, sku: str, status: str, note: str = ""):
    path = "batch_log.csv"
    exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["Timestamp", "Product Name", "SKU", "Status", "Note"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), name, sku, status, note])

async def worker(p, queue: asyncio.Queue, progress: tqdm, worker_id: int):
    ctx, page = await login_and_open_context(p, HEADLESS, SLOWMO_MS)
    try:
        while True:
            try:
                # Wait for next available product (prevents duplicates)
                item = await queue.get()
            except asyncio.CancelledError:
                break

            name = item["Product Name"]
            sku = item.get("SKU", "")

            try:
                st = await process_one(page, name, sku)
                msg = {"updated": "✓", "skipped": "→", "not_found": "✗"}.get(st, "⚠")
                print(f"[{msg} {worker_id}] {name} — {st}")
                append_log(name, sku, st)
            except Exception as e:
                print(f"[⚠ {worker_id}] {name} — {e}")
                append_log(name, sku, "error", f"{type(e).__name__}: {e}")
                traceback.print_exc(file=sys.stdout)
            finally:
                progress.update(1)
                queue.task_done()  # mark product as finished

            if queue.empty():
                break
    finally:
        await ctx.close()

# ---------------------------------------------------------------------
# main
# ---------------------------------------------------------------------
async def main_async():
    source = BATCH_CSV_PATH if BATCH_CSV_PATH else BATCH_CSV_URL
    rows = read_sheet_rows(source)
    if not rows:
        print("No rows found in CSV (need headers: 'Product Name','SKU').")
        return

    total_products = len(rows)
    if BATCH_LIMIT > 0:
        rows = rows[:BATCH_LIMIT]
        print(f"Loaded {total_products} total products; processing first {BATCH_LIMIT} (BATCH_LIMIT)")
    else:
        print(f"Loaded {total_products} products (no batch limit).")

    print(f"Concurrency = {MAX_CONCURRENT}, Headless = {HEADLESS}")
    print("\nPreview of products being processed:")
    for r in rows[:3]:
        print(f" • {r['Product Name']} ({r.get('SKU', '')})")

    # prepare queue
    q = asyncio.Queue()
    for r in rows:
        q.put_nowait(r)

    async with async_playwright() as p:
        bar = tqdm(total=len(rows), desc="Batch progress", unit="item")
        try:
            tasks = [asyncio.create_task(worker(p, q, bar, i + 1)) for i in range(MAX_CONCURRENT)]
            await asyncio.gather(*tasks)
        finally:
            bar.close()

    print(f"\n✅ Batch completed: {len(rows)} products processed (limit = {BATCH_LIMIT or 'ALL'}).")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()

