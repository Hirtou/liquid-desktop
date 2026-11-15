"""Виджет внутри рабочего стола: окно Qt становится дочерним окном слоя с ярлыками (SHELLDLL_DefView).
Тогда это часть рабочего стола, а не отдельное окно: Win+D, клик по пустому столу, окна других программ
его не поднимают и не прячут — он всегда там же, где ярлыки.

Идея и основа — из модификации Liquid Desktop, которую прислал пользователь (лицензия MIT, как у проекта).
Включается настройкой app.desktop_child (пока — для проверки тестерами).

Тонкости:
- окно-ребёнок не может спрятаться от снимков экрана, поэтому живого стекла у него нет — стекло из обоев;
- у ребёнка чужого окна нет своей «активности» Qt: чтобы печатать в «Заметках» и «Делах», по клику
  подключаемся к вводу окна, которое сейчас впереди, и ставим фокус сами (AttachThreadInput + SetFocus);
- слой ярлыков (SysListView32) лежит на весь стол и забирает клики даже на пустом месте — виджеты с вводом
  держим перед ним."""
import ctypes
import warnings
from ctypes import wintypes as wt

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QApplication, QWidget

import glass


class DesktopHost(QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.widget = widget
        self.attached = False
        self.parent = 0          # окно-хозяин (слой ярлыков)
        self.peer = 0            # окно самого виджета
        self.foreign = None      # хозяин, обёрнутый для Qt (QWindow.fromWinId)
        self.position = QPoint(QWidget.pos(widget))  # где виджет на экране (логические точки)
        self.error = None
        self.icon_view = False
        self.input_thread = 0
        self._focusing = False
        widget.destroyed.connect(self.release_input)
        QApplication.instance().installEventFilter(self)

    # ---------- клавиатура ----------

    def set_active(self, active):
        # У ребёнка чужого окна нет цепочки активации Qt: одного фокуса Windows мало — поля ввода
        # остаются неактивными. Делаем окно виджета «активным» для Qt, не поднимая сам рабочий стол.
        if active or QApplication.activeWindow() is self.widget:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                QApplication.setActiveWindow(self.widget if active else None)

    def release_input(self, *_):
        thread = self.input_thread
        self.input_thread = 0
        if thread:
            glass.user32.AttachThreadInput(ctypes.windll.kernel32.GetCurrentThreadId(), thread, False)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.MouseButtonPress and getattr(self.widget, "keyboard_input", False)
                and self.valid() and isinstance(watched, QWidget) and watched.window() is self.widget):
            u = glass.user32
            self._focusing = True
            foreground_thread = u.GetWindowThreadProcessId(u.GetForegroundWindow(), None)
            current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            if self.input_thread and self.input_thread != foreground_thread:
                self.release_input()
            joined = (not self.input_thread and foreground_thread and foreground_thread != current_thread
                      and u.AttachThreadInput(current_thread, foreground_thread, True))
            if joined:
                self.input_thread = foreground_thread
            u.SetFocus(wt.HWND(self.peer))
            self._focusing = False
            self.set_active(True)
        return False

    def native_focus(self, message):
        if self.attached and message in (0x0007, 0x0008):  # WM_SETFOCUS / WM_KILLFOCUS
            if message == 0x0008 and not self._focusing:
                self.release_input()
            self.set_active(message == 0x0007)

    # ---------- место ----------

    def valid(self):
        u = glass.user32
        return bool(self.attached and self.peer and u.IsWindow(self.peer) and self.parent
                    and u.IsWindow(self.parent) and u.GetParent(self.peer) == self.parent)

    def global_pos(self):
        # координаты экрана храним сами: у ребёнка Qt отдаёт их относительно хозяина
        return QPoint(self.position)

    def move_global(self, position):
        self.position = QPoint(position)
        if self.valid():
            QWidget.move(self.widget, self.foreign.mapFromGlobal(position))
        else:
            QWidget.move(self.widget, position)

    def _release_wrapper(self):
        if self.foreign is not None:
            self.foreign.deleteLater()
            self.foreign = None

    def attach(self, under_icons=False):
        """Вложить окно виджета в слой ярлыков. -> получилось ли (окно на месте и в нужном порядке)."""
        u = glass.user32
        icons = glass.icons_layer()
        listing = glass.icon_list(icons)
        if not listing and self.icon_view and self.valid() and icons == self.parent:
            self.error = "Explorer icon list is temporarily unavailable"
            return False
        parent = icons if listing else (u.GetParent(icons) if icons else 0)
        sibling = listing or icons
        if not parent:
            self.error = "Explorer icon host is unavailable"
            return False
        position = self.global_pos() if self.attached else QPoint(QWidget.pos(self.widget))
        focus_flag = None
        if not self.valid() or parent != self.parent:
            self.widget.setAttribute(Qt.WA_ShowWithoutActivating, True)
            replacement = QWindow.fromWinId(int(parent))
            if replacement is None:
                self.error = "Qt could not wrap the desktop host"
                return False
            lost_peer = bool(self.attached and self.peer and not u.IsWindow(self.peer))
            self.attached = True
            if lost_peer:  # Проводник перезапускали — старое окно погибло вместе с хозяином
                self.widget.destroy(True, False)
            previous = self.foreign
            self.foreign = replacement
            self.parent = int(parent)
            self.icon_view = bool(listing)
            self.peer = int(self.widget.winId())
            window = self.widget.windowHandle()
            focus_flag = bool(window.flags() & Qt.WindowDoesNotAcceptFocus)
            window.setFlag(Qt.WindowDoesNotAcceptFocus, True)
            # «не попадать в снимки» у ребёнка не ставится, а унаследованное от отдельного окна снять надо сейчас
            if not u.GetParent(self.peer):
                glass.include_in_capture(self.peer)
            window.setParent(self.foreign)
            if u.GetParent(self.peer) != parent:
                self.attached = False
                self.error = "Qt desktop reparenting failed"
                window.setParent(None)
                window.setFlag(Qt.WindowDoesNotAcceptFocus, focus_flag)
                QWidget.move(self.widget, position)
                self.parent = self.peer = 0
                self._release_wrapper()
                if previous is not None:
                    previous.deleteLater()
                return False
            if previous is not None:
                previous.deleteLater()
            self.move_global(position)
        self.widget.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.widget._skip_fade = True
        self.widget.show()
        if focus_flag is not None:
            self.widget.windowHandle().setFlag(Qt.WindowDoesNotAcceptFocus, focus_flag)
        # слой ярлыков забирает клики по всему столу: виджеты с вводом — перед ним, остальные — по настройке
        after = int(sibling) if under_icons and not getattr(self.widget, "keyboard_input", False) else 0
        ok = u.SetWindowPos(self.peer, after, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040 | 0x0400)
        self.error = None if ok else "Desktop sibling placement failed"
        return bool(ok)

    def detach(self):
        """Снова отдельное окно (на время «Двигать виджеты» или если вкладывать нельзя)."""
        self.release_input()
        if not self.attached:
            return
        position = self.global_pos()
        valid_peer = bool(self.peer and glass.user32.IsWindow(self.peer))
        self.attached = False
        if valid_peer and self.widget.windowHandle() is not None:
            self.widget.windowHandle().setParent(None)
            QWidget.move(self.widget, position)
        elif self.widget.windowHandle() is not None:
            self.widget.destroy(True, False)
            QWidget.move(self.widget, position)
        self.parent = self.peer = 0
        self._release_wrapper()
