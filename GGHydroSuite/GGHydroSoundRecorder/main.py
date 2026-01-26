from PySide6.QtWidgets import QApplication
from app.main_window import MainWindow

def main():
    app = QApplication([])
    app.setStyle("Fusion")

    w = MainWindow()
    w.show()

    app.exec()

if __name__ == "__main__":
    main()