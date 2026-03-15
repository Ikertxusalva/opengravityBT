"""Panel de chat con Groq LLM para analisis y correccion de estrategias."""
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QLineEdit, QPushButton, QFrame,
    QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QTextCursor

# --- Colores del tema ---
C_BG = "#0d1117"
C_SIDEBAR = "#161b22"
C_SURFACE = "#21262d"
C_BORDER = "#30363d"
C_TEXT = "#e6edf3"
C_TEXT_SEC = "#c9d1d9"
C_MUTED = "#8b949e"
C_SUBTLE = "#6e7681"
C_ACCENT = "#58a6ff"
C_GREEN = "#3fb950"
C_RED = "#f85149"
C_YELLOW = "#d29922"
C_PURPLE = "#bc8cff"
C_ORANGE = "#f0883e"
C_HOVER = "#1c2128"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """Eres un experto en trading algoritmico y backtesting con Python.
Tu rol es ayudar a analizar, corregir y mejorar estrategias de trading.
Usamos la libreria backtesting.py con pandas-ta para indicadores.
Responde de forma concisa y directa. Si te muestran codigo, analiza errores y sugiere mejoras.
Responde siempre en español."""



class GroqWorker(QThread):
    """Worker thread para llamadas a la API de Groq sin bloquear la UI."""
    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, messages: list[dict], parent=None):
        super().__init__(parent)
        self.messages = messages

    def run(self):
        try:
            from groq import Groq
            client = Groq(api_key=GROQ_API_KEY)
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=self.messages,
                temperature=0.7,
                max_completion_tokens=2048,
            )
            text = completion.choices[0].message.content or ""
            self.response_ready.emit(text)
        except Exception as e:
            self.error_occurred.emit(str(e))


