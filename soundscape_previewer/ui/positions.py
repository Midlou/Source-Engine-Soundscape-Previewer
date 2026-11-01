"""Top-down view of the listener and the 8 soundscape positions."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QMenu, QToolButton, QWidget

from ..audio import Engine, Spatial
from ..soundscape import NUM_POSITIONS

POS_COLORS = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#06b6d4", "#3b82f6", "#8b5cf6", "#ec4899"]


class PositionsView(QWidget):
    """Drag the listener (triangle) and positions 0-7 (circles).

    Right-drag turns the listener, the mouse wheel zooms, double-click a
    position to enable/disable it (disabled positions behave like an
    env_soundscape target that is not set: their sounds are not played).
    """

    changed = Signal()

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.scale = 0.35  # pixels per unit
        self.center = QPointF(0, 0)  # world point at the widget center
        self._drag = None
        self._pan_from = None
        self.snapshot: dict = {}
        self._flashes: list[tuple[float, tuple[float, float], str]] = []
        self._last_event_time = 0.0
        self.setMinimumHeight(180)
        self.setMouseTracking(True)
        self.setToolTip(
            "Drag the listener and positions 0-7.\nRight-drag: turn the listener. Middle-drag: pan. Wheel: zoom.\n"
            "Double-click a position: enable/disable it (like an unset env_soundscape target)."
        )

        # floating button in the top-right corner; add more actions to self.menu
        self.menu = QMenu(self)
        self.menu.addAction("Reset positions", self.reset_positions)
        self.menu.addAction("Reset player position", self.reset_listener)
        self.menu.addAction("Reset view", self.reset_view)
        self.menu.addSeparator()
        self.menu.addAction("Reset all", self.reset_all)
        self.btn_actions = QToolButton(self)
        self.btn_actions.setText("Actions ")
        self.btn_actions.setToolTip("Reset positions, the player or the view")
        self.btn_actions.setPopupMode(QToolButton.InstantPopup)
        self.btn_actions.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_actions.setMenu(self.menu)
        self.btn_actions.setCursor(Qt.ArrowCursor)

    # ---------------------------------------------------------------- coords
    def to_screen(self, p) -> QPointF:
        c = QPointF(self.width() / 2, self.height() / 2)
        return QPointF(c.x() + (p[0] - self.center.x()) * self.scale, c.y() - (p[1] - self.center.y()) * self.scale)

    def to_world(self, q: QPointF) -> tuple[float, float]:
        return (
            (q.x() - self.width() / 2) / self.scale + self.center.x(),
            -(q.y() - self.height() / 2) / self.scale + self.center.y(),
        )

    def update_snapshot(self, snap: dict) -> None:
        self.snapshot = snap
        now = time.monotonic()
        for ev in list(self.engine.events):
            if ev.time > self._last_event_time:
                self._last_event_time = ev.time
                if isinstance(ev.point, tuple):
                    self._flashes.append((now, ev.point, ev.wave.split("/")[-1]))
        self._flashes = [f for f in self._flashes if now - f[0] < 1.5]
        self.update()

    # --------------------------------------------------------------- painting
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        bg = pal.base().color()
        fg = pal.text().color()
        p.fillRect(self.rect(), bg)
        sp = self.engine.spatial

        # grid
        grid = 128
        while grid * self.scale < 24:
            grid *= 2
        gc = QColor(fg)
        gc.setAlpha(25)
        p.setPen(QPen(gc, 1))
        x0, y1 = self.to_world(QPointF(0, 0))
        x1, y0 = self.to_world(QPointF(self.width(), self.height()))
        gx = math.floor(x0 / grid) * grid
        while gx <= x1:
            s = self.to_screen((gx, 0)).x()
            p.drawLine(QPointF(s, 0), QPointF(s, self.height()))
            gx += grid
        gy = math.floor(y0 / grid) * grid
        while gy <= y1:
            s = self.to_screen((0, gy)).y()
            p.drawLine(QPointF(0, s), QPointF(self.width(), s))
            gy += grid

        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1.5))
        p.setFont(small)
        tc = QColor(fg)
        tc.setAlpha(140)
        p.setPen(tc)
        p.drawText(6, self.height() - 6, f"grid {grid} units")

        loops = self.snapshot.get("loops", [])
        # positioned loop activity
        level_at: dict = {}
        for lp in loops:
            pt = lp["point"]
            if isinstance(pt, tuple):
                level_at.setdefault(pt, []).append(lp)

        # positions
        for i in range(NUM_POSITIONS):
            pos = sp.positions[i]
            q = self.to_screen(pos)
            col = QColor(POS_COLORS[i])
            enabled = sp.enabled[i]
            active = level_at.get(tuple(pos), [])
            if active and enabled:
                lvl = max(a["level"] for a in active)
                r = 12 + 30 * min(1.0, lvl * 2)
                glow = QColor(col)
                glow.setAlpha(60)
                p.setPen(Qt.NoPen)
                p.setBrush(glow)
                p.drawEllipse(q, r, r)
            p.setPen(QPen(col, 2))
            p.setBrush(QBrush(col) if enabled else Qt.NoBrush)
            p.drawEllipse(q, 9, 9)
            p.setPen(QColor("white") if enabled else col)
            p.drawText(QRectF(q.x() - 9, q.y() - 9, 18, 18), Qt.AlignCenter, str(i))
            dist = math.hypot(pos[0] - sp.listener[0], pos[1] - sp.listener[1])
            p.setPen(tc)
            label = f"{dist:.0f}u" + (f" · {len(active)} loop{'s' if len(active) > 1 else ''}" if active else "")
            if not enabled:
                label += " (off)"
            p.drawText(QPointF(q.x() + 12, q.y() + 4), label)

        # origin-based sounds
        for lp in loops:
            pt = lp["point"]
            if isinstance(lp["position"], tuple) and isinstance(pt, tuple):
                q = self.to_screen(pt)
                p.setPen(QPen(fg, 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawRect(QRectF(q.x() - 6, q.y() - 6, 12, 12))

        # random sound flashes
        now = time.monotonic()
        for t, pt, name in self._flashes:
            a = 1.0 - (now - t) / 1.5
            q = self.to_screen(pt)
            c = QColor("#f59e0b")
            c.setAlphaF(max(0.0, a))
            p.setPen(QPen(c, 2))
            p.setBrush(Qt.NoBrush)
            r = 6 + (1 - a) * 30
            p.drawEllipse(q, r, r)
            p.drawText(QPointF(q.x() + 8, q.y() - 8), name)

        # listener
        q = self.to_screen(sp.listener)
        yaw = math.radians(sp.listener_yaw)
        path = QPainterPath()
        pts = [(0, 14), (-9, -9), (9, -9)]
        for k, (lx, ly) in enumerate(pts):
            wx = lx * math.cos(yaw) + ly * math.sin(yaw)
            wy = -lx * math.sin(yaw) + ly * math.cos(yaw)
            sp_pt = QPointF(q.x() + wx, q.y() - wy)
            path.moveTo(sp_pt) if k == 0 else path.lineTo(sp_pt)
        path.closeSubpath()
        p.setPen(QPen(fg, 1.5))
        p.setBrush(QColor("#10b981"))
        p.drawPath(path)

        # ambient summary
        ambient = [lp for lp in loops if lp["point"] is None]
        suppressed = [lp for lp in loops if lp["point"] is False]
        p.setPen(tc)
        lines = [f"Ambient loops: {len(ambient)}"]
        if suppressed:
            lines.append(f"Silent (position off): {len(suppressed)}")
        plan = self.snapshot.get("plan")
        lines.insert(0, f"Playing: {plan}" if plan else "Stopped")
        for k, line in enumerate(lines):
            p.drawText(6, 14 + k * 14, line)
        p.end()

    # ------------------------------------------------------------------ mouse
    def _hit(self, q: QPointF):
        sp = self.engine.spatial
        lq = self.to_screen(sp.listener)
        if (lq - q).manhattanLength() < 16:
            return "listener"
        for i in range(NUM_POSITIONS):
            if (self.to_screen(sp.positions[i]) - q).manhattanLength() < 14:
                return i
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = self._hit(e.position())
        elif e.button() == Qt.RightButton:
            self._drag = "rotate"
            self._rotate_to(e.position())
        elif e.button() == Qt.MiddleButton:
            self._pan_from = (e.position(), QPointF(self.center))

    def mouseMoveEvent(self, e):
        sp = self.engine.spatial
        if self._pan_from is not None:
            start, c = self._pan_from
            d = e.position() - start
            self.center = QPointF(c.x() - d.x() / self.scale, c.y() + d.y() / self.scale)
            self.update()
            return
        if self._drag is None:
            hit = self._hit(e.position())
            self.setCursor(Qt.OpenHandCursor if hit is not None else Qt.ArrowCursor)
            return
        w = self.to_world(e.position())
        if self._drag == "listener":
            sp.listener = w
        elif self._drag == "rotate":
            self._rotate_to(e.position())
        elif isinstance(self._drag, int):
            positions = list(sp.positions)
            positions[self._drag] = w
            sp.positions = positions
        self.update()

    def _rotate_to(self, q: QPointF):
        sp = self.engine.spatial
        w = self.to_world(q)
        dx, dy = w[0] - sp.listener[0], w[1] - sp.listener[1]
        if abs(dx) + abs(dy) > 1:
            sp.listener_yaw = math.degrees(math.atan2(dx, dy))
        self.update()

    def mouseReleaseEvent(self, _e):
        if self._drag is not None or self._pan_from is not None:
            self.changed.emit()
        self._drag = None
        self._pan_from = None

    def mouseDoubleClickEvent(self, e):
        hit = self._hit(e.position())
        if isinstance(hit, int):
            sp = self.engine.spatial
            enabled = list(sp.enabled)
            enabled[hit] = not enabled[hit]
            sp.enabled = enabled
            self.changed.emit()
            self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.btn_actions.adjustSize()
        self.btn_actions.move(self.width() - self.btn_actions.width() - 8, 8)

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale = max(0.02, min(4.0, self.scale * f))
        self.update()

    def reset_view(self):
        self.center = QPointF(*self.engine.spatial.listener)
        self.scale = 0.35
        self.update()

    def reset_positions(self):
        """Put positions 0-7 back on the default circle and enable them all."""
        default = Spatial()
        sp = self.engine.spatial
        sp.positions = default.positions
        sp.enabled = default.enabled
        self.changed.emit()
        self.update()

    def reset_listener(self):
        """Move the listener back to the origin, facing +Y."""
        sp = self.engine.spatial
        sp.listener = (0.0, 0.0)
        sp.listener_yaw = 0.0
        self.changed.emit()
        self.update()

    def reset_all(self):
        self.reset_positions()
        self.reset_listener()
        self.reset_view()


