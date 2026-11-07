from widgets.analog import AnalogClockWidget
from widgets.calendar_month import CalendarWidget
from widgets.clock import ClockWidget
from widgets.countdown import CountdownWidget
from widgets.currency import CurrencyWidget
from widgets.focus import FocusWidget
from widgets.gpu import GpuWidget
from widgets.moon import MoonWidget
from widgets.ping import PingWidget
from widgets.quick import QuickWidget
from widgets.lyrics import LyricsWidget
from widgets.meteoclock import MeteoClockWidget
from widgets.network import NetworkWidget
from widgets.notes import NotesWidget
from widgets.photo import PhotoWidget
from widgets.player import PlayerWidget
from widgets.sun import SunWidget
from widgets.system import SystemWidget
from widgets.timer import TimerWidget
from widgets.water import WaterWidget
from widgets.todo import TodoWidget
from widgets.weather import WeatherWidget
from widgets.worldclock import WorldClockWidget

# каталог: новый виджет — добавить сюда (и значок в icons.TILES)
ALL = [PlayerWidget, LyricsWidget, MeteoClockWidget, AnalogClockWidget, ClockWidget, WorldClockWidget,
       WeatherWidget, SunWidget, CalendarWidget, CountdownWidget, TimerWidget, WaterWidget,
       TodoWidget, NotesWidget, SystemWidget, NetworkWidget, GpuWidget, PingWidget,
       CurrencyWidget, PhotoWidget, FocusWidget, MoonWidget, QuickWidget]
