import asyncio
import math
import random
from typing import List, Tuple

from pydantic import BaseModel
from playwright.async_api import Page

class MousePath(BaseModel):
    points: List[Tuple[float, float]]  # (x, y) absolute pixel coords
    timestamps: List[float]            # cumulative ms from start
    total_distance_px: float
    total_duration_ms: float
    overshoot_occurred: bool

class BezierCurve:
    """
    Cubic Bezier curve: B(t) = (1-t)³P0 + 3(1-t)²tP1 + 3(1-t)t²P2 + t³P3
    t ∈ [0, 1]
    """
    def __init__(self, p0: Tuple[float, float], p1: Tuple[float, float], p2: Tuple[float, float], p3: Tuple[float, float]):
        self.p0 = p0
        self.p1 = p1
        self.p2 = p2
        self.p3 = p3

    def evaluate(self, t: float) -> Tuple[float, float]:
        x = (1-t)**3 * self.p0[0] + 3*(1-t)**2 * t * self.p1[0] + 3*(1-t) * t**2 * self.p2[0] + t**3 * self.p3[0]
        y = (1-t)**3 * self.p0[1] + 3*(1-t)**2 * t * self.p1[1] + 3*(1-t) * t**2 * self.p2[1] + t**3 * self.p3[1]
        return x, y

    def generate_points(self, num_points: int) -> List[Tuple[float, float]]:
        return [self.evaluate(t / (num_points - 1)) for t in range(num_points)]

def fitts_time(distance_px: float, target_size_px: float = 20.0) -> float:
    """
    Fitts's Law motion time estimation.
    T = a + b * log2(D/W + 1)
    where a=50ms, b=130ms (empirical constants for mouse movement)
    """
    ID = math.log2(distance_px / target_size_px + 1)
    return 50 + 130 * ID

def ease_in_out_cubic(t: float) -> float:
    """
    Cubic easing function for natural acceleration/deceleration.
    t < 0.5: 4t³
    t >= 0.5: 1 - (-2t + 2)³ / 2
    """
    if t < 0.5:
        return 4 * t * t * t
    else:
        return 1 - math.pow(-2 * t + 2, 3) / 2

def generate_control_points(start: Tuple[float, float], end: Tuple[float, float], overshoot: bool = False) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dist = math.hypot(dx, dy)
    
    # Random deviation roughly proportional to distance
    dev = dist * random.uniform(0.1, 0.4)
    # Give the curve a "bulge" direction randomly (left or right relative to direct path)
    if random.random() < 0.5:
        dev = -dev
        
    # Find perpendicular vector
    perp_dx = -dy / dist if dist > 0 else 0
    perp_dy = dx / dist if dist > 0 else 0
    
    # Calculate initial intermediate points
    # P1: 20-40% along the path
    t1 = random.uniform(0.2, 0.4)
    # P2: 60-80% along the path
    t2 = random.uniform(0.6, 0.8)
    
    p1 = (
        start[0] + dx * t1 + perp_dx * dev * random.uniform(0.5, 1.5),
        start[1] + dy * t1 + perp_dy * dev * random.uniform(0.5, 1.5)
    )
    
    if overshoot:
        # Overshoot pushes P2 past the end point
        overshoot_dist = dist * random.uniform(0.05, 0.15)
        # Continue in same rough direction but pushed past the target
        p2_base_x = start[0] + dx * 1.1 + (perp_dx * dev * 0.2)
        p2_base_y = start[1] + dy * 1.1 + (perp_dy * dev * 0.2)
    else:
        p2_base_x = start[0] + dx * t2 + (perp_dx * dev * random.uniform(0.2, 0.8))
        p2_base_y = start[1] + dy * t2 + (perp_dy * dev * random.uniform(0.2, 0.8))
        
    p2 = (
        p2_base_x + random.uniform(-dist * 0.05, dist * 0.05),
        p2_base_y + random.uniform(-dist * 0.05, dist * 0.05)
    )
    
    return p1, p2

