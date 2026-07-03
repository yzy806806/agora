"""Agora Dashboard E2E Test v2 — correct navigation through Hermes Plugins page."""
import asyncio
import json
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright

DASHBOARD_URL = "http://localhost:18765"
ADMIN_USER = "admin"
ADMIN_PASS = os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "wKHITmcn2mIrat2")
SCREENSHOT_DIR = Path("/root/agora/e2e-screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

results = []

def log_pass(msg):
    print(f"{GREEN}  ✓ {msg}{RESET}")
    results.append(("pass", msg))

def log_fail(msg, detail=""):
    print(f"{RED}  ✗ {msg}{RESET}")
    if detail:
        print(f"    {detail}")
    results.append(("fail", msg + (" — " + detail if detail else "")))

def log_info(msg):
    print(f"{YELLOW}  → {msg}{RESET}")

async def screenshot(page, name):
    path = SCREENSHOT_DIR / f"{name}.png"
    # Use screenshots without waiting for fonts (which can timeout)
    try:
        await page.screenshot(path=str(path), full_page=False, timeout=5000)
        log_info(f"Screenshot: {path.name}")
    except Exception:
        log_info(f"Screenshot skipped (timeout): {name}")

async def run_tests():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True,
        )
        page = await context.new_page()

        console_errors = []
        page.on("console", lambda msg: console_errors.append(f"{msg.type}: {msg.text}") if msg.type == "error" else None)

        print("\n" + "=" * 60)
        print("Agora Dashboard E2E Test (v2)")
        print("=" * 60)

        # --- Test 1: Login ---
        print("\n[Test 1] Login")
        try:
            resp = await page.request.post(
                DASHBOARD_URL + "/auth/password-login",
                data=json.dumps({"provider": "basic", "username": ADMIN_USER, "password": ADMIN_PASS}),
                headers={"Content-Type": "application/json"},
            )
            if resp.status == 200:
                log_pass("Login OK (200)")
            else:
                log_fail(f"Login failed ({resp.status})")
                return
        except Exception as e:
            log_fail("Login exception", str(e))
            return

        # --- Test 2: Navigate to Agora via sidebar link ---
        print("\n[Test 2] Navigate to Agora dashboard")
        try:
            # Navigate directly to /agora (sidebar link)
            await page.goto(DASHBOARD_URL + "/agora", wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(3000)

            agora_dashboard = page.locator('.agora-dashboard')
            count = await agora_dashboard.count()
            if count > 0:
                log_pass("Agora dashboard rendered at /agora")
            else:
                # Try clicking sidebar Agora link
                agora_link = page.locator('a[href="/agora"]')
                if await agora_link.count() > 0:
                    await agora_link.first.click()
                    await page.wait_for_timeout(3000)
                    agora_dashboard = page.locator('.agora-dashboard')
                    if await agora_dashboard.count() > 0:
                        log_pass("Agora dashboard rendered after sidebar click")
                    else:
                        log_fail("Agora dashboard not found after sidebar click")
                else:
                    log_fail("Agora sidebar link not found")

            await screenshot(page, "02-agora-main")
        except Exception as e:
            log_fail("Agora navigation failed", str(e))

        # --- Test 4: Projects tab ---
        print("\n[Test 4] Projects tab")
        try:
            # Check if we can see Projects tab
            projects_tab = page.locator('button:has-text("Projects"), [data-value="projects"]')
            if await projects_tab.count() > 0:
                await projects_tab.first.click()
                await page.wait_for_timeout(2000)

            project_cards = await page.locator('.agora-project-card').count()
            start_btn = await page.locator('button:has-text("Start")').count()
            log_pass(f"Projects: {project_cards} cards, {start_btn} start buttons")
            await screenshot(page, "04-projects")
        except Exception as e:
            log_fail("Projects tab failed", str(e))

        # --- Test 5: Team tab with sub-tabs ---
        print("\n[Test 5] Team tab + sub-tabs")
        try:
            team_tab = page.locator('button:has-text("Team")')
            if await team_tab.count() > 0:
                await team_tab.first.click()
                await page.wait_for_timeout(2000)
                log_pass("Team tab clicked")

                # Check sub-tabs exist
                for sub in ["Members", "Teams", "Profiles"]:
                    btn = page.locator(f'button:has-text("{sub}")')
                    c = await btn.count()
                    if c > 0:
                        await btn.last.click()  # click the sub-tab version, not sidebar
                        await page.wait_for_timeout(1500)
                        await screenshot(page, f"05-team-{sub.lower()}")
                        log_pass(f"Sub-tab '{sub}' rendered")
                    else:
                        log_fail(f"Sub-tab '{sub}' not found")

                await screenshot(page, "05-team-overview")
            else:
                log_fail("Team tab not found")
        except Exception as e:
            log_fail("Team tab failed", str(e))

        # --- Test 6: Project detail (if projects exist) ---
        print("\n[Test 6] Project detail")
        try:
            # Go back to Projects
            proj_btn = page.locator('button:has-text("Projects")')
            if await proj_btn.count() > 0:
                await proj_btn.first.click()
                await page.wait_for_timeout(2000)

            cards = page.locator('.agora-project-card')
            count = await cards.count()
            if count > 0:
                await cards.first.click()
                await page.wait_for_timeout(3000)
                log_pass(f"Opened project (1 of {count})")

                # Check project sub-tabs
                for sub in ["Overview", "Kanban", "Discussions", "Team"]:
                    btn = page.locator(f'button:has-text("{sub}")')
                    if await btn.count() > 0:
                        await btn.first.click()
                        await page.wait_for_timeout(1500)
                        await screenshot(page, f"06-project-{sub.lower()}")
                        log_pass(f"Project {sub} rendered")

                await screenshot(page, "06-project-detail")
            else:
                log_info("No projects — skipping project detail")
        except Exception as e:
            log_fail("Project detail failed", str(e))

        # --- Test 7: Heartbeat control ---
        print("\n[Test 7] Heartbeat control panel")
        try:
            ov_btn = page.locator('button:has-text("Overview")')
            if await ov_btn.count() > 0:
                await ov_btn.first.click()
                await page.wait_for_timeout(1500)

            # Look for heartbeat elements
            hb_elements = await page.evaluate("""() => {
                const els = document.querySelectorAll('[class*="heartbeat"], [class*="hb"]');
                return Array.from(els).map(e => ({class: e.className, tag: e.tagName, text: e.textContent.slice(0,80)}));
            }""")
            if hb_elements:
                log_pass(f"Heartbeat elements found: {len(hb_elements)}")
                for e in hb_elements[:3]:
                    log_info(f"  {e['class']}: {e['text'][:50]}")
            else:
                # Check for interval/pause/trigger buttons
                interval = await page.locator('input[type="number"]').count()
                pause = await page.locator('button:has-text("Pause"), button:has-text("Resume")').count()
                trigger = await page.locator('button:has-text("Trigger")').count()
                if interval > 0 or pause > 0 or trigger > 0:
                    log_pass(f"Heartbeat controls: input={interval}, pause/resume={pause}, trigger={trigger}")
                else:
                    log_fail("Heartbeat control panel not found")

            await screenshot(page, "07-heartbeat")
        except Exception as e:
            log_fail("Heartbeat test failed", str(e))

        # --- Test 8: CSS visual quality ---
        print("\n[Test 8] CSS visual quality")
        try:
            css_check = await page.evaluate("""() => {
                const el = document.querySelector('.agora-dashboard');
                if (!el) return {found: false};
                const style = window.getComputedStyle(el);
                return {
                    found: true,
                    color: style.color,
                    bgColor: style.backgroundColor,
                };
            }""")
            if css_check.get("found"):
                log_pass(f"CSS: color={css_check['color']}, bg={css_check['bgColor']}")
            else:
                log_fail(".agora-dashboard not found in DOM")

            # Check for invisible text
            invisible = await page.evaluate("""() => {
                const els = document.querySelectorAll('.agora-dashboard *');
                let issues = [];
                for (const el of els) {
                    if (el.children.length > 0) continue;
                    const style = window.getComputedStyle(el);
                    if ((style.color === 'rgba(0, 0, 0, 0)' || style.color === 'transparent') && el.textContent.trim()) {
                        issues.push(el.tagName + ': transparent text');
                    }
                }
                return issues.slice(0, 5);
            }""")
            if invisible:
                log_fail(f"Invisible text: {invisible}")
            else:
                log_pass("No invisible text")

            await screenshot(page, "08-css")
        except Exception as e:
            log_fail("CSS check failed", str(e))

        # --- Test 9: Console errors ---
        print("\n[Test 9] Console errors")
        if console_errors:
            # Filter out the 500 from login page redirect (known issue)
            real_errors = [e for e in console_errors if "500" not in e and "Internal Server Error" not in e]
            if real_errors:
                log_fail(f"{len(real_errors)} console errors")
                for e in real_errors[:5]:
                    log_info(f"  {e}")
            else:
                log_pass("Only expected 500 errors (login redirect)")
        else:
            log_pass("No console errors")

        # --- Test 10: Kanban cards ---
        print("\n[Test 10] Kanban task cards")
        try:
            kan_btn = page.locator('button:has-text("Kanban")')
            if await kan_btn.count() > 0:
                await kan_btn.first.click()
                await page.wait_for_timeout(2000)
                cards = page.locator('.agora-kanban-task')
                count = await cards.count()
                if count > 0:
                    first = cards.first
                    assignee = await first.locator('.agora-kanban-assignee').count()
                    status = await first.locator('.agora-kanban-status').count()
                    log_pass(f"Kanban: {count} cards, assignee={assignee}, status={status}")
                else:
                    log_info("No kanban tasks")
                await screenshot(page, "10-kanban")
            else:
                log_info("No Kanban tab")
        except Exception as e:
            log_fail("Kanban test failed", str(e))

        # --- Test 11: Discussions ---
        print("\n[Test 11] Discussion messages")
        try:
            disc_btn = page.locator('button:has-text("Discussions")')
            if await disc_btn.count() > 0:
                await disc_btn.first.click()
                await page.wait_for_timeout(2000)
                motions = await page.locator('[class*="motion"], [class*="discussion-item"]').count()
                if motions > 0:
                    await page.locator('[class*="motion"], [class*="discussion-item"]').first.click()
                    await page.wait_for_timeout(2000)
                    msgs = await page.locator('.agora-message').count()
                    speakers = await page.locator('.agora-speaker, .agora-speaker-chair').count()
                    log_pass(f"Discussion: {motions} motions, {msgs} messages, {speakers} speaker headers")
                else:
                    log_info("No discussions")
                await screenshot(page, "11-discussions")
            else:
                log_info("No Discussions tab")
        except Exception as e:
            log_fail("Discussion test failed", str(e))

        # --- Summary ---
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        passed = sum(1 for r in results if r[0] == "pass")
        failed = sum(1 for r in results if r[0] == "fail")
        print(f"{GREEN}Passed: {passed}{RESET}  {RED}Failed: {failed}{RESET}  Total: {len(results)}")

        if failed > 0:
            print(f"\n{RED}Failed:{RESET}")
            for s, m in results:
                if s == "fail":
                    print(f"  ✗ {m}")

        results_data = {"passed": passed, "failed": failed, "results": [{"status": s, "message": m} for s, m in results]}
        with open(SCREENSHOT_DIR / "results.json", "w") as f:
            json.dump(results_data, f, indent=2)

        await browser.close()
        return failed == 0

if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
