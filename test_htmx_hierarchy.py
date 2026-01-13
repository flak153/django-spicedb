#!/usr/bin/env python3
"""
Comprehensive QA Test Script for HTMX-powered Hierarchy UI

This script tests the complete user flow for the hierarchy management interface,
validating HTMX functionality, UI interactions, and user experience.
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright, Page, Browser, ConsoleMessage


class HTMXHierarchyQATest:
    """QA test suite for HTMX hierarchy UI."""

    def __init__(self):
        self.base_url = "http://localhost:8000"
        self.screenshots_dir = Path("/tmp/qa_screenshots")
        self.screenshots_dir.mkdir(exist_ok=True)
        self.test_results = {
            "timestamp": datetime.now().isoformat(),
            "test_steps": [],
            "console_errors": [],
            "console_warnings": [],
            "console_logs": [],
            "passed": 0,
            "failed": 0,
            "total": 0,
        }
        self.browser = None
        self.page = None

    def log_step(self, step_name: str, status: str, details: str = ""):
        """Log a test step with status."""
        step = {
            "step": step_name,
            "status": status,
            "details": details,
            "timestamp": datetime.now().isoformat(),
        }
        self.test_results["test_steps"].append(step)
        self.test_results["total"] += 1

        if status == "PASS":
            self.test_results["passed"] += 1
            print(f"✓ {step_name}: {status} - {details}")
        elif status == "FAIL":
            self.test_results["failed"] += 1
            print(f"✗ {step_name}: {status} - {details}")
        else:
            print(f"• {step_name}: {status} - {details}")

    def handle_console(self, msg: ConsoleMessage):
        """Capture browser console messages."""
        msg_type = msg.type
        text = msg.text
        location = f"{msg.location.get('url', '')}:{msg.location.get('lineNumber', '')}"

        entry = {
            "type": msg_type,
            "text": text,
            "location": location,
            "timestamp": datetime.now().isoformat(),
        }

        if msg_type == "error":
            self.test_results["console_errors"].append(entry)
            print(f"  [CONSOLE ERROR] {text}")
        elif msg_type == "warning":
            self.test_results["console_warnings"].append(entry)
            print(f"  [CONSOLE WARN] {text}")
        else:
            self.test_results["console_logs"].append(entry)

    async def take_screenshot(self, name: str, page: Page = None):
        """Take a screenshot and save it."""
        if page is None:
            page = self.page
        screenshot_path = self.screenshots_dir / f"{name}.png"
        await page.screenshot(path=str(screenshot_path), full_page=True)
        self.log_step(f"Screenshot: {name}", "INFO", f"Saved to {screenshot_path}")
        return screenshot_path

    async def wait_for_htmx(self, page: Page = None):
        """Wait for HTMX to complete any pending requests."""
        if page is None:
            page = self.page
        await page.evaluate("() => new Promise(resolve => htmx.on('htmx:afterSettle', resolve))")
        await page.wait_for_timeout(500)  # Additional buffer

    async def verify_no_page_reload(self, page: Page = None):
        """Verify that the page didn't perform a full reload by checking navigation timing."""
        if page is None:
            page = self.page
        # Check if page has navigation timing API (would reset on full reload)
        performance = await page.evaluate("""() => {
            return {
                navigationStart: window.performance.timing.navigationStart,
                loadEventEnd: window.performance.timing.loadEventEnd
            };
        }""")
        return performance

    async def setup(self):
        """Set up the browser and page."""
        self.log_step("Setup Browser", "INFO", "Initializing Playwright browser")
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=False)
        self.page = await self.browser.new_page()
        self.page.on("console", self.handle_console)
        self.page.set_default_timeout(30000)  # 30 second timeout
        self.log_step("Setup Browser", "PASS", "Browser ready")

    async def test_step_1_login(self):
        """Step 1: Navigate to login page and authenticate."""
        self.log_step("Step 1: Login", "INFO", "Navigating to login page")

        try:
            await self.page.goto(f"{self.base_url}/accounts/login/")
            await self.page.wait_for_load_state("networkidle")

            # Verify login page loaded
            if "login" in (await self.page.title()).lower() or await self.page.locator('input[name="username"]').count() > 0:
                self.log_step("Step 1: Login Page Load", "PASS", "Login page loaded successfully")
            else:
                self.log_step("Step 1: Login Page Load", "FAIL", "Login page did not load correctly")
                return False

            # Fill in credentials
            await self.page.fill('input[name="username"]', "admin")
            await self.page.fill('input[name="password"]', "admin")

            # Click login button
            await self.page.click('button[type="submit"], input[type="submit"]')
            await self.page.wait_for_load_state("networkidle")

            # Verify login success (check for redirect or logout link)
            current_url = self.page.url
            if "/login/" not in current_url:
                self.log_step("Step 1: Authentication", "PASS", f"Logged in successfully, redirected to {current_url}")
                return True
            else:
                self.log_step("Step 1: Authentication", "FAIL", "Login failed, still on login page")
                return False
        except Exception as e:
            self.log_step("Step 1: Login", "FAIL", f"Exception: {str(e)}")
            return False

    async def test_step_2_hierarchy_tree(self):
        """Step 2-4: Navigate to hierarchy tree and verify display."""
        self.log_step("Step 2: Hierarchy Tree", "INFO", "Navigating to hierarchy tree page")

        try:
            await self.page.goto(f"{self.base_url}/rebac/5/hierarchy/")
            await self.page.wait_for_load_state("networkidle")

            # Verify hierarchy tree is present
            tree_nodes = await self.page.locator(".tree-node, .hierarchy-tree li").count()
            if tree_nodes > 0:
                self.log_step("Step 2: Tree Structure", "PASS", f"Hierarchy tree displays {tree_nodes} nodes")
            else:
                self.log_step("Step 2: Tree Structure", "FAIL", "No hierarchy nodes found")
                return False

            # Check for specific expected nodes
            page_content = await self.page.content()
            expected_nodes = ["Acme Corp HQ", "Engineering", "Sales"]
            found_nodes = [node for node in expected_nodes if node in page_content]

            if len(found_nodes) >= 2:
                self.log_step("Step 2: Expected Nodes", "PASS", f"Found nodes: {', '.join(found_nodes)}")
            else:
                self.log_step("Step 2: Expected Nodes", "FAIL", f"Only found {len(found_nodes)} expected nodes")

            # Take screenshot
            await self.take_screenshot("01_hierarchy_tree")

            return True
        except Exception as e:
            self.log_step("Step 2: Hierarchy Tree", "FAIL", f"Exception: {str(e)}")
            return False

    async def test_step_3_node_detail(self):
        """Step 5-6: Click on Acme Corp HQ and verify node detail page."""
        self.log_step("Step 3: Node Detail", "INFO", "Clicking on Acme Corp HQ")

        try:
            # Find and click the Acme Corp HQ link
            acme_link = self.page.locator('a:has-text("Acme Corp HQ")').first
            if await acme_link.count() > 0:
                await acme_link.click()
                await self.page.wait_for_load_state("networkidle")
                self.log_step("Step 3: Click Node", "PASS", "Clicked Acme Corp HQ successfully")
            else:
                self.log_step("Step 3: Click Node", "FAIL", "Could not find Acme Corp HQ link")
                return False

            # Verify we're on the node detail page
            await self.page.wait_for_selector("h1:has-text('Acme Corp HQ')", timeout=5000)

            # Check for roles section
            roles_section = await self.page.locator("h2:has-text('Role Assignments')").count()
            if roles_section > 0:
                self.log_step("Step 3: Roles Section", "PASS", "Role assignments section is present")
            else:
                self.log_step("Step 3: Roles Section", "FAIL", "Role assignments section not found")

            # Wait for HTMX to load roles
            await self.page.wait_for_selector("#roles-list table, #roles-list .empty-state", timeout=10000)

            # Take screenshot
            await self.take_screenshot("02_node_detail_with_roles")

            return True
        except Exception as e:
            self.log_step("Step 3: Node Detail", "FAIL", f"Exception: {str(e)}")
            await self.take_screenshot("02_node_detail_error")
            return False

    async def test_step_4_add_role_form(self):
        """Step 7-8: Click Add Role button and verify form appears."""
        self.log_step("Step 4: Add Role Form", "INFO", "Clicking Add Role button")

        try:
            # Find and click the Add Role button
            add_role_btn = self.page.locator('button:has-text("Add Role")').first
            if await add_role_btn.count() > 0:
                await add_role_btn.click()
                await self.page.wait_for_timeout(500)  # Wait for animation
                self.log_step("Step 4: Click Add Role", "PASS", "Add Role button clicked")
            else:
                self.log_step("Step 4: Click Add Role", "FAIL", "Add Role button not found (may lack manage permission)")
                return False

            # Verify form is visible
            form_visible = await self.page.locator("#add-role-form").is_visible()
            if form_visible:
                self.log_step("Step 4: Form Visibility", "PASS", "Add role form is now visible")
            else:
                self.log_step("Step 4: Form Visibility", "FAIL", "Add role form did not appear")
                return False

            # Verify form fields are present
            user_select = await self.page.locator('select[name="user_id"]').count()
            role_select = await self.page.locator('select[name="role"]').count()

            if user_select > 0 and role_select > 0:
                self.log_step("Step 4: Form Fields", "PASS", "User and role select fields are present")
            else:
                self.log_step("Step 4: Form Fields", "FAIL", "Form fields are missing")

            return True
        except Exception as e:
            self.log_step("Step 4: Add Role Form", "FAIL", f"Exception: {str(e)}")
            return False

    async def test_step_5_assign_role_htmx(self):
        """Step 9-10: Assign role and verify HTMX update without page reload."""
        self.log_step("Step 5: Assign Role (HTMX)", "INFO", "Assigning diana as admin")

        try:
            # Store initial navigation timing to detect full page reload
            initial_timing = await self.verify_no_page_reload()
            initial_url = self.page.url

            # Count initial roles
            initial_role_rows = await self.page.locator("#roles-list tbody tr.role-row").count()
            self.log_step("Step 5: Initial State", "INFO", f"Found {initial_role_rows} existing roles")

            # Select user (diana)
            user_options = await self.page.locator('select[name="user_id"] option').all_inner_texts()
            diana_option = [opt for opt in user_options if "diana" in opt.lower()]

            if diana_option:
                await self.page.select_option('select[name="user_id"]', label=diana_option[0])
                self.log_step("Step 5: Select User", "PASS", f"Selected user: {diana_option[0]}")
            else:
                # Try to select any available user
                await self.page.select_option('select[name="user_id"]', index=1)
                selected_user = await self.page.locator('select[name="user_id"]').input_value()
                self.log_step("Step 5: Select User", "INFO", f"Diana not found, selected user ID: {selected_user}")

            # Select role (admin)
            await self.page.select_option('select[name="role"]', value="admin")
            self.log_step("Step 5: Select Role", "PASS", "Selected role: admin")

            # Submit form via HTMX
            submit_btn = self.page.locator('#add-role-form button[type="submit"]')
            await submit_btn.click()

            # Wait for HTMX request to complete
            await self.page.wait_for_selector(".htmx-request", state="detached", timeout=5000)
            await self.page.wait_for_timeout(1000)  # Buffer for DOM updates

            # Verify no full page reload occurred
            final_timing = await self.verify_no_page_reload()
            final_url = self.page.url

            if initial_timing["navigationStart"] == final_timing["navigationStart"] and initial_url == final_url:
                self.log_step("Step 5: No Page Reload", "PASS", "Page did NOT reload (HTMX worked correctly)")
            else:
                self.log_step("Step 5: No Page Reload", "FAIL", "Full page reload detected")

            # Verify new role was added
            await self.page.wait_for_timeout(500)
            final_role_rows = await self.page.locator("#roles-list tbody tr.role-row").count()

            if final_role_rows > initial_role_rows:
                self.log_step("Step 5: Role Added", "PASS", f"New role added ({initial_role_rows} -> {final_role_rows})")
            else:
                self.log_step("Step 5: Role Added", "FAIL", f"Role count unchanged ({initial_role_rows})")

            # Verify form is hidden
            form_visible = await self.page.locator("#add-role-form").is_visible()
            if not form_visible:
                self.log_step("Step 5: Form Hidden", "PASS", "Form automatically hidden after submission")
            else:
                self.log_step("Step 5: Form Hidden", "INFO", "Form is still visible")

            # Check for toast notification
            toast_visible = await self.page.locator(".toast").count()
            if toast_visible > 0:
                toast_text = await self.page.locator(".toast").first.inner_text()
                self.log_step("Step 5: Toast Notification", "PASS", f"Toast shown: {toast_text}")
            else:
                self.log_step("Step 5: Toast Notification", "INFO", "No toast notification detected")

            # Take screenshot
            await self.take_screenshot("03_after_role_assignment")

            return True
        except Exception as e:
            self.log_step("Step 5: Assign Role (HTMX)", "FAIL", f"Exception: {str(e)}")
            await self.take_screenshot("03_assign_role_error")
            return False

    async def test_step_6_remove_role_htmx(self):
        """Step 11-13: Remove role and verify HTMX update without page reload."""
        self.log_step("Step 6: Remove Role (HTMX)", "INFO", "Removing the newly added role")

        try:
            # Store initial state
            initial_timing = await self.verify_no_page_reload()
            initial_url = self.page.url
            initial_role_rows = await self.page.locator("#roles-list tbody tr.role-row").count()

            # Find the remove button for the last role (most recently added)
            remove_buttons = self.page.locator("button:has-text('Remove')")
            remove_count = await remove_buttons.count()

            if remove_count > 0:
                self.log_step("Step 6: Find Remove Button", "PASS", f"Found {remove_count} remove buttons")

                # Click the last remove button
                last_remove_btn = remove_buttons.last

                # Set up dialog handler for confirmation
                dialog_shown = False

                async def handle_dialog(dialog):
                    nonlocal dialog_shown
                    dialog_shown = True
                    self.log_step("Step 6: Confirmation Dialog", "PASS", f"Dialog shown: {dialog.message}")
                    await dialog.accept()

                self.page.on("dialog", handle_dialog)

                # Click remove button
                await last_remove_btn.click()
                await self.page.wait_for_timeout(1000)

                # Note: HTMX uses hx-confirm which may not trigger browser dialog
                # Check if HTMX handled it with custom confirm
                if not dialog_shown:
                    self.log_step("Step 6: Confirmation Dialog", "INFO", "No browser dialog (HTMX may use custom confirm)")

                # Wait for HTMX request to complete
                await self.page.wait_for_selector(".htmx-request", state="detached", timeout=5000)
                await self.page.wait_for_timeout(1000)

                # Verify no full page reload
                final_timing = await self.verify_no_page_reload()
                final_url = self.page.url

                if initial_timing["navigationStart"] == final_timing["navigationStart"] and initial_url == final_url:
                    self.log_step("Step 6: No Page Reload", "PASS", "Page did NOT reload (HTMX worked correctly)")
                else:
                    self.log_step("Step 6: No Page Reload", "FAIL", "Full page reload detected")

                # Verify role was removed
                final_role_rows = await self.page.locator("#roles-list tbody tr.role-row").count()

                if final_role_rows < initial_role_rows:
                    self.log_step("Step 6: Role Removed", "PASS", f"Role removed ({initial_role_rows} -> {final_role_rows})")
                else:
                    self.log_step("Step 6: Role Removed", "FAIL", f"Role count unchanged ({initial_role_rows})")

            else:
                self.log_step("Step 6: Find Remove Button", "FAIL", "No remove buttons found")
                return False

            # Take final screenshot
            await self.take_screenshot("04_after_role_removal")

            return True
        except Exception as e:
            self.log_step("Step 6: Remove Role (HTMX)", "FAIL", f"Exception: {str(e)}")
            await self.take_screenshot("04_remove_role_error")
            return False

    async def test_step_7_console_check(self):
        """Step 14: Check browser console for errors."""
        self.log_step("Step 7: Console Check", "INFO", "Analyzing browser console output")

        error_count = len(self.test_results["console_errors"])
        warning_count = len(self.test_results["console_warnings"])

        if error_count == 0:
            self.log_step("Step 7: Console Errors", "PASS", "No console errors detected")
        else:
            self.log_step("Step 7: Console Errors", "FAIL", f"{error_count} console errors found")

        if warning_count == 0:
            self.log_step("Step 7: Console Warnings", "PASS", "No console warnings detected")
        else:
            self.log_step("Step 7: Console Warnings", "INFO", f"{warning_count} console warnings found")

        return error_count == 0

    async def cleanup(self):
        """Clean up resources."""
        self.log_step("Cleanup", "INFO", "Closing browser")
        if self.browser:
            await self.browser.close()
        self.log_step("Cleanup", "PASS", "Browser closed")

    async def run_all_tests(self):
        """Run all test steps in sequence."""
        print("\n" + "="*80)
        print("HTMX Hierarchy UI - Comprehensive QA Test Suite")
        print("="*80 + "\n")

        try:
            await self.setup()

            # Run test steps in sequence
            if not await self.test_step_1_login():
                print("\n❌ Login failed, cannot proceed with remaining tests")
                return

            if not await self.test_step_2_hierarchy_tree():
                print("\n❌ Hierarchy tree test failed, cannot proceed")
                return

            if not await self.test_step_3_node_detail():
                print("\n⚠️  Node detail test failed, attempting to continue")

            if not await self.test_step_4_add_role_form():
                print("\n⚠️  Add role form test failed, skipping role assignment tests")
            else:
                await self.test_step_5_assign_role_htmx()
                await self.test_step_6_remove_role_htmx()

            await self.test_step_7_console_check()

        finally:
            await self.cleanup()
            self.generate_report()

    def generate_report(self):
        """Generate final test report."""
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        print(f"Total Tests: {self.test_results['total']}")
        print(f"Passed: {self.test_results['passed']}")
        print(f"Failed: {self.test_results['failed']}")
        print(f"Console Errors: {len(self.test_results['console_errors'])}")
        print(f"Console Warnings: {len(self.test_results['console_warnings'])}")

        if self.test_results['failed'] == 0:
            print("\n✅ ALL TESTS PASSED")
        else:
            print(f"\n❌ {self.test_results['failed']} TESTS FAILED")

        # Save JSON report
        report_path = self.screenshots_dir / "test_report.json"
        with open(report_path, "w") as f:
            json.dump(self.test_results, f, indent=2)

        print(f"\nScreenshots saved to: {self.screenshots_dir}")
        print(f"Full report saved to: {report_path}")
        print("="*80 + "\n")


async def main():
    """Main entry point."""
    test = HTMXHierarchyQATest()
    await test.run_all_tests()

    # Exit with appropriate code
    sys.exit(0 if test.test_results['failed'] == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
