"""Graphics View waveform with sample coordinates and pixel-sized interactions."""

import math

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QResizeEvent,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QStyleOptionGraphicsItem,
    QWidget,
)

from .audio import AudioData
from .document import AudioDocument, Marker
from .i18n import tr


def format_time(sample: float, samplerate: int) -> str:
    ms = round(sample * 1000 / samplerate)
    minutes, rest = divmod(ms, 60000)
    seconds, milliseconds = divmod(rest, 1000)
    return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


class WaveformItem(QGraphicsItem):
    """Draw audio channels in scene coordinates: x = sample index, y = channel lane.

    Each audio channel occupies one vertical unit (stereo: lanes 0..1 and 1..2).
    The view transform converts these logical coordinates to viewport pixels.
    """

    # The zero line sits halfway down each audio channel's one-unit lane.
    CHANNEL_CENTER = 0.5
    # Full-scale amplitude uses 84% of the lane, leaving 8% padding at either edge.
    AMPLITUDE_SCALE = 0.42
    # Avoid division/geometry issues when the horizontal transform is nearly zero.
    MIN_HORIZONTAL_SCALE = 1e-12
    # Draw individual samples up to this density; otherwise draw min/max envelopes.
    MAX_SAMPLES_PER_PIXEL = 2
    # Muted zero line and alternating channel colors on the dark background.
    ZERO_LINE_COLOR = "#37516a"
    CHANNEL_COLORS = ("#53d7bc", "#6ab4fa")

    def __init__(self, audio: AudioData) -> None:
        super().__init__()
        self.audio = audio
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption)
        self._cache_key: tuple[int, int, int] | None = None
        self._paths: list[QPainterPath] = []

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.audio.frames, self.audio.channels)

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        scale = max(abs(painter.worldTransform().m11()), self.MIN_HORIZONTAL_SCALE)
        visible = option.exposedRect.intersected(self.boundingRect())
        start = max(0, int(visible.left()) - 1)
        end = min(self.audio.frames, int(math.ceil(visible.right())) + 2)
        columns = max(1, int((end - start) * scale) + 1)
        self._update_paths(start, end, columns)
        self._draw_paths(painter, start, end)

    def _update_paths(self, start: int, end: int, columns: int) -> None:
        """Rebuild cached geometry only when the visible range or pixel density changes."""
        key = (start, end, columns)
        if key == self._cache_key:
            return
        self._paths = []
        if end > start:
            for channel in range(self.audio.channels):
                values = self.audio.samples[start:end, channel]
                center = channel + self.CHANNEL_CENTER
                if len(values) <= columns * self.MAX_SAMPLES_PER_PIXEL:
                    path = self._sample_path(values, start, center)
                else:
                    path = self._envelope_path(values, start, center, columns)
                self._paths.append(path)
        self._cache_key = key

    def _sample_path(self, values: NDArray[np.float64], start: int, center: float) -> QPainterPath:
        """Connect individual samples when zoomed in; values must be nonempty."""
        path = QPainterPath()
        path.moveTo(start, center - float(values[0]) * self.AMPLITUDE_SCALE)
        for i, value in enumerate(values[1:], start + 1):
            path.lineTo(i, center - float(value) * self.AMPLITUDE_SCALE)
        return path

    def _envelope_path(
        self, values: NDArray[np.float64], start: int, center: float, columns: int
    ) -> QPainterPath:
        """Preserve peaks as min/max lines when multiple samples share a pixel column."""
        edges = np.linspace(0, len(values), columns + 1, dtype=int)
        lows = np.minimum.reduceat(values, edges[:-1])
        highs = np.maximum.reduceat(values, edges[:-1])
        path = QPainterPath()
        for i in range(columns):
            x = start + (edges[i] + edges[i + 1]) / 2
            path.moveTo(x, center - float(highs[i]) * self.AMPLITUDE_SCALE)
            path.lineTo(x, center - float(lows[i]) * self.AMPLITUDE_SCALE)
        return path

    def _draw_paths(self, painter: QPainter, start: int, end: int) -> None:
        painter.setClipRect(self.boundingRect())
        for channel, path in enumerate(self._paths):
            pen = QPen(QColor(self.ZERO_LINE_COLOR))
            pen.setCosmetic(True)
            painter.setPen(pen)
            center = channel + self.CHANNEL_CENTER
            painter.drawLine(QPointF(start, center), QPointF(end, center))
            pen.setColor(QColor(self.CHANNEL_COLORS[channel % len(self.CHANNEL_COLORS)]))
            painter.setPen(pen)
            painter.drawPath(path)


