from PySide6.QtWidgets import QApplication
from app.project_selector import ProjectSelectorWindow

def main():
    app = QApplication([])
    app.setStyle("Fusion")

    w = ProjectSelectorWindow()
    w.show()

    app.exec()

if __name__ == "__main__":
    main()
