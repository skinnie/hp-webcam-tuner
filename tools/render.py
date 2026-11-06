"""Render an HTML file off-screen with WebKitGTK and save a PNG. JS on/off via --js."""
import sys, gi
gi.require_version('Gtk','3.0'); gi.require_version('WebKit2','4.1')
from gi.repository import Gtk, WebKit2, GLib
src, out, w, h = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
js = '--js' in sys.argv
dark = '--dark' in sys.argv
win = Gtk.OffscreenWindow(); wv = WebKit2.WebView()
s = wv.get_settings(); s.set_enable_javascript(js); s.set_enable_write_console_messages_to_stdout(True)
wv.set_size_request(w, h); win.add(wv); win.show_all()
if dark:
    Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', True)
def done(view, res, _):
    surf = view.get_snapshot_finish(res); surf.write_to_png(out); Gtk.main_quit()
def loaded(view, ev):
    if ev == WebKit2.LoadEvent.FINISHED:
        GLib.timeout_add(int(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5].isdigit() else 1500,
            lambda: (view.get_snapshot(WebKit2.SnapshotRegion.FULL_DOCUMENT, WebKit2.SnapshotOptions.NONE, None, done, None), False)[1])
wv.connect('load-changed', loaded)
wv.load_uri(src if '://' in src else GLib.filename_to_uri(src))
GLib.timeout_add(30000, Gtk.main_quit)
Gtk.main()
