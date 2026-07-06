import sys
import json
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QAction, QPixmap, QImage
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
)

# -----------------------------------------------------------------------------
# Backend import expectations
# -----------------------------------------------------------------------------
# Save your analysis script as: scratch_assay_analysis.py
# in the same folder as this GUI file.
#
# This GUI uses the following functions from that module:
#   - parse_filename_metadata
#   - load_gray
#   - ensure_dir
#   - build_t0_reference_table
#   - analyze_image
#   - add_closure_metrics
#
# It runs images one-by-one so the GUI can show real progress, keep a live log,
# and support row/image review immediately after the batch finishes.
# -----------------------------------------------------------------------------

IMPORT_ERROR = None
try:
    from scratch_assay_analysis import (
        parse_filename_metadata,
        load_gray,
        ensure_dir,
        build_t0_reference_table,
        analyze_image,
        add_closure_metrics,
    )
except Exception as e:
    IMPORT_ERROR = e
    parse_filename_metadata = None
    load_gray = None
    ensure_dir = None
    build_t0_reference_table = None
    analyze_image = None
    add_closure_metrics = None


# -----------------------------------------------------------------------------
# Data model
# -----------------------------------------------------------------------------

@dataclass
class AnalysisConfig:
    input_dir: str
    output_dir: str
    wound_geometry_mode: str = "auto"
    blur_kernel: int = 5
    background_kernel: int = 101
    std_window: int = 21
    residual_window: int = 9
    corridor_smooth_window: int = 31
    min_corridor_width: int = 20
    threshold_mode: str = "hybrid"
    percentile_value: float = 60.0
    min_open_object_size: int = 100
    morph_close: int = 5
    morph_open: int = 3
    leading_edge_search_radius: int = 120
    edge_smooth_window: int = 21
    min_cell_run_width: int = 12


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def scan_images(input_dir: Path):
    image_paths = []
    for ext in ["*.tif", "*.TIF", "*.tiff", "*.TIFF", "*.png", "*.jpg", "*.jpeg", "*.JPG", "*.JPEG"]:
        image_paths.extend(sorted(input_dir.glob(ext)))
    seen = set()
    deduped = []
    for p in image_paths:
        k = str(p.resolve())
        if k not in seen:
            seen.add(k)
            deduped.append(p)
    return deduped


def dataframe_safe_sort(df: pd.DataFrame) -> pd.DataFrame:
    sort_cols = [c for c in ["group_id", "field_id", "time_value", "filename"] if c in df.columns]
    if sort_cols:
        return df.sort_values(sort_cols, kind="stable").reset_index(drop=True)
    return df.reset_index(drop=True)


def qimage_from_path(image_path: Path):
    if not image_path.exists():
        return None
    img = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None

    if img.ndim == 2:
        h, w = img.shape
        bytes_per_line = w
        qimg = QImage(img.data, w, h, bytes_per_line, QImage.Format_Grayscale8)
        return qimg.copy()

    if img.shape[2] == 3:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        return qimg.copy()

    if img.shape[2] == 4:
        rgba = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
        h, w, ch = rgba.shape
        bytes_per_line = ch * w
        qimg = QImage(rgba.data, w, h, bytes_per_line, QImage.Format_RGBA8888)
        return qimg.copy()

    return None


def boolish_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().isin(["true", "1", "yes"])


# -----------------------------------------------------------------------------
# Worker infrastructure
# -----------------------------------------------------------------------------

class WorkerSignals(QObject):
    started = Signal()
    progress = Signal(int, int, str)     # current, total, filename
    log = Signal(str)
    error = Signal(str)
    finished = Signal(object)            # DataFrame | None


