import asyncio
import base64
import logging
import random
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from pydantic import BaseModel
from playwright.async_api import Page, Frame

from ironcore.browser.mouse_engine import MouseEngine

logger = logging.getLogger(__name__)


class GeeTestSolverResult(BaseModel):
    success: bool
    offset_x: Optional[float]
    confidence: float
    method_used: str       # "opencv_template", "vlm_fallback"
    attempts: int
    processing_time_ms: float
    error: Optional[str] = None


# Default selectors for GeeTest v3 and v4
GEETEST_V3_SELECTORS = {
    "background": ".geetest_canvas_bg",
    "piece": ".geetest_canvas_slice",
    "slider_button": ".geetest_slider_button",
    "success": ".geetest_success_animate",
    "fail": ".geetest_fail_animate",
}
GEETEST_V4_SELECTORS = {
    "background": ".geetest_bg",
    "piece": ".geetest_slice_bg",
    "slider_button": ".geetest_arrow",
    "success": ".geetest_result_success",
    "fail": ".geetest_result_fail",
}


class GeeTestCapturer:
    @staticmethod
    async def capture_background(page: Page, bg_selector: str = GEETEST_V3_SELECTORS["background"]) -> bytes:
        """Screenshot the background canvas/image of GeeTest."""
        element = await page.wait_for_selector(bg_selector, timeout=8000)
        if not element:
            raise ValueError(f"Background element not found: {bg_selector}")
        return await element.screenshot()

    @staticmethod
    async def capture_piece(page: Page, piece_selector: str = GEETEST_V3_SELECTORS["piece"]) -> bytes:
        """Screenshot the puzzle piece of GeeTest."""
        element = await page.wait_for_selector(piece_selector, timeout=8000)
        if not element:
            raise ValueError(f"Piece element not found: {piece_selector}")
        return await element.screenshot()

    @staticmethod
    async def check_success(page: Page, success_selector: str = GEETEST_V3_SELECTORS["success"],
                            fail_selector: str = GEETEST_V3_SELECTORS["fail"],
                            timeout: float = 3000.0) -> Optional[bool]:
        """
        Wait for success or fail animations after drag.
        Returns True on success, False on fail, None if neither appears.
        """
        try:
            # Race between success and fail elements appearing
            result = await page.wait_for_function(
                f"""
                () => {{
                    const success = document.querySelector('{success_selector}');
                    const fail = document.querySelector('{fail_selector}');
                    if (success && success.offsetParent !== null) return 'success';
                    if (fail && fail.offsetParent !== null) return 'fail';
                    return null;
                }}
                """,
                timeout=timeout
            )
            state = await result.json_value()
            return state == 'success'
        except Exception:
            return None


