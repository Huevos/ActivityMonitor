# Activity Monitor: when there has been no key press for the chosen time, close every open screen and
# return to the InfoBar (the current service) or to the movie / media player if one is playing.
from sys import maxsize
from traceback import print_exc

from enigma import eActionMap, eTimer

import Screens.Standby
from Components.config import ConfigSubsection, ConfigYesNo, ConfigSelection, ConfigText, config
from Components.Task import job_manager
from Plugins.Plugin import PluginDescriptor
from Screens.Setup import Setup

config.plugins.activitymonitor = ConfigSubsection()
config.plugins.activitymonitor.enabled = ConfigYesNo(default=False)
config.plugins.activitymonitor.timeout = ConfigSelection(default="5", choices=[(str(m), ngettext("%d minute", "%d minutes", m) % m) for m in (1, 2, 3, 5, 10, 15, 20, 30, 45, 60)])
config.plugins.activitymonitor.blacklist = ConfigText(default="", fixed_size=False)  # class names separated by commas

# The screens to return to. The movie player sits above the InfoBar in the dialog stack, so it is found first.
BASES = ("InfoBar", "MoviePlayer", "DVDPlayer", "MediaPlayer")
RETRY = 5000  # ms, when the box is busy at the timeout
BLACKLIST = ["BackupManager", "Console", "ImageManager", "JobView", "SoftwareUpdate", "UpdatePlugin"]


def isBase(dialog):
	return any(c.__name__ in BASES for c in type(dialog).__mro__)


def isBlacklisted(dialog):
	names = [n.strip() for n in config.plugins.activitymonitor.blacklist.value.split(",") if n.strip()] + BLACKLIST
	return any(c.__name__ in names for c in type(dialog).__mro__) if names else False


class ActivityMonitor:
	def __init__(self, session):
		self.session = session
		self.bound = False
		self.timer = eTimer()
		self.timer.callback.append(self.timeout)
		config.plugins.activitymonitor.enabled.addNotifier(self.configChanged, initial_call=False)
		config.plugins.activitymonitor.timeout.addNotifier(self.configChanged, initial_call=False)
		self.configChanged()

	def configChanged(self, element=None):
		try:
			if config.plugins.activitymonitor.enabled.value:
				if not self.bound:
					eActionMap.getInstance().bindAction("", -maxsize - 1, self.keyEvent)
					self.bound = True
				self.timer.start(self.interval(), True)
			else:
				self.timer.stop()
				if self.bound:
					eActionMap.getInstance().unbindAction("", self.keyEvent)
					self.bound = False
		except Exception:
			print_exc()

	def interval(self):
		try:
			return int(config.plugins.activitymonitor.timeout.value) * 60000
		except ValueError:
			return 300000

	def keyEvent(self, key, flag):
		try:
			self.timer.start(self.interval(), True)
		except Exception:
			print_exc()
		return 0  # never consume the key

	def timeout(self):
		try:
			session = self.session
			if Screens.Standby.inStandby or Screens.Standby.inTryQuitMainloop or session.current_dialog is None:
				return  # the next key press restarts the timer
			if not session.in_exec or session.delay_timer.isActive() or job_manager.getPendingJobs():
				self.timer.start(RETRY, True)  # a screen is changing or a task (update, flash...) is running
				return
			stack = [session.current_dialog] + [d for d, shown in session.dialog_stack]
			if any(type(d).__name__ in ("TryQuitMainloop", "Standby") for d in stack) or not any(isBase(d) for d in stack):
				return
			while session.current_dialog is not None and not isBase(session.current_dialog):
				if isBlacklisted(session.current_dialog):
					print("[ActivityMonitor] stopped at %s" % type(session.current_dialog).__name__)
					break
				print("[ActivityMonitor] closing %s" % type(session.current_dialog).__name__)
				session.current_dialog.returnValue = None  # no return value or callback, as in Session.reloadSkin
				session.current_dialog.callback = None
				session.execEnd()
				session.processDelay()
		except Exception:
			print_exc()


class ActivityMonitorSetup(Setup):
	def __init__(self, session):
		Setup.__init__(self, session)
		self.setTitle(_("Activity Monitor"))

	def createSetup(self, appendItems=None, prependItems=None):
		if not self.list:
			cfg = config.plugins.activitymonitor
			self.list = [
				(_("Enable activity monitor"), cfg.enabled, _("Close all screens and return to the playing service or movie when there is no key press.")),
				(_("Time without a key press"), cfg.timeout, _("How long to wait before closing the screens.")),
				(_("Screens not to close"), cfg.blacklist, _("Screen class names separated by commas. Closing stops at the first of these. The names are in the log as '[ActivityMonitor] closing ...'.")),
			]
			self["config"].list = self.list


monitor = None


def sessionStart(reason, session=None, **kwargs):
	global monitor
	if reason == 0 and session and monitor is None:
		monitor = ActivityMonitor(session)


def main(session, **kwargs):
	session.open(ActivityMonitorSetup)


def Plugins(**kwargs):
	return [
		PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=sessionStart),
		PluginDescriptor(name=_("Activity Monitor"), description=_("Return to the playing service after a period without key presses"), where=PluginDescriptor.WHERE_PLUGINMENU, needsRestart=False, fnc=main),
	]