class WaveformView(QGraphicsView):
    # Scene-space headroom above the channels and total vertical padding (0.10 below).
    SCENE_TOP_PADDING = 0.18
    SCENE_VERTICAL_PADDING = 0.28
    # Minimum widget height and inset reserved when fitting the viewport, in pixels.
    MINIMUM_HEIGHT_PX = 260
    VIEWPORT_INSET_PX = 2
    # Each wheel notch changes zoom by 25%; Qt reports 120 angle units per notch.
    ZOOM_FACTOR_PER_NOTCH = 1.25
    WHEEL_ANGLE_UNITS_PER_NOTCH = 120
    # Maximum horizontal magnification, in viewport pixels per audio sample.
    MAX_PIXELS_PER_SAMPLE = 20
    # Marker hit distance is exclusive; dragging starts at this movement, in pixels.
    MARKER_HIT_DISTANCE_PX = 7
    MARKER_DRAG_THRESHOLD_PX = 3
    # Background, empty-state text, and time-ruler palette.
    BACKGROUND_COLOR = "#101d2b"
    EMPTY_STATE_TEXT_COLOR = "#c5d6e5"
    RULER_BACKGROUND_COLOR = "#172839"
    RULER_TEXT_COLOR = "#a9bed0"
    # Translucent blue overlay for the selected segment (red, green, blue, alpha).
    SEGMENT_HIGHLIGHT_RGBA = (60, 155, 205, 35)
    # Distinguish detected/manual markers and the playback position.
    AUTOMATIC_MARKER_COLOR = "#ffbd69"
    MANUAL_MARKER_COLOR = "#c3a3ff"
    PLAYHEAD_COLOR = "#f3f7fc"
    # Fixed viewport coordinates in pixels, independent of waveform zoom.
    RULER_HEIGHT_PX = 27
    OVERLAY_TOP_PX = RULER_HEIGHT_PX + 1
    RULER_LABEL_OFFSET_X_PX = 4
    RULER_LABEL_BASELINE_PX = 18
    RULER_TICK_TOP_PX = 23
    # Prefer readable decimal time intervals with at least this pixel spacing.
    MIN_TICK_SPACING_PX = 100
    TICK_MAGNITUDE_BASE = 10
    TICK_INTERVAL_MULTIPLIERS = (1, 2, 5, 10)
    # Keep marker decorations visible just beyond the horizontal viewport edges.
    MARKER_CULL_MARGIN_PX = 8
    # Marker handle center/radius and line widths, in viewport pixels.
    MARKER_HANDLE_CENTER_Y_PX = 34
    MARKER_HANDLE_RADIUS_PX = 4
    MARKER_LINE_WIDTH_PX = 1.5
    SELECTED_MARKER_LINE_WIDTH_PX = 3
    PLAYHEAD_LINE_WIDTH_PX = 1.5
    ZOOM_FACTOR_PER_NOTCH = 1.25

    add_requested = Signal(int)
    remove_requested = Signal(str)
    move_started = Signal(str)
    move_preview = Signal(str, int)
    move_finished = Signal(str)
    segment_selected = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.document: AudioDocument | None = None
        self.anchor: int | None = None
        self.selected_marker: str | None = None
        self.playhead = 0
        self._drag_id: str | None = None
        self._dragging = False
        self._press_x = 0
        self._fit = True
        self.setBackgroundBrush(QColor(self.BACKGROUND_COLOR))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setMouseTracking(True)
        self.setMinimumHeight(self.MINIMUM_HEIGHT_PX)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)

    def set_document(self, document: AudioDocument) -> None:
        if self.document is not None:
            self.document.markers_changed.disconnect(self.refresh)
        self.document = document
        self.scene().clear()
        self.anchor = self.selected_marker = self._drag_id = None
        self._dragging = False
        self.playhead = 0
        document.markers_changed.connect(self.refresh)
        self.scene().addItem(WaveformItem(document.audio))
        self.scene().setSceneRect(
            0,
            -self.SCENE_TOP_PADDING,
            document.audio.frames,
            document.audio.channels + self.SCENE_VERTICAL_PADDING,
        )
        self.fit_all()

    def refresh(self) -> None:
        if (
            self.document
            and self.selected_marker
            and not self.document.marker(self.selected_marker)
        ):
            self.selected_marker = None
        self.viewport().update()

    def fit_all(self) -> None:
        if self.document:
            self._fit = True
            self._apply_scale(
                max(1, self.viewport().width() - self.VIEWPORT_INSET_PX)
                / self.document.audio.frames
            )
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().minimum())

    def zoom_in(self) -> None:
        self._zoom(self.ZOOM_FACTOR_PER_NOTCH)

    def zoom_out(self) -> None:
        self._zoom(1 / self.ZOOM_FACTOR_PER_NOTCH)

    def _zoom(self, factor: float, point: QPoint | None = None) -> None:
        if self.document is None:
            return

        if point is None:
            point = self.viewport().rect().center()

        before = self.mapToScene(point)
        minimum = (
            max(1, self.viewport().width() - self.VIEWPORT_INSET_PX) / self.document.audio.frames
        )
        scale = max(
            minimum,
            min(self.MAX_PIXELS_PER_SAMPLE, self.transform().m11() * factor),
        )

        if scale <= minimum:
            self.fit_all()
            return

        self._fit = False
        self._apply_scale(scale)

        # Den gewählten Zeitpunkt an seiner Bildschirmposition halten.
        after = self.mapFromScene(before)
        scrollbar = self.horizontalScrollBar()
        scrollbar.setValue(scrollbar.value() + after.x() - point.x())

    def _apply_scale(self, x_scale: float) -> None:
        assert self.document is not None
        y_scale = max(1, self.viewport().height() - self.VIEWPORT_INSET_PX) / (
            self.document.audio.channels + self.SCENE_VERTICAL_PADDING
        )
        self.setTransform(QTransform.fromScale(x_scale, y_scale))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.document:
            if self._fit:
                self.fit_all()
            else:
                self._apply_scale(self.transform().m11())

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.document is None:
            event.ignore()
            return

        delta = event.angleDelta().y() or event.angleDelta().x()

        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = self.ZOOM_FACTOR_PER_NOTCH ** (delta / self.WHEEL_ANGLE_UNITS_PER_NOTCH)
            self._zoom(factor, event.position().toPoint())
        else:
            movement = event.pixelDelta().y() or event.pixelDelta().x() or delta
            scrollbar = self.horizontalScrollBar()
            scrollbar.setValue(scrollbar.value() - movement)

        event.accept()

    def sample_at(self, point: QPoint) -> int:
        assert self.document is not None
        return max(0, min(self.document.audio.frames - 1, int(round(self.mapToScene(point).x()))))

    def marker_at(self, point: QPoint) -> Marker | None:
        assert self.document is not None
        closest: Marker | None = None
        distance = self.MARKER_HIT_DISTANCE_PX
        for marker in self.document.markers:
            d = abs(self.mapFromScene(QPointF(marker.sample, 0)).x() - point.x())
            if d < distance:
                closest, distance = marker, d
        return closest

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.document or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self.setFocus()
        point = event.position().toPoint()
        marker = self.marker_at(point)
        if marker:
            self.selected_marker = marker.id
            self._drag_id, self._dragging, self._press_x = marker.id, False, point.x()
        else:
            self.selected_marker = None
            self.anchor = self.sample_at(point)
            self.segment_selected.emit(self.anchor)
        self.viewport().update()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.document:
            return
        point = event.position().toPoint()
        if self._drag_id and event.buttons() & Qt.MouseButton.LeftButton:
            if (
                not self._dragging
                and abs(point.x() - self._press_x) >= self.MARKER_DRAG_THRESHOLD_PX
            ):
                self._dragging = True
                self.move_started.emit(self._drag_id)
            if self._dragging:
                self.move_preview.emit(self._drag_id, self.sample_at(point))
            event.accept()
        else:
            marker = self.marker_at(point)
            self.setCursor(Qt.CursorShape.SizeHorCursor if marker else Qt.CursorShape.CrossCursor)
            self.setToolTip(
                tr(
                    "marker.tooltip",
                    kind=tr("marker.automatic" if marker.automatic else "marker.manual"),
                    time=format_time(marker.sample, self.document.audio.samplerate),
                    sample=marker.sample,
                )
                if marker
                else ""
            )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_id:
            marker_id, dragging = self._drag_id, self._dragging
            self._drag_id, self._dragging = None, False
            if dragging:
                self.move_finished.emit(marker_id)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self.document and event.button() == Qt.MouseButton.LeftButton:
            self._drag_id, self._dragging = None, False
            point = event.position().toPoint()
            marker = self.marker_at(point)
            if marker:
                self.remove_requested.emit(marker.id)
            else:
                self.add_requested.emit(self.sample_at(point))
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def drawForeground(self, painter: QPainter, rect: QRectF | QRect) -> None:
        """Paint overlays in viewport pixels so their sizes stay fixed during zoom."""
        painter.save()
        painter.resetTransform()
        width, height = self.viewport().width(), self.viewport().height()
        try:
            if self.document is None:
                self._draw_empty_state(painter, width, height)
                return
            self._draw_selected_segment(painter, height)
            self._draw_time_ruler(painter, width)
            self._draw_markers(painter, width, height)
            self._draw_playhead(painter, height)
        finally:
            painter.restore()

    def _draw_empty_state(self, painter: QPainter, width: int, height: int) -> None:
        painter.setPen(QColor(self.EMPTY_STATE_TEXT_COLOR))
        painter.drawText(
            QRectF(0, 0, width, height),
            Qt.AlignmentFlag.AlignCenter,
            tr("empty.waveform"),
        )

    def _draw_selected_segment(self, painter: QPainter, height: int) -> None:
        assert self.document is not None
        if self.anchor is None:
            return
        start, end = self.document.segment_at(self.anchor)
        x1, x2 = (
            self.mapFromScene(QPointF(start, 0)).x(),
            self.mapFromScene(QPointF(end, 0)).x(),
        )
        painter.fillRect(
            QRectF(x1, self.OVERLAY_TOP_PX, x2 - x1, height - self.OVERLAY_TOP_PX),
            QColor(*self.SEGMENT_HIGHLIGHT_RGBA),
        )

    def _draw_time_ruler(self, painter: QPainter, width: int) -> None:
        assert self.document is not None
        audio = self.document.audio
        painter.fillRect(
            QRectF(0, 0, width, self.RULER_HEIGHT_PX), QColor(self.RULER_BACKGROUND_COLOR)
        )
        visible_start = max(0, self.mapToScene(0, 0).x())
        visible_end = min(audio.frames, self.mapToScene(width, 0).x())
        seconds_per_tick = max(
            1 / audio.samplerate,
            (visible_end - visible_start)
            / audio.samplerate
            * self.MIN_TICK_SPACING_PX
            / max(width, 1),
        )
        magnitude = self.TICK_MAGNITUDE_BASE ** math.floor(math.log10(seconds_per_tick))
        tick = next(
            v * magnitude
            for v in self.TICK_INTERVAL_MULTIPLIERS
            if v * magnitude >= seconds_per_tick
        )
        t = math.ceil(visible_start / audio.samplerate / tick) * tick
        painter.setPen(QColor(self.RULER_TEXT_COLOR))
        while t <= visible_end / audio.samplerate:
            x = self.mapFromScene(QPointF(t * audio.samplerate, 0)).x()
            painter.drawText(
                x + self.RULER_LABEL_OFFSET_X_PX,
                self.RULER_LABEL_BASELINE_PX,
                format_time(t * audio.samplerate, audio.samplerate),
            )
            painter.drawLine(x, self.RULER_TICK_TOP_PX, x, self.RULER_HEIGHT_PX)
            t += tick

    def _draw_markers(self, painter: QPainter, width: int, height: int) -> None:
        assert self.document is not None
        for marker in self.document.markers:
            x = self.mapFromScene(QPointF(marker.sample, 0)).x()
            if not -self.MARKER_CULL_MARGIN_PX <= x <= width + self.MARKER_CULL_MARGIN_PX:
                continue
            color = QColor(
                self.AUTOMATIC_MARKER_COLOR if marker.automatic else self.MANUAL_MARKER_COLOR
            )
            pen = QPen(
                color,
                (
                    self.SELECTED_MARKER_LINE_WIDTH_PX
                    if marker.id == self.selected_marker
                    else self.MARKER_LINE_WIDTH_PX
                ),
            )
            painter.setPen(pen)
            painter.drawLine(x, self.OVERLAY_TOP_PX, x, height)
            painter.setBrush(color)
            painter.drawEllipse(
                QPointF(x, self.MARKER_HANDLE_CENTER_Y_PX),
                self.MARKER_HANDLE_RADIUS_PX,
                self.MARKER_HANDLE_RADIUS_PX,
            )

    def _draw_playhead(self, painter: QPainter, height: int) -> None:
        x = self.mapFromScene(QPointF(self.playhead, 0)).x()
        painter.setPen(QPen(QColor(self.PLAYHEAD_COLOR), self.PLAYHEAD_LINE_WIDTH_PX))
        painter.drawLine(x, self.OVERLAY_TOP_PX, x, height)
