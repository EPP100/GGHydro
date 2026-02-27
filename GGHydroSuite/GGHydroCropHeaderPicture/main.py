import sys
from io import BytesIO
from typing import Tuple

from PIL import Image

from PyQt6.QtCore import Qt, QBuffer, QByteArray
from PyQt6.QtGui import QImage, QPixmap, QGuiApplication, QKeySequence
from PyQt6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout, QHBoxLayout, QSpinBox, QPushButton


# ============
# CONFIG
# ============
# Set your fixed header height (in pixels) here.
# This value will be cropped from the TOP of every pasted image.
HEADER_PX = 110


# ============
# Utilities
# ============
def crop_fixed_top(img: Image.Image, header_px: int) -> Tuple[Image.Image, int]:
    """Crop a fixed number of pixels from the top of the image."""
    w, h = img.size
    header_px = max(0, min(header_px, h - 1))  # keep safe bounds
    if header_px <= 0:
        return img, 0
    return img.crop((0, header_px, w, h)), header_px


def qimage_to_pil(qimg: QImage) -> Image.Image:
    """Convert QImage -> PIL Image using an in-memory buffer."""
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.OpenModeFlag.ReadWrite)
    qimg.save(buf, b"PNG")
    data = bytes(buf.data())
    return Image.open(BytesIO(data)).convert("RGB")


def pil_to_qimage(pil_img: Image.Image) -> QImage:
    """Convert PIL Image -> QImage."""
    bio = BytesIO()
    pil_img.save(bio, format="PNG")
    data = bio.getvalue()
    return QImage.fromData(data, "PNG")


# ============
# Qt Window
# ============
class CropPasteWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Paste Image → Fixed Top Crop (Qt6)")
        self.resize(840, 560)

        # Info + instructions
        self.info = QLabel(
            "👉 Press Ctrl+V to paste an image.\n"
            "The app removes a FIXED number of pixels from the TOP and copies the result to the clipboard.\n"
            "Tip: Use Ctrl+C to copy the current result again.",
            self
        )
        self.info.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Image preview area
        self.image_label = QLabel("", self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background: #202020; color: #ddd;")
        self.image_label.setMinimumSize(200, 160)

        # Header height control (so you can tweak without editing code)
        controls = QHBoxLayout()
        controls.setSpacing(12)

        self.spin_header = QSpinBox(self)
        self.spin_header.setRange(1, 4000)
        self.spin_header.setValue(HEADER_PX)
        self.spin_header.setSuffix(" px")
        self.spin_header.setToolTip("Fixed pixels to remove from the top of pasted images.")

        self.btn_copy = QPushButton("Copy Result (Ctrl+C)", self)
        self.btn_copy.clicked.connect(self.copy_result_to_clipboard)

        controls.addWidget(QLabel("Top crop:", self))
        controls.addWidget(self.spin_header)
        controls.addStretch(1)
        controls.addWidget(self.btn_copy)

        # Layout
        layout = QVBoxLayout()
        layout.addWidget(self.info)
        layout.addLayout(controls)
        layout.addWidget(self.image_label, stretch=1)
        self.setLayout(layout)

        self._current_qimage = None  # last processed image (QImage)

    # Keyboard shortcuts
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            self.handle_paste()
        elif event.matches(QKeySequence.StandardKey.Copy):
            self.copy_result_to_clipboard()
        else:
            super().keyPressEvent(event)

    # Keep preview fitted on resize
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_qimage is not None:
            self.show_qimage(self._current_qimage)

    # Handle image paste from clipboard
    def handle_paste(self):
        cb = QGuiApplication.clipboard()
        mime = cb.mimeData()

        if mime.hasImage():
            qimg = cb.image()
            if qimg.isNull():
                self.info.setText("⚠️ Could not read image from clipboard.")
                return

            # QImage -> PIL
            pil_img = qimage_to_pil(qimg)

            # Fixed crop
            header_px = int(self.spin_header.value())
            cropped_pil, cropped_px = crop_fixed_top(pil_img, header_px)

            # PIL -> QImage
            out_qimg = pil_to_qimage(cropped_pil)

            # Display + info
            self._current_qimage = out_qimg
            self.show_qimage(out_qimg)
            self.info.setText(f"✔ Cropped fixed {cropped_px} px from top. "
                              f"Result copied to clipboard. Paste anywhere.")

            # Auto-copy processed image to clipboard
            cb.setImage(out_qimg)

        else:
            self.info.setText("📋 Clipboard does not contain an image. "
                              "Copy an image first, then press Ctrl+V here.")

    # Render QImage into preview label (scaled)
    def show_qimage(self, qimg: QImage):
        pix = QPixmap.fromImage(qimg)
        scaled = pix.scaled(
            self.image_label.width(),
            self.image_label.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.image_label.setPixmap(scaled)

    def copy_result_to_clipboard(self):
        if self._current_qimage is None:
            self.info.setText("Nothing to copy yet. Paste an image first (Ctrl+V).")
            return
        QGuiApplication.clipboard().setImage(self._current_qimage)
        self.info.setText("📋 Processed image copied to clipboard.")


def main():
    app = QApplication(sys.argv)
    win = CropPasteWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()