class AnalysisWorker(QRunnable):
    def __init__(self, config: AnalysisConfig):
        super().__init__()
        self.config = config
        self.signals = WorkerSignals()

    def run(self):
        self.signals.started.emit()

        if IMPORT_ERROR is not None:
            self.signals.error.emit(
                "Could not import scratch_assay_analysis.py\n\n"
                f"Import error: {IMPORT_ERROR}"
            )
            self.signals.finished.emit(None)
            return

        try:
            input_dir = Path(self.config.input_dir)
            output_dir = Path(self.config.output_dir)
            mask_dir = output_dir / "masks"
            overlay_dir = output_dir / "overlays"
            debug_dir = output_dir / "debug"

            ensure_dir(output_dir)
            ensure_dir(mask_dir)
            ensure_dir(overlay_dir)
            ensure_dir(debug_dir)

            image_paths = scan_images(input_dir)
            if not image_paths:
                raise ValueError(f"No images found in {input_dir}")

            self.signals.log.emit(f"Found {len(image_paths)} images.")
            self.signals.log.emit("Building time-0 references...")

            t0_ref_df = build_t0_reference_table(
                image_paths=image_paths,
                root_dir=input_dir,
                blur_kernel=self.config.blur_kernel,
                background_kernel=self.config.background_kernel,
                std_window=self.config.std_window,
                residual_window=self.config.residual_window,
                corridor_smooth_window=self.config.corridor_smooth_window,
                min_corridor_width=self.config.min_corridor_width,
            )

            if t0_ref_df.empty:
                raise ValueError("No time-0 images found.")

            self.signals.log.emit(f"Built {len(t0_ref_df)} time-0 references.")

            results = []
            total = len(image_paths)

            for i, image_path in enumerate(image_paths, start=1):
                self.signals.progress.emit(i, total, image_path.name)
                self.signals.log.emit(f"[{i}/{total}] Analyzing {image_path.name}")
                try:
                    row = analyze_image(
                        image_path=image_path,
                        root_dir=input_dir,
                        t0_ref_df=t0_ref_df,
                        mask_dir=mask_dir,
                        overlay_dir=overlay_dir,
                        debug_dir=debug_dir,
                        wound_geometry_mode=self.config.wound_geometry_mode,
                        blur_kernel=self.config.blur_kernel,
                        background_kernel=self.config.background_kernel,
                        std_window=self.config.std_window,
                        residual_window=self.config.residual_window,
                        threshold_mode=self.config.threshold_mode,
                        percentile_value=self.config.percentile_value,
                        min_open_object_size=self.config.min_open_object_size,
                        morph_close=self.config.morph_close,
                        morph_open=self.config.morph_open,
                        leading_edge_search_radius=self.config.leading_edge_search_radius,
                        edge_smooth_window=self.config.edge_smooth_window,
                        min_cell_run_width=self.config.min_cell_run_width,
                    )
                    row["overlay_path"] = str((overlay_dir / f"{image_path.stem}_overlay.png").resolve())
                    row["debug_path"] = str((debug_dir / f"{image_path.stem}_debug.png").resolve())
                    row["mask_path"] = str((mask_dir / f"{image_path.stem}_open_mask.png").resolve())
                    row["source_image_path"] = str(image_path.resolve())
                    self.signals.log.emit(
                        f"    OK | left_edge={row.get('detected_left_edge_px', '')} | "
                        f"open_area={row.get('residual_open_area_px', '')}"
                    )
                    results.append(row)
                except Exception as e:
                    meta = parse_filename_metadata(image_path.name)
                    self.signals.log.emit(f"    FAIL | {e}")
                    results.append({
                        **meta,
                        "error": str(e),
                        "source_image_path": str(image_path.resolve()),
                    })

            df = pd.DataFrame(results)
            df = add_closure_metrics(df)
            df = dataframe_safe_sort(df)

            out_csv = output_dir / "scratch_results.csv"
            df.to_csv(out_csv, index=False)
            self.signals.log.emit(f"Saved results table: {out_csv}")
            self.signals.finished.emit(df)

        except Exception:
            self.signals.error.emit(traceback.format_exc())
            self.signals.finished.emit(None)


# -----------------------------------------------------------------------------
# Results table
# -----------------------------------------------------------------------------