def generate_mouse_path(
    start: Tuple[float, float],
    end: Tuple[float, float],
    target_size: float = 20.0,
    speed_factor: float = 1.0,
) -> MousePath:
    """
    Generate a human-realistic mouse path from start to end.
    Uses Cubic Bezier + Fitts's Law + optional overshoot.
    """
    dist = math.hypot(end[0] - start[0], end[1] - start[1])
    
    # 15% chance to overshoot
    overshoot_occurred = random.random() < 0.15 and dist > 100
    
    p1, p2 = generate_control_points(start, end, overshoot=overshoot_occurred)
    curve = BezierCurve(start, p1, p2, end)
    
    # Determine number of points based roughly on distance
    num_points = max(10, min(100, int(dist / 5)))
    points = curve.generate_points(num_points)
    
    # Calculate timing with Fitts's Law
    base_duration = fitts_time(dist, target_size)
    duration_ms = base_duration * speed_factor * random.uniform(0.9, 1.1)
    
    timestamps = []
    current_time = 0.0
    for i in range(num_points):
        t = i / (num_points - 1)
        # Ease the time so points concentrate at start/end to simulate acceleration/deceleration
        eased_t = ease_in_out_cubic(t)
        timestamps.append(eased_t * duration_ms)
        
    return MousePath(
        points=points,
        timestamps=timestamps,
        total_distance_px=dist,
        total_duration_ms=duration_ms,
        overshoot_occurred=overshoot_occurred
    )

class MouseEngine:
    def __init__(self):
        self._current_pos = (0.0, 0.0)

    async def _add_micro_jitter(self, page: Page, x: float, y: float) -> None:
        """Simulate human hand tremor after reaching the target."""
        num_jitters = random.randint(3, 7)
        for _ in range(num_jitters):
            jitter_x = x + random.uniform(-2, 2)
            jitter_y = y + random.uniform(-2, 2)
            await page.mouse.move(jitter_x, jitter_y)
            await asyncio.sleep(random.uniform(0.015, 0.040))
            self._current_pos = (jitter_x, jitter_y)
            
        # Settle on final target
        await page.mouse.move(x, y)
        self._current_pos = (x, y)
        await asyncio.sleep(random.uniform(0.05, 0.15))

    async def move_to(self, page: Page, x: float, y: float, target_size: float = 20.0) -> None:
        """Move cursor simulating human acceleration and pathing."""
        path = generate_mouse_path(self._current_pos, (x, y), target_size)
        
        last_t = 0.0
        for i, point in enumerate(path.points):
            t = path.timestamps[i]
            sleep_time = (t - last_t) / 1000.0
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            
            await page.mouse.move(point[0], point[1])
            last_t = t
            
        self._current_pos = (x, y)
        await self._add_micro_jitter(page, x, y)

    async def click(self, page: Page, x: float, y: float, button: str = "left") -> None:
        """Human-like move then click."""
        await self.move_to(page, x, y)
        
        # Mousedown, hold a bit, mouseup
        await page.mouse.down(button=button)
        # Gaussian delay for mouse click length
        delay_ms = random.gauss(mu=70, sigma=20)
        await asyncio.sleep(max(0.01, delay_ms / 1000))
        await page.mouse.up(button=button)
        
    async def double_click(self, page: Page, x: float, y: float) -> None:
        """Human-like move and double click."""
        await self.move_to(page, x, y)
        await page.mouse.dblclick(x, y)

    async def drag(self, page: Page, start: Tuple[float, float], end: Tuple[float, float]) -> None:
        """Human-like drag (e.g. for sliders)."""
        await self.move_to(page, start[0], start[1])
        await page.mouse.down()
        await asyncio.sleep(random.uniform(0.1, 0.3))
        
        # Drag normally doesn't overshoot
        path = generate_mouse_path(start, end, target_size=10.0, speed_factor=1.2)
        
        last_t = 0.0
        for i, point in enumerate(path.points):
            t = path.timestamps[i]
            sleep_time = (t - last_t) / 1000.0
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
                
            await page.mouse.move(point[0], point[1])
            last_t = t
            
        self._current_pos = end
        await asyncio.sleep(random.uniform(0.1, 0.4))
        await page.mouse.up()
