# Copyright (c) 2011, Dirk Thomas, Dorian Scholz, TU Darmstadt
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#   * Redistributions of source code must retain the above copyright
#     notice, this list of conditions and the following disclaimer.
#   * Redistributions in binary form must reproduce the above
#     copyright notice, this list of conditions and the following
#     disclaimer in the documentation and/or other materials provided
#     with the distribution.
#   * Neither the name of the TU Darmstadt nor the names of its
#     contributors may be used to endorse or promote products derived
#     from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import traceback

import QtBindingHelper #@UnusedImport
from QtCore import qCritical, QEvent, QObject, Qt, qWarning, Signal, Slot
from QtGui import QDockWidget

from DockWidgetTitleBar import DockWidgetTitleBar
from PluginContext import PluginContext

class PluginHandler(QObject):

    close_signal = Signal(str)
    reload_signal = Signal(str)
    help_signal = Signal(str)

    def __init__(self, main_window, instance_id, plugin_id, serial_number, application_context):
        super(PluginHandler, self).__init__()
        self.setObjectName('PluginHandler')

        self._main_window = main_window
        self._instance_id = instance_id
        self._plugin_id = plugin_id
        self._serial_number = serial_number
        self._application_context = application_context

        self._plugin_provider = None
        self._context = None
        self._plugin = None

        # mapping from added widgets to dock widgets
        self._widgets = {}

    def __del__(self):
        print 'PluginHandler.__del__()'


    def load(self, plugin_provider):
        self._plugin_provider = plugin_provider
        self._context = PluginContext(self)
        self._plugin = self._load()
        if self._plugin is None:
            return None
        # emit close_signal when deferred delete event for plugin is received
        self._plugin.installEventFilter(self)
        return self

    def _load(self):
        return self._plugin_provider.load(self._plugin_id, self._context)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.DeferredDelete:
            # TOOD: check if ignore() is necessary
            event.ignore()
            self.close_signal.emit(self._instance_id)
            return True
        return QObject.eventFilter(self, watched, event)

    def shutdown_plugin(self):
        self._plugin.removeEventFilter(self)
        self._shutdown_plugin()
        for widget in self._widgets.keys():
            self.remove_widget(widget)
            # only delete widgets which are not at the same time the plugin
            if widget != self._plugin:
                del widget
        self._plugin.deleteLater()

    def _shutdown_plugin(self):
        if hasattr(self._plugin, 'shutdown_plugin'):
            self._plugin.shutdown_plugin()

    def unload(self):
        self._plugin_provider.unload(self._plugin)


    def save_settings(self, global_settings, perspective_settings):
        self._save_settings(global_settings, perspective_settings)
        # call after plugin method since the plugin may spawn additional dock widgets depending on current settings
        self._call_method_on_all_dock_widgets('save_settings', perspective_settings)

    def _save_settings(self, global_settings, perspective_settings):
        if hasattr(self._plugin, 'save_settings'):
            global_settings_plugin = global_settings.get_settings('plugin')
            perspective_settings_plugin = perspective_settings.get_settings('plugin')
            self._plugin.save_settings(global_settings_plugin, perspective_settings_plugin)

    def restore_settings(self, global_settings, perspective_settings):
        self._restore_settings(global_settings, perspective_settings)
        # call after plugin method since the plugin may spawn additional dock widgets depending on current settings
        self._call_method_on_all_dock_widgets('restore_settings', perspective_settings)

    def _restore_settings(self, global_settings, perspective_settings):
        if hasattr(self._plugin, 'restore_settings'):
            global_settings_plugin = global_settings.get_settings('plugin')
            perspective_settings_plugin = perspective_settings.get_settings('plugin')
            self._plugin.restore_settings(global_settings_plugin, perspective_settings_plugin)

    def _call_method_on_all_dock_widgets(self, method_name, perspective_settings):
        for dock_widget in self._widgets.values():
            name = 'title_bar__' + dock_widget.objectName().replace('/', '_')
            settings = perspective_settings.get_settings(name)
            title_bar = dock_widget.titleBarWidget()
            if hasattr(title_bar, method_name):
                method = getattr(title_bar, method_name)
                try:
                    method(settings)
                except Exception:
                    qCritical('PluginHandler._call_method_on_all_dock_widgets(%s) call on DockWidgetTitleBar failed:\n%s' % (method_name, traceback.format_exc()))


    def serial_number(self):
        return self._serial_number

    # pointer to QWidget must be used for PySide to work (at least with 1.0.1)
    @Slot('QWidget*')
    def add_widget(self, widget):
        dock_widget = self._create_dock_widget()
        dock_widget.setWidget(widget)
        dock_widget.setObjectName(self._instance_id + '__' + widget.objectName())
        self._add_dock_widget(dock_widget, widget)
        self.update_widget_title(widget)

    def _create_dock_widget(self):
        dock_widget = QDockWidget()
        if self._application_context.options.standalone_plugin is not None:
            # standalone plugins are not closable
            features = dock_widget.features()
            dock_widget.setFeatures(features ^ QDockWidget.DockWidgetClosable)
        self._update_title_bar(dock_widget)
        return dock_widget

    def _update_title_bar(self, dock_widget):
        title_bar = dock_widget.titleBarWidget()
        if title_bar is None:
            title_bar = DockWidgetTitleBar(dock_widget)
            dock_widget.setTitleBarWidget(title_bar)

            # connect extra buttons
            title_bar.connect_close_button(self._close_dock_widget)
            title_bar.connect_button('help', self._emit_help_signal)
            title_bar.connect_button('reload', self._emit_reload_signal)

            # connect settings button to plugin instance
            if hasattr(self._plugin, 'settings_request'):
                title_bar.connect_button('settings', getattr(self._plugin, 'settings_request'))
                title_bar.show_button('settings')
            else:
                title_bar.hide_button('settings')

    def _emit_help_signal(self):
        self.help_signal.emit(self._instance_id)

    def _emit_reload_signal(self):
        self.reload_signal.emit(self._instance_id)

    def _add_dock_widget(self, dock_widget, widget):
        self._add_dock_widget_to_main_window(dock_widget)
        self._widgets[widget] = dock_widget

    def _add_dock_widget_to_main_window(self, dock_widget):
        if self._main_window is not None:
            # find and remove possible remaining dock_widget with this object name
            old_dock_widget = self._main_window.findChild(QDockWidget, dock_widget.objectName())
            if old_dock_widget is not None:
                qWarning('PluginHandler._add_dock_widget_to_main_window() duplicate object name "%s", removing old dock widget!' % dock_widget.objectName())
                self._main_window.removeDockWidget(old_dock_widget)
            self._main_window.addDockWidget(Qt.BottomDockWidgetArea, dock_widget)

    # pointer to QWidget must be used for PySide to work (at least with 1.0.1)
    @Slot('QWidget*')
    def update_widget_title(self, widget):
        self._update_widget_title(widget, widget.windowTitle())

    def _update_widget_title(self, widget, title):
        dock_widget = self._widgets[widget]
        dock_widget.setWindowTitle(title)

    # pointer to QWidget must be used for PySide to work (at least with 1.0.1)
    @Slot('QWidget*')
    def remove_widget(self, widget):
        dock_widget = self._widgets[widget]
        self._remove_dock_widget_from_main_window(dock_widget)
        # do not delete the widget, only the dock widget
        widget.setParent(None)
        del self._widgets[widget]
        # close plugin when last widget is removed
        if len(self._widgets) == 0:
            self.close_plugin()

    def _remove_dock_widget_from_main_window(self, dock_widget):
        if self._main_window is not None:
            self._main_window.removeDockWidget(dock_widget)
            dock_widget.setParent(None)
            dock_widget.deleteLater()

    def _close_dock_widget(self, dock_widget):
        widget = [key for key, value in self._widgets.iteritems() if value == dock_widget][0]
        self.remove_widget(widget)


    @Slot()
    def close_plugin(self):
        # only non-standalone plugins are closable
        if self._application_context.options.standalone_plugin is None:
            self.close_signal.emit(self._instance_id)