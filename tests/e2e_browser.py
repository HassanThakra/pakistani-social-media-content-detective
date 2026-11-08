"""
End-to-end browser check for the CSV WORKBENCH at /workbench (needs Playwright + Chromium).
The public website is covered by tests/e2e_site.py.

    1. Start the app:      PORT=8765 python app.py
    2. In another shell:   python tests/e2e_browser.py http://127.0.0.1:8765 [screenshot_dir]

It walks every tab with the bundled real dataset, then the upload path, then keyboard
navigation, dark mode and a phone-sized screen. It fails (exit code 1) on any JavaScript
error, failed request, or Content-Security-Policy violation.
"""
import os
import re
import sys
import tempfile

from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SHOTS = sys.argv[2] if len(sys.argv) > 2 else None
CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "social_media_sentiment_raw.csv")

problems, checks = [], []


def check(name, ok, detail=""):
    checks.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def shot(page, name, full=True):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=full)


def wire(page):
    page.on("console", lambda m: problems.append(f"console {m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("requestfailed", lambda r: problems.append(f"requestfailed: {r.url} {r.failure}"))
    page.on("response", lambda r: problems.append(f"http {r.status}: {r.url}") if r.status >= 400 and "/api/" not in r.url else None)


def go(page, n):
    page.click(f"#tab-{n}")
    page.wait_for_selector(f"#panel-{n}", state="visible")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1180, "height": 900}, accept_downloads=True)
        page = ctx.new_page()
        wire(page)
        page.goto(BASE + "/workbench")
        check("page title", page.title() == "Data Detective", page.title())
        check("tab 1 visible, others hidden", page.is_visible("#panel-1") and not page.is_visible("#panel-2"))
        shot(page, "01_question")

        # ---- step 2: load the bundled real dataset
        go(page, 2)
        check("bundled dataset is the default source", page.is_checked('input[name="source"][value="bundled"]'))
        check("no synthetic/demo option on the page", "synthetic" not in page.inner_text("body").lower())
        page.click("#load-btn")
        page.wait_for_selector("#inspect-out", state="visible", timeout=20000)
        tiles = page.inner_text("#tiles")
        check("raw tiles show 2,260 rows and 13 columns", "2,260" in tiles and "13" in tiles, tiles.replace("\n", " "))
        check("44 exact duplicate rows reported", "44" in tiles)
        issues = page.inner_text("#issues")
        check("issues mention negative likes", "negative" in issues.lower())
        check("issues mention spellings", "spellings" in issues)
        check("provenance warns the data looks templated", "very repetitive" in page.inner_text("#provenance"))
        check("column table has 13 rows", page.locator("#columns tbody tr").count() == 13)
        databar = page.inner_text("#databar")
        check("data bar names the bundled dataset", "Bundled dataset" in databar and "2,200" in databar, databar)
        page.fill("#note-record", "One row is one social-media post.")
        page.fill("#note-provenance", "From the GitHub repo mrudukp/social-media-sentiment-analysis. No license stated.")
        page.fill('[data-note="meaning:likes"]', "Number of likes on the post")
        shot(page, "02_inspect")

        # ---- step 3: clean
        go(page, 3)
        page.wait_for_selector("#clean-out", state="visible")
        steps = page.inner_text("#clean-steps")
        check("cleaning merges platform spellings", "Tidied spellings in platform" in steps)
        check("cleaning removes 60 duplicates", "60 duplicate rows removed" in steps, steps[:300])
        check("negative likes set to missing", "Negative likes set to missing" in steps)
        check("focus defaults to Instagram", page.input_value("#focus-col") == "platform" and page.input_value("#focus-val") == "Instagram")
        check("focus info shows 595 of 2,200", "595" in page.inner_text("#focus-info"), page.inner_text("#focus-info"))
        shot(page, "03_clean")

        # ---- step 4: explore
        go(page, 4)
        page.wait_for_selector("#chart-group svg", timeout=15000)
        check("group chart has 3 bars (sentiment)", page.locator("#chart-group path.bar").count() == 3, str(page.locator("#chart-group path.bar").count()))
        check("group table lists Positive/Neutral/Negative", all(w in page.inner_text("#table-group") for w in ("Positive", "Neutral", "Negative")))
        check("histogram drawn", page.locator("#chart-dist rect.bar").count() > 3)
        check("scatter drawn", page.locator("#chart-scatter circle.dot").count() > 100)
        check("Spearman 0.51 shown", "0.51" in page.inner_text("#scatter-facts"), page.inner_text("#scatter-facts"))
        check("weekday block shown with 7 rows", page.is_visible("#weekday-block") and page.locator("#table-weekday tbody tr").count() == 7)
        check("reach/impressions warning shown", "no reach or impressions" in page.inner_text("#explore-warnings").lower())
        page.hover("#chart-group path.bar >> nth=0")
        check("hover tooltip appears", page.is_visible("#tip") and "median" in page.inner_text("#tip"), page.inner_text("#tip"))
        shot(page, "04_explore")
        page.select_option("#sel-group", "country")
        expect(page.locator("#h-group")).to_contain_text("country")
        check("changing group to country redraws (>= 8 bars)", page.locator("#chart-group path.bar").count() >= 8)
        check("small country groups flagged 'few posts'", "few posts" in page.inner_text("#table-group"))
        shot(page, "04b_explore_country")
        page.select_option("#sel-group", "sentiment")
        page.uncheck("#sel-focus")
        expect(page.locator("#explore-scope")).to_contain_text("all rows")
        check("unticking focus uses all 2,200 rows", "2,200" in page.inner_text("#explore-scope"), page.inner_text("#explore-scope"))
        page.check("#sel-focus")
        page.fill("#sel-min", "0")
        page.wait_for_timeout(700)

        # ---- step 5: interpret
        go(page, 5)
        check("interpret tab repeats the cautions", page.locator("#interpret-warnings .callout").count() >= 1)
        page.fill("#note-finding", "In this dataset Positive posts have a higher median comment count than Neutral.")
        page.fill("#note-evidence", "Median comments 4 vs 3 with 216 and 184 posts.")
        page.fill("#note-finding2", "Likes and comments move together (Spearman about 0.5).")
        page.fill("#note-evidence2", "Scatter plot and correlation in step 4.")
        page.fill("#note-action", "Test more Positive-toned posts and compare with a consistent metric.")
        page.fill("#note-limitation", "No reach or impressions column, and the data may be generated.")
        shot(page, "05_interpret")

        # ---- step 6: scale
        go(page, 6)
        check("1000x disabled (over the server limit)", page.is_disabled('input[name="factor"][value="1000"]'))
        page.click("#scale-btn")
        page.wait_for_selector("#scale-out", state="visible", timeout=60000)
        check("scaling table has 3 rows", page.locator("#scale-table tbody tr").count() == 3, str(page.locator("#scale-table tbody tr").count()))
        check("scaling shows 220,000 rows at 100x", "220,000" in page.inner_text("#scale-table"))
        check("scaling chart has 2 series", page.locator("#chart-scale path.line-1, #chart-scale path.line-2").count() == 2)
        page.fill("#note-reflect", "Loading grew faster than the analysis; 100x still fit in memory.")
        shot(page, "06_scale")

        # ---- step 7: analytics
        go(page, 7)
        page.click("#models-btn")
        page.wait_for_selector("#models-out .cards", timeout=60000)
        mt = page.inner_text("#models-out")
        check("classification result shown", "unseen test posts" in mt)
        check("regression result shown", "off by" in mt)
        check("clustering table has 3 groups", page.locator("#models-out table tbody tr").count() == 3)
        page.fill("#note-analytics", "Classification, with a defensible engagement label.")
        shot(page, "07_analytics")

        # ---- step 8: submit
        go(page, 8)
        check("all 5 checklist items tick", page.locator("#checklist li.done").count() == 5, str(page.locator("#checklist li.done").count()))
        page.fill("#note-closing", "Positive posts get slightly more comments; test that next.")
        page.click("#report-preview-btn")
        report = page.inner_text("#report-preview")
        for needle in ("# Project 1 report", "Bundled dataset", "One row is one social-media post", "Number of likes on the post",
                       "Spearman", "220,000", "Classification:", "no stated license"):
            check(f"report contains '{needle}'", needle in report)
        with page.expect_download() as dl:
            page.click("#report-btn")
        path = dl.value.path()
        text = open(path, encoding="utf-8").read()
        check("downloaded report file matches preview", dl.value.suggested_filename == "project1_report.md" and "# Project 1 report" in text and len(text) > 2000, f"{len(text)} chars")
        shot(page, "08_submit")

        # ---- notes survive a reload (saved in this browser only)
        page.reload()
        page.wait_for_load_state()
        go(page, 5)
        check("notes restored after reload", "Positive posts have a higher median" in page.input_value("#note-finding"))
        page.on("dialog", lambda d: d.accept())
        go(page, 8)
        page.click("#clear-notes")
        go(page, 5)
        check("clear-notes empties the fields", page.input_value("#note-finding") == "")

        # ---- upload path with the real CSV
        go(page, 2)
        page.check('input[name="source"][value="upload"]')
        page.click("#load-btn")
        check("upload with no file shows an error", "Choose a CSV file" in page.inner_text("#load-error"))
        page.set_input_files("#file-input", CSV)
        check("choosing a file selects the upload source", page.is_checked('input[name="source"][value="upload"]'))
        page.click("#load-btn")
        expect(page.locator("#databar-text")).to_contain_text("Your file", timeout=20000)
        check("upload loads the same data", "2,200" in page.inner_text("#databar") and "discarded" in page.inner_text("#databar"), page.inner_text("#databar"))
        # a bad file
        bad = os.path.join(tempfile.mkdtemp(), "bad.csv")
        open(bad, "w").write("only_one_column\n1\n2\n")
        page.set_input_files("#file-input", bad)
        page.click("#load-btn")
        expect(page.locator("#load-error")).to_be_visible(timeout=10000)
        check("bad file shows a clear error", "Only one column" in page.inner_text("#load-error"), page.inner_text("#load-error"))
        # a different, tiny file works end to end
        small = os.path.join(tempfile.mkdtemp(), "small.csv")
        with open(small, "w") as f:
            f.write("platform,likes,comments\n" + "\n".join(f"{['A','B','C'][i % 3]},{i % 17},{i % 5}" for i in range(400)) + "\n")
        page.set_input_files("#file-input", small)
        page.click("#load-btn")
        expect(page.locator("#databar-text")).to_contain_text("small.csv", timeout=15000)
        go(page, 4)
        page.wait_for_selector("#chart-group svg", timeout=15000)
        check("a different CSV explores without errors", page.locator("#chart-group path.bar").count() >= 2 and page.is_hidden("#explore-error"))
        go(page, 7)
        page.click("#models-btn")
        page.wait_for_selector("#models-out .callout, #models-out .cards", timeout=30000)
        check("models explain when columns are missing", "need" in page.inner_text("#models-out").lower() or "unseen" in page.inner_text("#models-out"))

        # ---- keyboard navigation of tabs
        page.focus("#tab-1")
        page.keyboard.press("ArrowRight")
        check("ArrowRight moves to tab 2", page.get_attribute("#tab-2", "aria-selected") == "true" and page.is_visible("#panel-2"))
        page.keyboard.press("End")
        check("End moves to tab 8", page.get_attribute("#tab-8", "aria-selected") == "true")
        page.keyboard.press("Home")
        check("Home moves to tab 1", page.get_attribute("#tab-1", "aria-selected") == "true")

        # ---- reload on the real bundled data for the theme and phone checks
        page.goto(BASE + "/workbench#4")
        go(page, 2)
        page.check('input[name="source"][value="bundled"]')
        page.click("#load-btn")
        expect(page.locator("#databar-text")).to_contain_text("Bundled", timeout=20000)
        go(page, 4)
        page.wait_for_selector("#chart-group svg")

        # ---- dark mode
        dctx = browser.new_context(viewport={"width": 1180, "height": 900}, color_scheme="dark")
        dpage = dctx.new_page()
        wire(dpage)
        dpage.goto(BASE + "/workbench")
        dpage.click("#tab-2"); dpage.click("#load-btn")
        dpage.wait_for_selector("#inspect-out", state="visible", timeout=20000)
        dpage.click("#tab-4"); dpage.wait_for_selector("#chart-group svg")
        bg = dpage.evaluate("getComputedStyle(document.body).backgroundColor")
        check("dark mode background is dark", bg == "rgb(26, 26, 25)", bg)
        shot(dpage, "09_dark_explore")
        dpage.click("#theme-btn")
        check("theme button cycles to light", "light" in dpage.inner_text("#theme-btn"))
        bg2 = dpage.evaluate("getComputedStyle(document.body).backgroundColor")
        check("light override beats dark preference", bg2 == "rgb(252, 252, 251)", bg2)

        # ---- phone-sized screen: no sideways scrolling on any tab
        mctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, device_scale_factor=2)
        mpage = mctx.new_page()
        wire(mpage)
        mpage.goto(BASE + "/workbench")
        mpage.click("#tab-2"); mpage.click("#load-btn")
        mpage.wait_for_selector("#inspect-out", state="visible", timeout=20000)
        mpage.click("#tab-4"); mpage.wait_for_selector("#chart-group svg")
        mpage.click("#tab-6"); mpage.click("#scale-btn"); mpage.wait_for_selector("#scale-out", state="visible", timeout=60000)
        for n in range(1, 9):
            mpage.click(f"#tab-{n}")
            mpage.wait_for_selector(f"#panel-{n}", state="visible")
            sw = mpage.evaluate("document.documentElement.scrollWidth"); iw = mpage.evaluate("window.innerWidth")
            check(f"phone: tab {n} has no page-level horizontal scroll", sw <= iw + 1, f"scrollWidth {sw} > {iw}")
            if n == 4:
                shot(mpage, "10_phone_explore")
        browser.close()

    # The deliberate bad-file test makes the server answer 400 once; Chromium logs that. Anything else is a problem.
    expected_400 = [x for x in problems if "status of 400" in x]
    check("exactly one deliberate 400 (the one-column file)", len(expected_400) == 1, str(len(expected_400)))
    bad = [x for x in problems if not re.search(r"favicon", x) and "status of 400" not in x]
    check("no console errors, failed requests or CSP violations", not bad, "; ".join(bad[:5]))
    failed = [c for c in checks if not c[1]]
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks passed")
    for x in bad[:20]:
        print("  problem:", x)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