class ResultsTable(QTableWidget):
    row_selected = Signal(int)

    def __init__(self):
        super().__init__()
        self._df = pd.DataFrame()
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.horizontalHeader().setStretchLastSection(True)
        self.itemSelectionChanged.connect(self._emit_current_row)

    def set_dataframe(self, df: pd.DataFrame):
        self._df = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
        self.setSortingEnabled(False)
        self.clear()

        if self._df.empty:
            self.setRowCount(0)
            self.setColumnCount(0)
            self.setSortingEnabled(True)
            return

        display_df = self._df.copy()
        for col in display_df.columns:
            if pd.api.types.is_float_dtype(display_df[col]):
                display_df[col] = display_df[col].map(lambda x: "" if pd.isna(x) else f"{x:.3f}")
            else:
                display_df[col] = display_df[col].astype(str).replace("nan", "")

        self.setRowCount(len(display_df))
        self.setColumnCount(len(display_df.columns))
        self.setHorizontalHeaderLabels([str(c) for c in display_df.columns])

        for r in range(len(display_df)):
            for c, col in enumerate(display_df.columns):
                item = QTableWidgetItem(display_df.iat[r, c])
                self.setItem(r, c, item)

        self.setSortingEnabled(True)
        self.resizeColumnsToContents()
        if len(display_df) > 0:
            self.selectRow(0)

    def _emit_current_row(self):
        row = self.currentRow()
        if row >= 0:
            self.row_selected.emit(row)


# -----------------------------------------------------------------------------
# Image viewer
# -----------------------------------------------------------------------------

class ImagePreviewPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.current_qimage = None

        self.view_mode = QComboBox()
        self.view_mode.addItems(["Source", "Overlay", "Debug", "Mask"])

        self.fit_check = QCheckBox("Fit to panel")
        self.fit_check.setChecked(True)

        self.title_label = QLabel("No image selected")
        self.title_label.setWordWrap(True)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(300, 300)
        self.image_label.setStyleSheet("QLabel { background: #111; color: #ddd; border: 1px solid #444; }")
        self.image_label.setText("No preview")

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Preview"))
        controls.addWidget(self.view_mode)
        controls.addWidget(self.fit_check)
        controls.addStretch(1)
        layout.addLayout(controls)
        layout.addWidget(self.title_label)
        layout.addWidget(self.image_label, 1)

        self.view_mode.currentTextChanged.connect(self.refresh_display)
        self.fit_check.stateChanged.connect(self.refresh_display)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh_display()

    def set_row(self, row: dict | None):
        self._row = row or {}
        self.refresh_display()

    def selected_path(self):
        if not hasattr(self, "_row") or not self._row:
            return None
        mode = self.view_mode.currentText().lower()
        key_map = {
            "source": "source_image_path",
            "overlay": "overlay_path",
            "debug": "debug_path",
            "mask": "mask_path",
        }
        key = key_map.get(mode)
        p = self._row.get(key)
        return Path(p) if p else None

    def refresh_display(self):
        img_path = self.selected_path()
        if img_path is None:
            self.title_label.setText("No image selected")
            self.current_qimage = None
            self.image_label.setText("No preview")
            self.image_label.setPixmap(QPixmap())
            return

        self.title_label.setText(str(img_path))
        qimg = qimage_from_path(img_path)
        self.current_qimage = qimg

        if qimg is None:
            self.image_label.setText("Preview unavailable")
            self.image_label.setPixmap(QPixmap())
            return

        pix = QPixmap.fromImage(qimg)
        if self.fit_check.isChecked():
            pix = pix.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(pix)


# -----------------------------------------------------------------------------
# Inspector panel
# -----------------------------------------------------------------------------

class InspectorPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.form = QFormLayout(self)
        self.form.setContentsMargins(8, 8, 8, 8)
        self.form.setSpacing(6)
        self.labels = {}

        for key in [
            "filename", "time_value", "field_id", "group_id",
            "detected_left_edge_px", "analysis_roi_left_px", "analysis_roi_right_px",
            "analysis_roi_width_px", "residual_open_area_px", "percent_closure",
            "flag_empty_open_mask", "flag_nearly_closed", "error"
        ]:
            lab = QLabel("")
            lab.setWordWrap(True)
            self.labels[key] = lab
            self.form.addRow(key, lab)

    def set_row(self, row: dict | None):
        row = row or {}
        for key, lab in self.labels.items():
            val = row.get(key, "")
            if isinstance(val, float):
                txt = "" if pd.isna(val) else f"{val:.3f}"
            else:
                txt = "" if val is None else str(val)
            lab.setText(txt)


# -----------------------------------------------------------------------------
# File list / browser
# -----------------------------------------------------------------------------

