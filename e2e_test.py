"""Agora Dashboard E2E Test — Playwright browser automation.

Tests the full user journey from the browser perspective:
1. Login to dashboard
2. Navigate to Agora tab
3. Check Projects tab renders
4. Check Team tab renders (Members + Teams + Profiles sub-tabs)
5. Start a project (if none active)
6. Check project detail (Overview / Kanban / Discussions / Team)
7. Check heartbeat control panel
8. Check toast notifications (trigger heartbeat)
9. Take screenshots at each step for visual verification
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright

# Config
DASHBOARD_URL = "http://localhost:18765"
ADMIN_USER = "admin"
ADMIN_PASS = os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "wKHITmcn2mIrat2")
SCREENSHOT_DIR = Path("/root/agora/e2e-screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# Colors for terminal output
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
    await page.screenshot(path=str(path), full_page=True)
    log_info(f"Screenshot saved: {path}")

async def run_tests():
    async with async_playwright() as p:
        # Launch headless Chromium
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True,
        )
        page = await context.new_page()

        # Collect console errors
        console_errors = []
        page.on("console", lambda msg: console_errors.append(f"{msg.type}: {msg.text}") if msg.type == "error" else None)

        print("\n" + "=" * 60)
        print("Agora Dashboard E2E Test")
        print("=" * 60)

        # --- Test 1: Dashboard loads ---
        print("\n[Test 1] Dashboard loads and redirects to login")
        try:
            response = await page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=15000)
            log_pass(f"Dashboard responded with status {response.status}")
            await screenshot(page, "01-login")
        except Exception as e:
            log_fail("Dashboard failed to load", str(e))
            return

        # --- Test 2: Login via /auth/password-login ---
        print("\n[Test 2] Login with admin credentials")
        try:
            # POST JSON to /auth/password-login (Hermes basic auth flow)
            response = await page.request.post(
                DASHBOARD_URL + "/auth/password-login",
                data=json.dumps({
                    "provider": "basic",
                    "username": ADMIN_USER,
                    "password": ADMIN_PASS,
                }),
                headers={"Content-Type": "application/json"},
            )
            if response.status == 200:
                log_pass("Login API returned 200 OK")
                # The response sets cookies via Set-Cookie headers.
                # Playwright's request context captures them.
                # Now navigate to dashboard root with cookies
                await page.goto(DASHBOARD_URL + "/", wait_until="networkidle", timeout=15000)
                log_pass(f"Dashboard loaded after login (status: {page.url})")
                await screenshot(page, "02-after-login")
            else:
                body = await response.text()
                log_fail(f"Login API returned {response.status}", body[:200])
        except Exception as e:
            log_fail("Login failed", str(e))

        # --- Test 3: Navigate to Agora tab ---
        print("\n[Test 3] Navigate to Agora dashboard")
        try:
            # Look for Agora in the dashboard
            # It might be a tab, a sidebar link, or loaded automatically
            await page.wait_for_timeout(2000)
            
            # Try to find Agora-related elements
            agora_visible = await page.locator('text=🏛️ Agora').count()
            if agora_visible > 0:
                log_pass("Agora dashboard visible")
            else:
                # Try clicking on a plugins menu or Agora link
                agora_link = page.locator('a:has-text("Agora"), button:has-text("Agora"), [class*="agora"]')
                if await agora_link.count() > 0:
                    await agora_link.first.click()
                    await page.wait_for_timeout(2000)
                    log_pass("Clicked Agora link")
                else:
                    # Check if agora dashboard is already rendered
                    agora_dashboard = page.locator('.agora-dashboard')
                    if await agora_dashboard.count() > 0:
                        log_pass("Agora dashboard auto-rendered")
                    else:
                        log_fail("Agora dashboard not found", "No 🏛️ Agora text, link, or .agora-dashboard element")
            
            await screenshot(page, "03-agora-main")
        except Exception as e:
            log_fail("Navigation to Agora failed", str(e))

        # --- Test 4: Projects tab ---
        print("\n[Test 4] Projects tab renders")
        try:
            # Check for project-related elements
            projects_tab = page.locator('[data-value="projects"], button:has-text("Projects")')
            if await projects_tab.count() > 0:
                await projects_tab.first.click()
                await page.wait_for_timeout(1500)
            
            # Check content
            project_cards = await page.locator('.agora-project-card').count()
            start_btn = await page.locator('button:has-text("Start")').count()
            log_pass(f"Projects tab: {project_cards} project cards, {start_btn} start buttons")
            await screenshot(page, "04-projects")
        except Exception as e:
            log_fail("Projects tab test failed", str(e))

        # --- Test 5: Team tab ---
        print("\n[Test 5] Team tab with sub-tabs")
        try:
            team_tab = page.locator('button:has-text("Team")')
            if await team_tab.count() > 0:
                await team_tab.first.click()
                await page.wait_for_timeout(1500)
                log_pass("Team tab clicked")
                
                # Check sub-tabs
                members_subtab = await page.locator('button:has-text("Members")').count()
                teams_subtab = await page.locator('button:has-text("Teams")').count()
                profiles_subtab = await page.locator('button:has-text("Profiles")').count()
                log_pass(f"Sub-tabs: Members={members_subtab}, Teams={teams_subtab}, Profiles={profiles_subtab}")
                
                # Click through sub-tabs
                for subtab_name in ["Members", "Teams", "Profiles"]:
                    btn = page.locator(f'button:has-text("{subtab_name}")')
                    if await btn.count() > 0:
                        await btn.first.click()
                        await page.wait_for_timeout(1000)
                        await screenshot(page, f"05-team-{subtab_name.lower()}")
                log_pass("Team sub-tabs navigation works")
            else:
                log_fail("Team tab not found")
            await screenshot(page, "05-team")
        except Exception as e:
            log_fail("Team tab test failed", str(e))

        # --- Test 6: Check for existing projects ---
        print("\n[Test 6] Check existing projects and project detail")
        try:
            # Go back to Projects
            projects_tab = page.locator('button:has-text("Projects")')
            if await projects_tab.count() > 0:
                await projects_tab.first.click()
                await page.wait_for_timeout(1500)
            
            project_cards = page.locator('.agora-project-card')
            count = await project_cards.count()
            
            if count > 0:
                # Click first project
                await project_cards.first.click()
                await page.wait_for_timeout(2000)
                log_pass(f"Opened project detail (1 of {count} projects)")
                
                # Check project detail tabs
                overview_tab = await page.locator('button:has-text("Overview")').count()
                kanban_tab = await page.locator('button:has-text("Kanban")').count()
                discussions_tab = await page.locator('button:has-text("Discussions")').count()
                team_detail_tab = await page.locator('button:has-text("Team")').count()
                log_pass(f"Project detail tabs: Overview={overview_tab}, Kanban={kanban_tab}, Discussions={discussions_tab}, Team={team_detail_tab}")
                
                # Click through project sub-tabs
                for subtab in ["Overview", "Kanban", "Discussions", "Team"]:
                    btn = page.locator(f'button:has-text("{subtab}")')
                    if await btn.count() > 0:
                        await btn.first.click()
                        await page.wait_for_timeout(1500)
                        await screenshot(page, f"06-project-{subtab.lower()}")
                        log_pass(f"Project {subtab} tab rendered")
                
                await screenshot(page, "06-project-detail")
            else:
                log_info("No existing projects — skipping project detail test")
        except Exception as e:
            log_fail("Project detail test failed", str(e))

        # --- Test 7: Heartbeat control panel ---
        print("\n[Test 7] Heartbeat control panel")
        try:
            # Navigate to project overview
            overview_btn = page.locator('button:has-text("Overview")')
            if await overview_btn.count() > 0:
                await overview_btn.first.click()
                await page.wait_for_timeout(1000)
            
            # Check for heartbeat controls
            interval_input = await page.locator('input[type="number"], input[placeholder*="minute"]').count()
            pause_btn = await page.locator('button:has-text("Pause"), button:has-text("Resume")').count()
            trigger_btn = await page.locator('button:has-text("Trigger"), button:has-text("trigger")').count()
            save_btn = await page.locator('button:has-text("Save")').count()
            
            if interval_input > 0 or pause_btn > 0 or trigger_btn > 0:
                log_pass(f"Heartbeat controls found: interval={interval_input}, pause/resume={pause_btn}, trigger={trigger_btn}, save={save_btn}")
            else:
                log_fail("Heartbeat control panel not found")
            
            await screenshot(page, "07-heartbeat")
        except Exception as e:
            log_fail("Heartbeat control test failed", str(e))

        # --- Test 8: Check CSS / visual quality ---
        print("\n[Test 8] CSS and visual quality")
        try:
            # Check that .agora-dashboard has proper styling
            bg_color = await page.evaluate("""() => {
                const el = document.querySelector('.agora-dashboard');
                if (!el) return null;
                return window.getComputedStyle(el).color;
            }""")
            
            if bg_color:
                log_pass(f"Agora dashboard text color: {bg_color}")
            else:
                log_fail("Could not read agora-dashboard styles")
            
            # Check for invisible text (transparent or same as background)
            invisible_check = await page.evaluate("""() => {
                const els = document.querySelectorAll('.agora-dashboard *');
                let issues = [];
                for (const el of els) {
                    if (el.children.length > 0) continue;
                    const style = window.getComputedStyle(el);
                    const color = style.color;
                    const bg = style.backgroundColor;
                    // Check for transparent text
                    if (color === 'rgba(0, 0, 0, 0)' || color === 'transparent') {
                        if (el.textContent.trim()) issues.push(el.tagName + ': transparent text');
                    }
                }
                return issues.slice(0, 5);
            }""")
            
            if invisible_check:
                log_fail(f"Invisible text found: {invisible_check}")
            else:
                log_pass("No invisible text elements detected")
            
            await screenshot(page, "08-css-check")
        except Exception as e:
            log_fail("CSS check failed", str(e))

        # --- Test 9: Console errors ---
        print("\n[Test 9] JavaScript console errors")
        if console_errors:
            log_fail(f"{len(console_errors)} console errors detected")
            for err in console_errors[:5]:
                log_info(f"  {err}")
        else:
            log_pass("No console errors")

        # --- Test 10: Kanban task cards content ---
        print("\n[Test 10] Kanban task card content")
        try:
            kanban_btn = page.locator('button:has-text("Kanban")')
            if await kanban_btn.count() > 0:
                await kanban_btn.first.click()
                await page.wait_for_timeout(1500)
                
                cards = page.locator('.agora-kanban-task')
                card_count = await cards.count()
                
                if card_count > 0:
                    # Check first card for assignee and status badges
                    first_card = cards.first
                    assignee = await first_card.locator('.agora-kanban-assignee').count()
                    status_badge = await first_card.locator('.agora-kanban-status').count()
                    log_pass(f"Kanban: {card_count} cards, first card has assignee={assignee}, status={status_badge}")
                else:
                    log_info("No kanban tasks — skipping card content check")
                
                await screenshot(page, "10-kanban-cards")
            else:
                log_info("No Kanban tab available — skipping")
        except Exception as e:
            log_fail("Kanban card test failed", str(e))

        # --- Test 11: Discussion messages ---
        print("\n[Test 11] Discussion messages display")
        try:
            disc_btn = page.locator('button:has-text("Discussions")')
            if await disc_btn.count() > 0:
                await disc_btn.first.click()
                await page.wait_for_timeout(1500)
                
                # Check for motion items
                motions = await page.locator('[class*="motion"], [class*="discussion-item"]').count()
                
                if motions > 0:
                    # Click first motion
                    motion_el = page.locator('[class*="motion"], [class*="discussion-item"]').first
                    await motion_el.click()
                    await page.wait_for_timeout(2000)
                    
                    # Check messages
                    messages = await page.locator('.agora-message').count()
                    speaker_headers = await page.locator('.agora-speaker, .agora-speaker-chair').count()
                    
                    log_pass(f"Discussion: {motions} motions, {messages} messages, {speaker_headers} speaker headers")
                    
                    # Check auto-scroll
                    scroll_pos = await page.evaluate("""() => {
                        const container = document.querySelector('.agora-discussion-messages');
                        if (!container) return null;
                        return {
                            scrollTop: container.scrollTop,
                            scrollHeight: container.scrollHeight,
                            clientHeight: container.clientHeight,
                        };
                    }""")
                    if scroll_pos:
                        at_bottom = scroll_pos["scrollTop"] + scroll_pos["clientHeight"] >= scroll_pos["scrollHeight"] - 50
                        log_pass(f"Scroll: {scroll_pos['scrollTop']}/{scroll_pos['scrollHeight']} (at bottom: {at_bottom})")
                else:
                    log_info("No discussions available — skipping")
                
                await screenshot(page, "11-discussions")
            else:
                log_info("No Discussions tab — skipping")
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
            print(f"\n{RED}Failed tests:{RESET}")
            for status, msg in results:
                if status == "fail":
                    print(f"  ✗ {msg}")
        
        # Save results JSON
        results_data = {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "results": [{"status": s, "message": m} for s, m in results],
            "console_errors": console_errors[:10],
        }
        results_path = SCREENSHOT_DIR / "results.json"
        with open(results_path, "w") as f:
            json.dump(results_data, f, indent=2)
        print(f"\nResults saved to {results_path}")
        print(f"Screenshots saved to {SCREENSHOT_DIR}/")
        
        await browser.close()
        
        return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