class ChatMessage(QFrame):
    """Burbuja de mensaje individual en el chat."""

    def __init__(self, text: str, is_user: bool, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        # Header: nombre + hora
        header = QLabel("Tu" if is_user else "Groq AI")
        header_color = C_ACCENT if is_user else C_ORANGE
        header.setStyleSheet(
            f"color: {header_color}; font-size: 10px; font-weight: 700; "
            f"background: transparent;"
        )
        layout.addWidget(header)

        # Contenido del mensaje
        content = QLabel(text)
        content.setWordWrap(True)
        content.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        bg_color = "rgba(88,166,255,0.08)" if is_user else "rgba(240,136,62,0.08)"
        border_color = "rgba(88,166,255,0.2)" if is_user else "rgba(240,136,62,0.2)"
        content.setStyleSheet(
            f"color: {C_TEXT}; font-size: 12px; line-height: 1.5; "
            f"background-color: {bg_color}; "
            f"border: 1px solid {border_color}; "
            f"border-radius: 8px; padding: 10px 12px;"
        )
        layout.addWidget(content)



class GroqChatPanel(QWidget):
    """Panel de chat con Groq LLM integrado para analizar estrategias."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(250)
        self._strategy_code: str = ""
        self._strategy_name: str = ""
        self._messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        self._worker: GroqWorker | None = None

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Header ---
        header = QWidget()
        header.setFixedHeight(40)
        header.setStyleSheet(
            f"background-color: {C_SIDEBAR}; "
            f"border-bottom: 1px solid {C_BORDER};"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 0, 12, 0)
        header_layout.setSpacing(8)

        # Dot naranja
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {C_ORANGE}; font-size: 8px;")
        dot.setFixedWidth(12)
        header_layout.addWidget(dot)

        title = QLabel("Strategy Chat")
        title.setStyleSheet(
            f"color: {C_TEXT}; font-size: 12px; font-weight: 600;"
        )
        header_layout.addWidget(title)

        header_layout.addStretch()

        # Badge del modelo
        model_badge = QLabel("Groq")
        model_badge.setStyleSheet(
            f"color: {C_ORANGE}; background-color: rgba(240,136,62,0.15); "
            f"padding: 2px 8px; border-radius: 4px; "
            f"font-size: 9px; font-weight: 600;"
        )
        model_badge.setFixedHeight(18)
        header_layout.addWidget(model_badge)

        # Boton limpiar chat
        clear_btn = QPushButton("✕")
        clear_btn.setFixedSize(22, 22)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setToolTip("Limpiar conversacion")
        clear_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {C_SUBTLE}; "
            f"border: none; border-radius: 4px; font-size: 12px; }}"
            f"QPushButton:hover {{ color: {C_TEXT}; background: {C_SURFACE}; }}"
        )
        clear_btn.clicked.connect(self._clear_chat)
        header_layout.addWidget(clear_btn)

        layout.addWidget(header)

        # --- Chat area (scroll) ---
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet(
            f"QScrollArea {{ background-color: {C_BG}; border: none; }}"
            f"QScrollBar:vertical {{ background-color: {C_BG}; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background-color: {C_BORDER}; "
            f"border-radius: 3px; min-height: 20px; }}"
            f"QScrollBar::handle:vertical:hover {{ background-color: {C_MUTED}; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )

        self.chat_container = QWidget()
        self.chat_container.setStyleSheet(f"background-color: {C_BG};")
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(4, 8, 4, 8)
        self.chat_layout.setSpacing(4)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Mensaje de bienvenida
        welcome = QLabel(
            "💬 Selecciona una estrategia y pregunta lo que necesites. "
            "Puedo analizar el codigo, sugerir mejoras o ayudarte a corregir errores."
        )
        welcome.setWordWrap(True)
        welcome.setStyleSheet(
            f"color: {C_MUTED}; font-size: 11px; font-style: italic; "
            f"padding: 12px; background: transparent;"
        )
        self.chat_layout.addWidget(welcome)

        self.chat_layout.addStretch()

        self.scroll_area.setWidget(self.chat_container)
        layout.addWidget(self.scroll_area, stretch=1)

        # --- Status indicator ---
        self.status_label = QLabel("")
        self.status_label.setFixedHeight(20)
        self.status_label.setStyleSheet(
            f"color: {C_ORANGE}; font-size: 10px; padding: 0 12px; "
            f"background-color: {C_SIDEBAR};"
        )
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        # --- Input area ---
        input_container = QWidget()
        input_container.setStyleSheet(
            f"background-color: {C_SIDEBAR}; "
            f"border-top: 1px solid {C_BORDER};"
        )
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(8, 8, 8, 8)
        input_layout.setSpacing(6)

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Pregunta sobre la estrategia...")
        self.text_input.setFixedHeight(34)
        self.text_input.setStyleSheet(
            f"QLineEdit {{ "
            f"background-color: {C_BG}; color: {C_TEXT}; "
            f"border: 1px solid {C_BORDER}; border-radius: 8px; "
            f"padding: 4px 12px; font-size: 12px; "
            f"}}"
            f"QLineEdit:focus {{ border-color: {C_ORANGE}; }}"
            f"QLineEdit::placeholder {{ color: {C_SUBTLE}; }}"
        )
        self.text_input.returnPressed.connect(self._send_message)
        input_layout.addWidget(self.text_input)

        send_btn = QPushButton("➤")
        send_btn.setFixedSize(34, 34)
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.setToolTip("Enviar mensaje")
        send_btn.setStyleSheet(
            f"QPushButton {{ "
            f"background-color: {C_ORANGE}; color: #ffffff; "
            f"border: none; border-radius: 8px; "
            f"font-size: 14px; font-weight: 700; "
            f"}}"
            f"QPushButton:hover {{ background-color: #e8772e; }}"
            f"QPushButton:pressed {{ background-color: #d06820; }}"
            f"QPushButton:disabled {{ background-color: {C_SURFACE}; color: {C_SUBTLE}; }}"
        )
        send_btn.clicked.connect(self._send_message)
        self.send_btn = send_btn


        input_layout.addWidget(send_btn)

        layout.addWidget(input_container)

    # ── API publica ──

    def set_strategy_context(self, name: str, code: str):
        """Actualiza el contexto de la estrategia actual para el chat."""
        self._strategy_name = name
        self._strategy_code = code
        # Resetear conversacion con nuevo contexto
        context_msg = (
            f"Estoy analizando la estrategia '{name}'. "
            f"Aqui esta el codigo:\n\n```python\n{code}\n```\n\n"
            f"Analiza esta estrategia y preparate para responder preguntas sobre ella."
        )
        self._messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context_msg},
        ]

    # ── Slots internos ──

    def _send_message(self):
        """Envia un mensaje del usuario a Groq."""
        text = self.text_input.text().strip()
        if not text:
            return

        self.text_input.clear()
        self._add_message_bubble(text, is_user=True)

        # Añadir al historial
        self._messages.append({"role": "user", "content": text})

        # Mostrar indicador de carga
        self.status_label.setText("⏳ Groq esta pensando...")
        self.status_label.setVisible(True)
        self.send_btn.setEnabled(False)
        self.text_input.setEnabled(False)

        # Lanzar worker
        self._worker = GroqWorker(list(self._messages))
        self._worker.response_ready.connect(self._on_response)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    def _on_response(self, text: str):
        """Recibe la respuesta de Groq."""
        self._messages.append({"role": "assistant", "content": text})
        self._add_message_bubble(text, is_user=False)
        self.status_label.setVisible(False)
        self.send_btn.setEnabled(True)
        self.text_input.setEnabled(True)
        self.text_input.setFocus()

    def _on_error(self, error: str):
        """Maneja errores de la API."""
        self._add_message_bubble(f"❌ Error: {error}", is_user=False)
        self.status_label.setVisible(False)
        self.send_btn.setEnabled(True)
        self.text_input.setEnabled(True)
        self.text_input.setFocus()

    def _add_message_bubble(self, text: str, is_user: bool):
        """Agrega una burbuja de mensaje al chat."""
        # Remover el stretch del final
        stretch_item = self.chat_layout.takeAt(self.chat_layout.count() - 1)

        msg = ChatMessage(text, is_user)
        self.chat_layout.addWidget(msg)

        # Re-agregar stretch
        self.chat_layout.addStretch()

        # Scroll al fondo
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        """Desplaza el scroll al final."""
        sb = self.scroll_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_chat(self):
        """Limpia la conversacion."""
        # Limpiar widgets del chat
        while self.chat_layout.count() > 0:
            item = self.chat_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        # Reiniciar mensajes
        self._messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        if self._strategy_code:
            context_msg = (
                f"Estoy analizando la estrategia '{self._strategy_name}'. "
                f"Aqui esta el codigo:\n\n```python\n{self._strategy_code}\n```"
            )
            self._messages.append({"role": "user", "content": context_msg})

        # Re-agregar mensaje de bienvenida
        welcome = QLabel(
            "💬 Chat reiniciado. Pregunta lo que necesites sobre la estrategia."
        )
        welcome.setWordWrap(True)
        welcome.setStyleSheet(
            f"color: {C_MUTED}; font-size: 11px; font-style: italic; "
            f"padding: 12px; background: transparent;"
        )
        self.chat_layout.addWidget(welcome)
        self.chat_layout.addStretch()

