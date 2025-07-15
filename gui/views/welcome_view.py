"""
欢迎页面视图类，用于显示欢迎信息
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QHBoxLayout,
    QFrame,
    QSizePolicy,
)
from PySide6.QtGui import QFont, QPixmap, QColor, QPalette


class WelcomeView(QWidget):
    """欢迎页面视图，显示欢迎信息"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        card = QFrame(self)
        card.setObjectName("WelcomeCardFrame")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setFrameShadow(QFrame.Shadow.Raised)

        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(15)
        card_layout.setContentsMargins(25, 25, 25, 25)

        title_layout = QHBoxLayout()

        icon_label = QLabel()
        icon = QPixmap(":/icons/app_icon.png")
        if icon.isNull():
            from PySide6.QtWidgets import QStyle

            icon = (
                self.style()
                .standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
                .pixmap(64, 64)
            )
        icon_label.setPixmap(icon)
        icon_label.setFixedSize(64, 64)
        title_layout.addWidget(icon_label)

        welcome_label = QLabel("欢迎使用 邻里+")
        welcome_label.setObjectName("WelcomeTitle")
        font = QFont()
        font.setPointSize(24)
        font.setBold(True)
        welcome_label.setFont(font)
        title_layout.addWidget(
            welcome_label, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        card_layout.addLayout(title_layout)

        separator = QFrame()
        separator.setObjectName("WelcomeSeparator")
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        card_layout.addWidget(separator)

        subtitle = QLabel("快速开始使用")
        subtitle.setObjectName("WelcomeSubtitle")
        subtitle_font = QFont()
        subtitle_font.setPointSize(14)
        subtitle_font.setBold(True)
        subtitle.setFont(subtitle_font)
        card_layout.addWidget(subtitle)

        instructions_frame = QFrame()
        instructions_frame.setObjectName("InstructionsFrame")
        instructions_layout = QVBoxLayout(instructions_frame)

        step1_layout = QHBoxLayout()
        step1_number = QLabel("1")
        step1_number.setObjectName("Step1Number")
        step1_number.setProperty("class", "StepNumber")
        step1_label = QLabel("从左侧列表中选择一个在线设备")
        step1_label.setProperty("class", "StepLabel")
        step1_layout.addWidget(step1_number)
        step1_layout.addWidget(step1_label, 1)
        instructions_layout.addLayout(step1_layout)

        step2_layout = QHBoxLayout()
        step2_number = QLabel("2")
        step2_number.setObjectName("Step2Number")
        step2_number.setProperty("class", "StepNumber")
        step2_label = QLabel("选择该设备的共享文件夹")
        step2_label.setProperty("class", "StepLabel")
        step2_layout.addWidget(step2_number)
        step2_layout.addWidget(step2_label, 1)
        instructions_layout.addLayout(step2_layout)

        step3_layout = QHBoxLayout()
        step3_number = QLabel("3")
        step3_number.setObjectName("Step3Number")
        step3_number.setProperty("class", "StepNumber")
        step3_label = QLabel("开始浏览、上传和下载文件")
        step3_label.setProperty("class", "StepLabel")
        step3_layout.addWidget(step3_number)
        step3_layout.addWidget(step3_label, 1)
        instructions_layout.addLayout(step3_layout)

        card_layout.addWidget(instructions_frame)

        tip_label = QLabel("提示：您也可以通过拖放文件到文件列表区域来快速上传文件")
        tip_label.setObjectName("WelcomeTip")
        card_layout.addWidget(tip_label)

        layout.addStretch()
        layout.addWidget(card)
        layout.addStretch()