class ImageBrowserPanel(QWidget):
    row_selected = Signal(int)

    def __init__(self):
        super().__init__()
        self.list_widget = QListWidget()
        self.prev_btn = QPushButton("Previous")
        self.next_btn = QPushButton("Next")

        layout = QVBoxLayout(self)
        nav = QHBoxLayout()
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        layout.addLayout(nav)
        layout.addWidget(self.list_widget, 1)

        self.prev_btn.clicked.connect(self.select_prev)
        self.next_btn.clicked.connect(self.select_next)
        self.list_widget.currentRowChanged.connect(self.row_selected.emit)

    def set_dataframe(self, df: pd.DataFrame):
        self.list_widget.clear()
        if df is None or df.empty:
            return
        for _, row in df.iterrows():
            name = row.get("filename", "")
            status = "FAIL" if pd.notna(row.get("error", np.nan)) else "OK"
            item = QListWidgetItem(f"[{status}] {name}")
            self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def set_current_row(self, row: int):
        if 0 <= row < self.list_widget.count() and self.list_widget.currentRow() != row:
            self.list_widget.setCurrentRow(row)

    def select_prev(self):
        r = self.list_widget.currentRow()
        if r > 0:
            self.list_widget.setCurrentRow(r - 1)

    def select_next(self):
        r = self.list_widget.currentRow()
        if r < self.list_widget.count() - 1:
            self.list_widget.setCurrentRow(r + 1)


# -----------------------------------------------------------------------------
# Parameter panel with presets
# -----------------------------------------------------------------------------

