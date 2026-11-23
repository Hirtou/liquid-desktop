from widgets.air import AirWidget
from widgets.analog import AnalogClockWidget
from widgets.breathe import BreatheWidget
from widgets.calc import CalcWidget
from widgets.claude import ClaudeWidget
from widgets.clipboard import ClipboardWidget
from widgets.dice import DiceWidget
from widgets.habits import HabitsWidget
from widgets.processes import ProcessesWidget
from widgets.progress import ProgressWidget
from widgets.stopwatch import StopwatchWidget
from widgets.volume import VolumeWidget
from widgets.calendar_month import CalendarWidget
from widgets.clock import ClockWidget
from widgets.countdown import CountdownWidget
from widgets.currency import CurrencyWidget
from widgets.focus import FocusWidget
from widgets.gpu import GpuWidget
from widgets.moon import MoonWidget
from widgets.ping import PingWidget
from widgets.quick import QuickWidget
from widgets.tools import ToolsWidget
from widgets.visualizer import VisualizerWidget
from widgets.lyrics import LyricsWidget
from widgets.meteoclock import MeteoClockWidget
from widgets.network import NetworkWidget
from widgets.notes import NotesWidget
from widgets.photo import PhotoWidget
from widgets.folder import FolderWidget
from widgets.gif import GifWidget
from widgets.player import PlayerWidget
from widgets.sun import SunWidget
from widgets.system import SystemWidget
from widgets.timer import TimerWidget
from widgets.water import WaterWidget
from widgets.todo import TodoWidget
from widgets.weather import WeatherWidget
from widgets.worldclock import WorldClockWidget

# каталог: новый виджет — добавить сюда (и значок в icons.TILES)
ALL = [PlayerWidget, LyricsWidget, VisualizerWidget, MeteoClockWidget, AnalogClockWidget, ClockWidget, WorldClockWidget,
       WeatherWidget, AirWidget, SunWidget, CalendarWidget, ProgressWidget, CountdownWidget, TimerWidget, StopwatchWidget, WaterWidget, HabitsWidget,
       TodoWidget, NotesWidget, ClipboardWidget, CalcWidget, ClaudeWidget, SystemWidget, ProcessesWidget, NetworkWidget, GpuWidget, PingWidget, VolumeWidget,
       CurrencyWidget, PhotoWidget, GifWidget, FolderWidget, FocusWidget, BreatheWidget, DiceWidget, MoonWidget, QuickWidget, ToolsWidget]

# виджеты, которых можно поставить несколько (свои фото, свои гифки): копия — тот же класс со своим ключом
# («photo_2», «gif_3») и своим разделом настроек; список копий — config["app"]["copies"]
COPYABLE = {PhotoWidget.key: PhotoWidget, GifWidget.key: GifWidget, FolderWidget.key: FolderWidget}
_copies = {}


def copy_class(base_key, n):
    key = f"{base_key}_{n}"
    if key not in _copies:
        base = COPYABLE[base_key]
        _copies[key] = type(f"{base.__name__}{n}", (base,), {"key": key, "title": f"{base.title} {n}", "copy_of": base_key})
    return _copies[key]
