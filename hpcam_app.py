#!/usr/bin/env python3
"""HP Webcam tuner: native window around the web UI in ui/ (served by hpcam_web.py).

  hpcam_app.py            open the app window (GTK + WebKitGTK)
  hpcam_app.py --browser  open the UI in the default web browser instead
"""
import os, sys, webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hpcam_web  # noqa: E402


def main():
    ctl, srv, url = hpcam_web.serve()
    if '--browser' in sys.argv:
        print('HP Webcam UI at', url, '(Ctrl+C to stop)', flush=True)
        webbrowser.open(url)
        try:
            import time
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            ctl.shutdown()
        return

    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('WebKit2', '4.1')
    from gi.repository import Gtk, WebKit2

    win = Gtk.Window(title='HP Webcam', default_width=1180, default_height=760)
    win.set_icon_name('camera-web')
    view = WebKit2.WebView()
    settings = view.get_settings()
    settings.set_enable_developer_extras('--debug' in sys.argv)
    # keep the app on its own local page; anything else opens in the browser
    def on_decide(v, decision, kind):
        if kind == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_navigation_action().get_request().get_uri()
            if not uri.startswith(url):
                webbrowser.open(uri)
                decision.ignore()
                return True
        return False
    view.connect('decide-policy', on_decide)
    view.load_uri(url)
    win.add(view)
    win.connect('destroy', lambda *_: (ctl.shutdown(), Gtk.main_quit()))
    win.show_all()
    Gtk.main()


if __name__ == '__main__':
    main()