class ParameterPanel(QWidget):
    def __init__(self):
        super().__init__()

        self.input_edit = QLineEdit()
        self.output_edit = QLineEdit()

        self.blur_kernel = QSpinBox(); self.blur_kernel.setRange(1, 999); self.blur_kernel.setValue(5)
        self.background_kernel = QSpinBox(); self.background_kernel.setRange(1, 9999); self.background_kernel.setValue(101)
        self.std_window = QSpinBox(); self.std_window.setRange(1, 999); self.std_window.setValue(21)
        self.residual_window = QSpinBox(); self.residual_window.setRange(1, 999); self.residual_window.setValue(9)
        self.corridor_smooth_window = QSpinBox(); self.corridor_smooth_window.setRange(1, 999); self.corridor_smooth_window.setValue(31)
        self.min_corridor_width = QSpinBox(); self.min_corridor_width.setRange(1, 5000); self.min_corridor_width.setValue(20)

        self.threshold_mode = QComboBox(); self.threshold_mode.addItems(["percentile", "otsu", "hybrid"])
        self.threshold_mode.setCurrentText("hybrid")
        self.percentile_value = QDoubleSpinBox(); self.percentile_value.setRange(0.0, 100.0); self.percentile_value.setDecimals(2); self.percentile_value.setValue(60.0)
        self.min_open_object_size = QSpinBox(); self.min_open_object_size.setRange(1, 10000000); self.min_open_object_size.setValue(100)
        self.morph_close = QSpinBox(); self.morph_close.setRange(1, 999); self.morph_close.setValue(5)
        self.morph_open = QSpinBox(); self.morph_open.setRange(1, 999); self.morph_open.setValue(3)

        self.leading_edge_search_radius = QSpinBox(); self.leading_edge_search_radius.setRange(1, 5000); self.leading_edge_search_radius.setValue(120)
        self.edge_smooth_window = QSpinBox(); self.edge_smooth_window.setRange(1, 999); self.edge_smooth_window.setValue(21)
        self.min_cell_run_width = QSpinBox(); self.min_cell_run_width.setRange(1, 5000); self.min_cell_run_width.setValue(12)

        self.save_preset_btn = QPushButton("Save preset…")
        self.load_preset_btn = QPushButton("Load preset…")

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        paths_box = QGroupBox("Paths")
        paths_form = QGridLayout(paths_box)
        input_btn = QPushButton("Browse…")
        output_btn = QPushButton("Browse…")
        input_btn.clicked.connect(self.choose_input_dir)
        output_btn.clicked.connect(self.choose_output_dir)
        paths_form.addWidget(QLabel("Input folder"), 0, 0)
        paths_form.addWidget(self.input_edit, 0, 1)
        paths_form.addWidget(input_btn, 0, 2)
        paths_form.addWidget(QLabel("Output folder"), 1, 0)
        paths_form.addWidget(self.output_edit, 1, 1)
        paths_form.addWidget(output_btn, 1, 2)

        preprocess_box = QGroupBox("Preprocessing")
        preprocess_form = QFormLayout(preprocess_box)
        preprocess_form.addRow("Blur kernel", self.blur_kernel)
        preprocess_form.addRow("Background kernel", self.background_kernel)
        preprocess_form.addRow("STD window", self.std_window)
        preprocess_form.addRow("Residual window", self.residual_window)

        corridor_box = QGroupBox("Time-0 corridor detection")
        corridor_form = QFormLayout(corridor_box)
        corridor_form.addRow("Corridor smooth window", self.corridor_smooth_window)
        corridor_form.addRow("Min corridor width", self.min_corridor_width)

        segmentation_box = QGroupBox("Open-region segmentation")
        segmentation_form = QFormLayout(segmentation_box)
        segmentation_form.addRow("Threshold mode", self.threshold_mode)
        segmentation_form.addRow("Percentile value", self.percentile_value)
        segmentation_form.addRow("Min open object size", self.min_open_object_size)
        segmentation_form.addRow("Morph close", self.morph_close)
        segmentation_form.addRow("Morph open", self.morph_open)

        edge_box = QGroupBox("Left-edge alignment")
        edge_form = QFormLayout(edge_box)
        edge_form.addRow("Leading-edge search radius", self.leading_edge_search_radius)
        edge_form.addRow("Edge smooth window", self.edge_smooth_window)
        edge_form.addRow("Min cell run width", self.min_cell_run_width)

        preset_box = QGroupBox("Presets")
        preset_layout = QHBoxLayout(preset_box)
        preset_layout.addWidget(self.save_preset_btn)
        preset_layout.addWidget(self.load_preset_btn)

        layout.addWidget(paths_box)
        layout.addWidget(preprocess_box)
        layout.addWidget(corridor_box)
        layout.addWidget(segmentation_box)
        layout.addWidget(edge_box)
        layout.addWidget(preset_box)
        layout.addStretch(1)

    def _connect_signals(self):
        self.threshold_mode.currentTextChanged.connect(self._update_threshold_controls)
        self.save_preset_btn.clicked.connect(self.save_preset)
        self.load_preset_btn.clicked.connect(self.load_preset)
        self._update_threshold_controls(self.threshold_mode.currentText())

    def _update_threshold_controls(self, mode: str):
        self.percentile_value.setEnabled(mode in {"percentile", "hybrid"})

    def choose_input_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select input folder")
        if folder:
            self.input_edit.setText(folder)
            if not self.output_edit.text().strip():
                self.output_edit.setText(str(Path(folder) / "scratch_results_gui"))

    def choose_output_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select output folder")
        if folder:
            self.output_edit.setText(folder)

    def config(self) -> AnalysisConfig:
        return AnalysisConfig(
            input_dir=self.input_edit.text().strip(),
            output_dir=self.output_edit.text().strip(),
            blur_kernel=self.blur_kernel.value(),
            background_kernel=self.background_kernel.value(),
            std_window=self.std_window.value(),
            residual_window=self.residual_window.value(),
            corridor_smooth_window=self.corridor_smooth_window.value(),
            min_corridor_width=self.min_corridor_width.value(),
            threshold_mode=self.threshold_mode.currentText(),
            percentile_value=self.percentile_value.value(),
            min_open_object_size=self.min_open_object_size.value(),
            morph_close=self.morph_close.value(),
            morph_open=self.morph_open.value(),
            leading_edge_search_radius=self.leading_edge_search_radius.value(),
            edge_smooth_window=self.edge_smooth_window.value(),
            min_cell_run_width=self.min_cell_run_width.value(),
        )

    def apply_config(self, cfg: AnalysisConfig):
        self.input_edit.setText(cfg.input_dir)
        self.output_edit.setText(cfg.output_dir)
        self.blur_kernel.setValue(cfg.blur_kernel)
        self.background_kernel.setValue(cfg.background_kernel)
        self.std_window.setValue(cfg.std_window)
        self.residual_window.setValue(cfg.residual_window)
        self.corridor_smooth_window.setValue(cfg.corridor_smooth_window)
        self.min_corridor_width.setValue(cfg.min_corridor_width)
        self.threshold_mode.setCurrentText(cfg.threshold_mode)
        self.percentile_value.setValue(cfg.percentile_value)
        self.min_open_object_size.setValue(cfg.min_open_object_size)
        self.morph_close.setValue(cfg.morph_close)
        self.morph_open.setValue(cfg.morph_open)
        self.leading_edge_search_radius.setValue(cfg.leading_edge_search_radius)
        self.edge_smooth_window.setValue(cfg.edge_smooth_window)
        self.min_cell_run_width.setValue(cfg.min_cell_run_width)

    def save_preset(self):
        out_path, _ = QFileDialog.getSaveFileName(self, "Save preset", "scratch_preset.json", "JSON Files (*.json)")
        if not out_path:
            return
        cfg = self.config()
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(asdict(cfg), f, indent=2)
        QMessageBox.information(self, "Preset saved", f"Saved preset to:\n{out_path}")

    def load_preset(self):
        in_path, _ = QFileDialog.getOpenFileName(self, "Load preset", "", "JSON Files (*.json)")
        if not in_path:
            return
        with open(in_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = AnalysisConfig(**data)
        self.apply_config(cfg)
        QMessageBox.information(self, "Preset loaded", f"Loaded preset from:\n{in_path}")


# -----------------------------------------------------------------------------
# Main window
# -----------------------------------------------------------------------------

class ScratchAssayMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Scratch Assay Review Workstation")
        self.resize(1850, 1050)

        self.thread_pool = QThreadPool.globalInstance()
        self.current_df = pd.DataFrame()
        self.filtered_df = pd.DataFrame()

        self.params = ParameterPanel()
        self.results_table = ResultsTable()
        self.browser = ImageBrowserPanel()
        self.preview = ImagePreviewPanel()
        self.inspector = InspectorPanel()
        self.log_box = QPlainTextEdit(); self.log_box.setReadOnly(True)

        self.summary_label = QLabel("No analysis run yet.")
        self.summary_label.setWordWrap(True)

        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        self.progress.setMaximum(100)
        self.progress.setValue(0)

        self.run_btn = QPushButton("Run analysis")
        self.export_btn = QPushButton("Export table as CSV")
        self.open_output_btn = QPushButton("Open output folder")
        self.reload_btn = QPushButton("Reload scratch_results.csv")

        self.filter_mode = QComboBox()
        self.filter_mode.addItems(["All rows", "Successful only", "Failed only", "Flagged QC only"])

        self._build_ui()
        self._build_menu()
        self._connect_signals()

        if IMPORT_ERROR is not None:
            self.append_log(
                "WARNING: Could not import scratch_assay_analysis.py\n"
                f"Reason: {IMPORT_ERROR}"
            )

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        top_split = QSplitter(Qt.Horizontal)
        top_split.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.params)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.run_btn)
        toolbar.addWidget(self.export_btn)
        toolbar.addWidget(self.reload_btn)
        toolbar.addWidget(self.open_output_btn)
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("Filter"))
        toolbar.addWidget(self.filter_mode)
        toolbar.addStretch(1)

        center_layout.addLayout(toolbar)
        center_layout.addWidget(self.progress)
        center_layout.addWidget(self.summary_label)
        center_layout.addWidget(self.preview, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Image browser"))
        right_layout.addWidget(self.browser, 1)
        right_layout.addWidget(QLabel("Row inspector"))
        right_layout.addWidget(self.inspector)

        top_split.addWidget(left)
        top_split.addWidget(center)
        top_split.addWidget(right)
        top_split.setSizes([400, 980, 420])

        bottom_tabs = QTabWidget()

        table_tab = QWidget()
        table_layout = QVBoxLayout(table_tab)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addWidget(self.results_table)

        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.addWidget(self.log_box)

        bottom_tabs.addTab(table_tab, "Batch results")
        bottom_tabs.addTab(log_tab, "Run log")

        vertical = QSplitter(Qt.Vertical)
        vertical.setChildrenCollapsible(False)
        vertical.addWidget(top_split)
        vertical.addWidget(bottom_tabs)
        vertical.setSizes([650, 300])

        root.addWidget(vertical)

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("File")

        run_action = QAction("Run analysis", self)
        run_action.triggered.connect(self.run_analysis)
        file_menu.addAction(run_action)

        reload_action = QAction("Reload scratch_results.csv", self)
        reload_action.triggered.connect(self.reload_results)
        file_menu.addAction(reload_action)

        export_action = QAction("Export current table", self)
        export_action.triggered.connect(self.export_table)
        file_menu.addAction(export_action)

        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def _connect_signals(self):
        self.run_btn.clicked.connect(self.run_analysis)
        self.export_btn.clicked.connect(self.export_table)
        self.reload_btn.clicked.connect(self.reload_results)
        self.open_output_btn.clicked.connect(self.open_output_folder)
        self.filter_mode.currentTextChanged.connect(self.apply_filter)
        self.results_table.row_selected.connect(self.on_row_selected)
        self.browser.row_selected.connect(self.on_row_selected_from_browser)

    def append_log(self, text: str):
        self.log_box.appendPlainText(text)
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def validate_config(self, cfg: AnalysisConfig) -> bool:
        if not cfg.input_dir:
            QMessageBox.warning(self, "Missing input", "Please select an input folder.")
            return False
        if not Path(cfg.input_dir).exists():
            QMessageBox.warning(self, "Invalid input", "The selected input folder does not exist.")
            return False
        if not cfg.output_dir:
            QMessageBox.warning(self, "Missing output", "Please select an output folder.")
            return False
        return True

    def set_busy(self, busy: bool):
        self.run_btn.setEnabled(not busy)
        self.reload_btn.setEnabled(not busy)
        self.export_btn.setEnabled((not busy) and (not self.filtered_df.empty))
        self.open_output_btn.setEnabled((not busy) and bool(self.params.output_edit.text().strip()))
        if not busy:
            self.progress.setValue(0)

    def run_analysis(self):
        cfg = self.params.config()
        if not self.validate_config(cfg):
            return

        Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)
        self.append_log("=" * 90)
        self.append_log("Queued analysis run")
        self.append_log(f"Input:  {cfg.input_dir}")
        self.append_log(f"Output: {cfg.output_dir}")
        self.set_busy(True)

        worker = AnalysisWorker(cfg)
        worker.signals.started.connect(lambda: self.append_log("Worker started."))
        worker.signals.log.connect(self.append_log)
        worker.signals.error.connect(self.on_error)
        worker.signals.progress.connect(self.on_progress)
        worker.signals.finished.connect(self.on_finished)
        self.thread_pool.start(worker)

    def on_progress(self, current: int, total: int, filename: str):
        if total > 0:
            self.progress.setValue(int(round(100 * current / total)))
        self.summary_label.setText(f"Running: {current}/{total} | {filename}")

    def on_error(self, message: str):
        self.append_log("ERROR:\n" + message)
        QMessageBox.critical(self, "Analysis failed", message)

    def on_finished(self, df):
        self.set_busy(False)
        if not isinstance(df, pd.DataFrame):
            self.current_df = pd.DataFrame()
            self.filtered_df = pd.DataFrame()
            self.results_table.set_dataframe(self.filtered_df)
            self.browser.set_dataframe(self.filtered_df)
            self.summary_label.setText("Analysis did not return a valid result table.")
            return

        self.current_df = df.copy()
        self.apply_filter()
        self.append_log(f"Analysis finished. Loaded {len(self.current_df)} rows.")

    def apply_filter(self):
        df = self.current_df.copy() if isinstance(self.current_df, pd.DataFrame) else pd.DataFrame()
        if df.empty:
            self.filtered_df = df
            self.results_table.set_dataframe(df)
            self.browser.set_dataframe(df)
            self.summary_label.setText("No analysis run yet.")
            self.export_btn.setEnabled(False)
            return

        mode = self.filter_mode.currentText()
        fdf = df.copy()

        if mode == "Successful only":
            if "error" in fdf.columns:
                fdf = fdf[fdf["error"].isna()]
        elif mode == "Failed only":
            if "error" in fdf.columns:
                fdf = fdf[fdf["error"].notna()]
        elif mode == "Flagged QC only":
            qc_cols = [
                c for c in [
                    "flag_empty_roi", "flag_empty_open_mask",
                    "flag_open_touches_left_border", "flag_open_touches_right_border",
                    "flag_nearly_closed"
                ] if c in fdf.columns
            ]
            if qc_cols:
                mask = pd.Series(False, index=fdf.index)
                for c in qc_cols:
                    mask = mask | boolish_series(fdf[c])
                fdf = fdf[mask]
            else:
                fdf = fdf.iloc[0:0]

        fdf = fdf.reset_index(drop=True)
        self.filtered_df = fdf
        self.results_table.set_dataframe(fdf)
        self.browser.set_dataframe(fdf)
        self.export_btn.setEnabled(not fdf.empty)
        self.update_summary(fdf, df)

    def update_summary(self, shown_df: pd.DataFrame, full_df: pd.DataFrame):
        if full_df.empty:
            self.summary_label.setText("No analysis run yet.")
            return

        n_total = len(full_df)
        n_shown = len(shown_df)
        n_errors = int(full_df["error"].notna().sum()) if "error" in full_df.columns else 0
        n_ok = n_total - n_errors

        parts = [f"Shown: {n_shown}/{n_total}", f"Successful: {n_ok}", f"Failed: {n_errors}"]

        if "percent_closure" in shown_df.columns:
            vals = pd.to_numeric(shown_df["percent_closure"], errors="coerce").dropna()
            if len(vals) > 0:
                parts.append(f"Median closure: {vals.median():.2f}%")

        if "residual_open_area_px" in shown_df.columns:
            vals = pd.to_numeric(shown_df["residual_open_area_px"], errors="coerce").dropna()
            if len(vals) > 0:
                parts.append(f"Median open area: {vals.median():.1f}px")

        self.summary_label.setText(" | ".join(parts))

    def current_row_dict(self, row: int):
        if self.filtered_df.empty or row < 0 or row >= len(self.filtered_df):
            return None
        return self.filtered_df.iloc[row].to_dict()

    def on_row_selected(self, row: int):
        self.browser.set_current_row(row)
        row_dict = self.current_row_dict(row)
        self.preview.set_row(row_dict)
        self.inspector.set_row(row_dict)

    def on_row_selected_from_browser(self, row: int):
        if 0 <= row < self.results_table.rowCount() and self.results_table.currentRow() != row:
            self.results_table.selectRow(row)
        row_dict = self.current_row_dict(row)
        self.preview.set_row(row_dict)
        self.inspector.set_row(row_dict)

    def export_table(self):
        if self.filtered_df.empty:
            QMessageBox.information(self, "Nothing to export", "No displayed rows to export.")
            return
        default_path = Path(self.params.output_edit.text().strip() or ".") / "scratch_results_export.csv"
        out_path, _ = QFileDialog.getSaveFileName(self, "Export table", str(default_path), "CSV Files (*.csv)")
        if not out_path:
            return
        self.filtered_df.to_csv(out_path, index=False)
        self.append_log(f"Exported displayed table to: {out_path}")
        QMessageBox.information(self, "Export complete", f"Saved:\n{out_path}")

    def reload_results(self):
        output_dir = Path(self.params.output_edit.text().strip() or ".")
        csv_path = output_dir / "scratch_results.csv"
        if not csv_path.exists():
            QMessageBox.warning(self, "No results file", f"Could not find:\n{csv_path}")
            return
        df = pd.read_csv(csv_path)
        self.current_df = dataframe_safe_sort(df)
        self.apply_filter()
        self.append_log(f"Reloaded results from: {csv_path}")

    def open_output_folder(self):
        output = self.params.output_edit.text().strip()
        if not output:
            return
        path = Path(output)
        path.mkdir(parents=True, exist_ok=True)

        import subprocess
        import platform
        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.run(["open", str(path)], check=False)
            elif system == "Windows":
                subprocess.run(["explorer", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as e:
            QMessageBox.warning(self, "Could not open folder", str(e))


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    window = ScratchAssayMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