class OpenCVSolver:
    @staticmethod
    def preprocess_image(image_bytes: bytes) -> np.ndarray:
        """Decode bytes to BGR numpy array."""
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Failed to decode image bytes into numpy array")
        return img

    @staticmethod
    def apply_canny(img: np.ndarray, low: int = 50, high: int = 150) -> np.ndarray:
        """Convert to grayscale and apply Canny edge detection."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Add slight blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, low, high)
        return edges

    @classmethod
    def find_slider_offset(
        cls,
        background_bytes: bytes,
        piece_bytes: bytes,
        method: int = cv2.TM_CCOEFF_NORMED,
    ) -> Tuple[float, float]:
        """
        Extract images, find edges, and match template to find the X-offset.
        """
        bg_img = cls.preprocess_image(background_bytes)
        piece_img = cls.preprocess_image(piece_bytes)

        # Apply edge detection to both for more robust matching invariant to colors
        bg_edges = cls.apply_canny(bg_img)
        piece_edges = cls.apply_canny(piece_img)

        # Since the puzzle piece is usually smaller and might have transparent padding,
        # we might need to find the actual bounding box of the piece edges
        # Find contours of the piece to crop empty space
        contours, _ = cv2.findContours(piece_edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            # Find the largest contour which should be the puzzle piece
            c = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(c)
            # Crop the piece edges to the bounding rectangle
            cropped_piece = piece_edges[y:y+h, x:x+w]
        else:
            cropped_piece = piece_edges
            x = 0  # Offset from original piece image left edge

        res = cv2.matchTemplate(bg_edges, cropped_piece, method)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

        # The max_loc[0] gives the match location in the background image.
        # However, the piece itself might have a starting offset (x) relative to its own container.
        # We need the pure translation distance:
        best_match_x = max_loc[0]
        confidence = max_val

        # Offset is exactly distance from current piece location to best match
        # Often the piece starts at X=0 in the background's coordinate system
        # If it doesn't, we have to subtract the piece's initial offset on the page.
        # For a standard solver, max_loc[0] is usually the raw offset needed minus existing offset.
        # We assume the piece's left visual edge aligns with start of drag.
        final_offset_x = float(best_match_x - x)

        return final_offset_x, confidence


class GeeTestSolver:
    def __init__(self, mouse_engine: MouseEngine, vlm_bridge=None):
        self.mouse_engine = mouse_engine
        self.capturer = GeeTestCapturer()
        self.cv_solver = OpenCVSolver()
        self.vlm_bridge = vlm_bridge  # VLMBridge instance (optional fallback)

    async def solve(
        self,
        page: Page,
        bg_selector: str = GEETEST_V3_SELECTORS["background"],
        piece_selector: str = GEETEST_V3_SELECTORS["piece"],
        slider_button_selector: str = GEETEST_V3_SELECTORS["slider_button"],
        success_selector: str = GEETEST_V3_SELECTORS["success"],
        fail_selector: str = GEETEST_V3_SELECTORS["fail"],
        max_attempts: int = 3
    ) -> GeeTestSolverResult:

        start_time = time.time()
        attempt = 0
        error = None
        # Jitter compensation: each retry offset increases slightly if we overshot/undershot
        offset_compensation = 0.0

        while attempt < max_attempts:
            attempt += 1
            try:
                # 1. Capture templates
                bg_bytes = await self.capturer.capture_background(page, bg_selector)
                piece_bytes = await self.capturer.capture_piece(page, piece_selector)

                # 2. Find offset via OpenCV
                offset_x, confidence = self.cv_solver.find_slider_offset(bg_bytes, piece_bytes)
                method = "opencv_template"
                logger.info("[Ghost/GeeTest] OpenCV offset=%.1fpx confidence=%.3f attempt=%d",
                            offset_x, confidence, attempt)

                # 3. Fallback to VLM if confidence is too low
                if confidence < 0.6 and self.vlm_bridge:
                    try:
                        bg_b64 = base64.b64encode(bg_bytes).decode('utf-8')
                        coords = self.vlm_bridge.analyze_captcha(
                            base64_image=bg_b64,
                            prompt="Find the empty slot for the sliding puzzle piece. Return the x-offset from left boundary in pixels."
                        )
                        if coords and len(coords) == 2:
                            # VLMBridge returns (x, y) — x is the absolute x of the slot
                            offset_x = float(coords[0])
                            method = "vlm_fallback"
                            logger.info("[Ghost/GeeTest] VLM fallback offset=%.1fpx", offset_x)
                    except Exception as vlm_err:
                        logger.warning("[Ghost/GeeTest] VLM fallback failed: %s", vlm_err)

                # Apply compensation from previous failed attempts
                adjusted_offset = offset_x + offset_compensation

                # 4. Get slider button position
                slider_btn = await page.wait_for_selector(slider_button_selector, timeout=5000)
                if not slider_btn:
                    raise ValueError(f"Slider button not found: {slider_button_selector}")

                box = await slider_btn.bounding_box()
                if not box:
                    raise ValueError("Could not get bounding box for slider button")

                start_x = box['x'] + box['width'] / 2
                start_y = box['y'] + box['height'] / 2
                target_x = start_x + adjusted_offset

                # 5. Drag using MouseEngine (human-like Bezier path)
                await self.mouse_engine.drag(page, (start_x, start_y), (target_x, start_y))

                # 6. Wait for server response and check result
                await asyncio.sleep(random.uniform(1.0, 2.0))
                success = await self.capturer.check_success(
                    page, success_selector, fail_selector, timeout=3000.0
                )

                if success is True:
                    processing_time = (time.time() - start_time) * 1000
                    logger.info("[Ghost/GeeTest] Success on attempt %d in %.0fms", attempt, processing_time)
                    return GeeTestSolverResult(
                        success=True,
                        offset_x=adjusted_offset,
                        confidence=confidence,
                        method_used=method,
                        attempts=attempt,
                        processing_time_ms=processing_time
                    )
                else:
                    # Retry with slight random jitter compensation
                    offset_compensation += random.uniform(-3, 3)
                    error = "Success check failed" if success is False else "Timeout waiting for result"
                    await asyncio.sleep(random.uniform(0.8, 1.5))

            except Exception as e:
                error = str(e)
                logger.warning("[Ghost/GeeTest] Attempt %d error: %s", attempt, error)
                await asyncio.sleep(random.uniform(0.5, 1.5))

        processing_time = (time.time() - start_time) * 1000
        return GeeTestSolverResult(
            success=False,
            offset_x=None,
            confidence=0.0,
            method_used="failed",
            attempts=attempt,
            processing_time_ms=processing_time,
            error=error
        )

class ReCaptchaResult(BaseModel):
    success: bool
    method: str = "unknown"           # v2_checkbox, v2_audio, v3
    confidence: float = 0.0          # score from reCAPTCHA v3 (0.0 = unavailable)
    attempts: int
    processing_time_ms: float
    error: Optional[str] = None



class ReCaptchaCapturer:
    @staticmethod
    async def wait_for_captcha(page: Page, timeout: float = 10000.0) -> Optional[Frame]:
        """Wait for the ReCaptcha checkbox iframe to appear and return its frame."""
        try:
            iframe_element = await page.wait_for_selector(
                'iframe[src*="recaptcha/api2/anchor"], iframe[title*="reCAPTCHA"]',
                timeout=timeout
            )
            if not iframe_element:
                return None
            frame = await iframe_element.content_frame()
            logger.info("[Ghost/ReCaptcha] Captcha iframe detected")
            return frame
        except Exception as e:
            logger.warning("[Ghost/ReCaptcha] wait_for_captcha error: %s", e)
            return None

    @staticmethod
    async def screenshot_frame(page: Page, challenge_iframe_element: Any) -> bytes:
        """Take a screenshot of the captcha challenge iframe element (not the Frame object)."""
        # challenge_iframe_element is the ElementHandle of the challenge iframe
        return await challenge_iframe_element.screenshot()

    @staticmethod
    async def get_challenge_text(challenge_frame: Frame) -> str:
        """Extract the text instruction like 'Select all images with traffic lights'."""
        try:
            # Try multiple selectors for different reCAPTCHA versions
            selectors = [
                '.rc-imageselect-instructions strong',
                '.rc-imageselect-desc-no-canonical',
                '.rc-imageselect-desc',
                '.rc-imageselect-instructions',
            ]
            for sel in selectors:
                el = await challenge_frame.query_selector(sel)
                if el:
                    text = await el.inner_text()
                    if text:
                        return text.strip()
            return "Unknown challenge"
        except Exception:
            return "Unknown challenge"

    @staticmethod
    async def is_verification_complete(checkbox_frame: Frame) -> bool:
        """Check if the verification succeeded by checking the aria-checked attribute."""
        try:
            # The checkbox element has aria-checked='true' when verified
            checkbox = await checkbox_frame.query_selector('.recaptcha-checkbox')
            if checkbox:
                aria = await checkbox.get_attribute('aria-checked')
                return aria == 'true'
            # Fallback: check for the checked state class
            checked = await checkbox_frame.query_selector('.recaptcha-checkbox-checked')
            return checked is not None
        except Exception:
            return False


class TileCoordinateMapper:
    @staticmethod
    def map_relative_to_absolute(relative_coords: Tuple[int, int], iframe_rect: Dict) -> Tuple[int, int]:
        """Convert coordinates from inside the iframe to absolute page coordinates."""
        # iframe_rect typically from element.bounding_box()
        abs_x = int(iframe_rect['x'] + relative_coords[0])
        abs_y = int(iframe_rect['y'] + relative_coords[1])
        return (abs_x, abs_y)

    @staticmethod
    def split_grid_to_tiles(image_bytes: bytes, grid_size: int = 3) -> List[bytes]:
        """
        Split captcha grid image into individual tile images.
        Returns list of `grid_size*grid_size` tile images as bytes.
        Useful for sending individual tiles to VLM for per-tile classification.
        """
        nparr = np.frombuffer(image_bytes, np.uint8)
        if nparr.size == 0:
            return []
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None or not hasattr(img, 'shape') or len(img.shape) < 2:
            return []

        height, width = img.shape[:2]
        tile_h = height // grid_size
        tile_w = width // grid_size
        tiles = []

        for row in range(grid_size):
            for col in range(grid_size):
                y1 = row * tile_h
                y2 = y1 + tile_h
                x1 = col * tile_w
                x2 = x1 + tile_w
                tile = img[y1:y2, x1:x2]
                _, buf = cv2.imencode('.png', tile)
                tiles.append(buf.tobytes())

        return tiles

    @staticmethod
    def get_tile_center(tile_index: int, iframe_rect: Dict, grid_size: int = 3) -> Tuple[int, int]:
        """
        Calculate the absolute center coordinates of a tile given its index and iframe bounding box.
        tile_index is 0-based, row-major order.
        """
        tile_h = iframe_rect['height'] / grid_size
        tile_w = iframe_rect['width'] / grid_size
        row = tile_index // grid_size
        col = tile_index % grid_size
        center_x = int(iframe_rect['x'] + (col + 0.5) * tile_w)
        center_y = int(iframe_rect['y'] + (row + 0.5) * tile_h)
        return (center_x, center_y)


class ReCaptchaV2Solver:
    def __init__(self, mouse_engine: MouseEngine, vlm_bridge):
        self.mouse_engine = mouse_engine
        self.capturer = ReCaptchaCapturer()
        self.tile_mapper = TileCoordinateMapper()
        self.vlm_bridge = vlm_bridge

    async def solve(self, page: Page, max_attempts: int = 3) -> ReCaptchaResult:
        start_time = time.time()

        # 1. Detect captcha presence (checkbox iframe)
        main_frame = await self.capturer.wait_for_captcha(page)
        if not main_frame:
            return ReCaptchaResult(success=False, confidence=0.0, attempts=0,
                                   processing_time_ms=0, error="ReCaptcha iframe not found")

        # 2. Click the initial checkbox with Bezier mouse
        try:
            checkbox = await main_frame.wait_for_selector('.recaptcha-checkbox-border', timeout=5000)
            if checkbox:
                box = await checkbox.bounding_box()
                iframe_el = await page.query_selector(
                    'iframe[src*="recaptcha/api2/anchor"], iframe[title*="reCAPTCHA"]'
                )
                iframe_box = await iframe_el.bounding_box() if iframe_el else None
                if box and iframe_box:
                    abs_x = iframe_box['x'] + box['x'] + box['width'] / 2
                    abs_y = iframe_box['y'] + box['y'] + box['height'] / 2
                    await self.mouse_engine.click(page, abs_x, abs_y)
                    logger.info("[Ghost/ReCaptcha] Clicked checkbox at (%.0f, %.0f)", abs_x, abs_y)
                    await asyncio.sleep(random.uniform(1.0, 2.5))
        except Exception as e:
            logger.warning("[Ghost/ReCaptcha] Checkbox click error: %s", e)

        # 3. Check if already verified (high trust score bypass)
        if await self.capturer.is_verification_complete(main_frame):
            logger.info("[Ghost/ReCaptcha] Bypassed without challenge (high trust score)")
            return ReCaptchaResult(success=True, confidence=1.0, attempts=1,
                                   processing_time_ms=(time.time() - start_time) * 1000)

        # 4. Handle image challenge
        for attempt in range(max_attempts):
            attempt_num = attempt + 1
            try:
                # Detect the challenge iframe (different from checkbox iframe)
                challenge_iframe_el = await page.wait_for_selector(
                    'iframe[src*="recaptcha/api2/bframe"], iframe[title*="recaptcha challenge"]',
                    timeout=8000
                )
                challenge_frame = await challenge_iframe_el.content_frame()
                iframe_rect = await challenge_iframe_el.bounding_box()

                if not challenge_frame or not iframe_rect:
                    logger.warning("[Ghost/ReCaptcha] Challenge frame or rect not found, attempt %d", attempt_num)
                    continue

                # 5. Screenshot + get challenge text
                frame_bytes = await self.capturer.screenshot_frame(page, challenge_iframe_el)
                challenge_text = await self.capturer.get_challenge_text(challenge_frame)
                logger.info("[Ghost/ReCaptcha] Challenge: '%s' — attempt %d", challenge_text, attempt_num)

                # 6. Send to VLMBridge → get list of target tile coordinates
                b64_image = base64.b64encode(frame_bytes).decode('utf-8')
                raw_result = self.vlm_bridge.analyze_captcha(
                    base64_image=b64_image,
                    prompt=f"{challenge_text}. Return all matching tile coordinates as a list."
                )

                # Adapt VLMBridge response: single Tuple → List of Tuples
                if isinstance(raw_result, tuple) and len(raw_result) == 2:
                    targets: List[Tuple[int, int]] = [raw_result]
                elif isinstance(raw_result, list):
                    targets = [(t[0], t[1]) for t in raw_result if len(t) >= 2]
                else:
                    targets = []

                logger.info("[Ghost/ReCaptcha] VLM returned %d target(s)", len(targets))

                # 7. Click each matching tile with human-like Bezier movement
                for (x, y) in targets:
                    abs_x, abs_y = self.tile_mapper.map_relative_to_absolute((x, y), iframe_rect)
                    await self.mouse_engine.click(page, float(abs_x), float(abs_y))
                    # Human pause between tile clicks (0.3s ± 0.1s)
                    await asyncio.sleep(max(0.1, random.gauss(0.3, 0.1)))

                # 8. Wait for possible grid refresh (new images may appear after clicking)
                await asyncio.sleep(random.gauss(1.2, 0.3))

                # 9. Check if grid refreshed — if it did, we need to loop again
                # (Visual check: if tiles changed, challenge_text may change)
                new_challenge_text = await self.capturer.get_challenge_text(challenge_frame)
                grid_refreshed = new_challenge_text != challenge_text

                if grid_refreshed:
                    logger.info("[Ghost/ReCaptcha] Grid refreshed — new challenge: '%s'", new_challenge_text)
                    # Continue loop to handle new grid (don't click verify yet)
                    continue

                # 10. Click Verify button
                try:
                    verify_btn = await challenge_frame.wait_for_selector(
                        '#recaptcha-verify-button', timeout=3000
                    )
                    if verify_btn:
                        v_box = await verify_btn.bounding_box()
                        if v_box:
                            v_abs_x = iframe_rect['x'] + v_box['x'] + v_box['width'] / 2
                            v_abs_y = iframe_rect['y'] + v_box['y'] + v_box['height'] / 2
                            await self.mouse_engine.click(page, v_abs_x, v_abs_y)
                            logger.info("[Ghost/ReCaptcha] Clicked Verify button")
                except Exception as e:
                    logger.warning("[Ghost/ReCaptcha] Verify button error: %s", e)

                # 11. Check if verification succeeded
                await asyncio.sleep(random.gauss(1.5, 0.4))
                if await self.capturer.is_verification_complete(main_frame):
                    processing_time = (time.time() - start_time) * 1000
                    logger.info("[Ghost/ReCaptcha] Verification SUCCESS on attempt %d in %.0fms",
                                attempt_num, processing_time)
                    return ReCaptchaResult(
                        success=True,
                        confidence=0.9,
                        attempts=attempt_num,
                        processing_time_ms=processing_time
                    )

            except Exception as e:
                logger.warning("[Ghost/ReCaptcha] Attempt %d error: %s", attempt_num, e)
                await asyncio.sleep(random.uniform(1.0, 2.0))

        return ReCaptchaResult(
            success=False,
            confidence=0.0,
            attempts=max_attempts,
            processing_time_ms=(time.time() - start_time) * 1000,
            error="Max attempts reached without verification success"
        )


class ReCaptchaV3Analyzer:
    """
    ReCaptcha v3 is score-based — no visual challenge.
    Strategy: optimize behavioral signals to get high score (>= 0.7).
    """

    def __init__(self, mouse_engine: MouseEngine):
        self.mouse_engine = mouse_engine

    async def prime_behavioral_signals(
        self,
        page: Page,
        min_time_on_page_s: float = 10.0,
        scroll_rounds: int = 3
    ) -> None:
        """
        Simulate genuine user behavior to maximize reCAPTCHA v3 score:
        - Random mouse movements across the page
        - Natural scroll behavior (varying speed and direction)
        - Time-on-page that mimics reading
        """
        # Phase A: Random mouse wandering across page
        viewport_size = await page.evaluate("({w: window.innerWidth, h: window.innerHeight})")
        w = viewport_size.get('w', 1280)
        h = viewport_size.get('h', 720)

        num_movements = random.randint(5, 10)
        for _ in range(num_movements):
            rand_x = random.uniform(w * 0.1, w * 0.9)
            rand_y = random.uniform(h * 0.1, h * 0.9)
            await self.mouse_engine.move_to(page, rand_x, rand_y)
            await asyncio.sleep(random.gauss(0.5, 0.2))

        # Phase B: Natural scroll behavior
        for _ in range(scroll_rounds):
            # Scroll down
            scroll_distance = random.randint(200, 600)
            await page.mouse.wheel(0, scroll_distance)
            await asyncio.sleep(random.gauss(1.5, 0.5))
            # Scroll up slightly (reading pattern)
            await page.mouse.wheel(0, -random.randint(50, 150))
            await asyncio.sleep(random.gauss(0.8, 0.3))

        # Phase C: Simulate reading time
        remaining_time = max(0, min_time_on_page_s - (scroll_rounds * 2.3))
        if remaining_time > 0:
            await asyncio.sleep(remaining_time)

        logger.info("[Ghost/ReCaptchaV3] Behavioral priming complete — ready for action")

    def assess_action_score_risk(
        self,
        action: str,
        time_on_page_s: float,
        scroll_depth_percent: float,
        mouse_movement_count: int
    ) -> str:
        """
        Estimate v3 score risk level based on behavioral signals.
        Returns: 'high_score' (>= 0.7), 'medium_score' (0.4-0.7), 'low_score' (< 0.4)
        """
        score = 0.5  # baseline

        # Time-on-page factor
        if time_on_page_s >= 30:
            score += 0.2
        elif time_on_page_s >= 10:
            score += 0.1
        else:
            score -= 0.2

        # Mouse movement factor
        if mouse_movement_count >= 10:
            score += 0.15
        elif mouse_movement_count >= 5:
            score += 0.05
        else:
            score -= 0.15

        # Scroll depth factor
        if scroll_depth_percent >= 50:
            score += 0.1
        elif scroll_depth_percent >= 20:
            score += 0.05

        score = max(0.0, min(1.0, score))

        if score >= 0.7:
            return 'high_score'
        elif score >= 0.4:
            return 'medium_score'
        else:
            return 'low_score'
