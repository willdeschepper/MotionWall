"""Ordinary application window for workspace/focus regression tests."""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk

app = Gtk.Application(application_id="io.github.willdeschepper.MotionWall.WorkspaceTest",
                      flags=Gio.ApplicationFlags.NON_UNIQUE)


def activate(application):
    window = Gtk.ApplicationWindow(application=application, title="MotionWall Workspace Test",
                                  default_width=420, default_height=240)
    window.set_child(Gtk.Label(label="Workspace regression fixture"))
    window.present()


app.connect("activate", activate)
app.run([])
