"""Synthetic MSS frames for unit tests; real capture belongs to desktop acceptance."""
from unittest.mock import patch
from mss.screenshot import ScreenShot

class FakeMss:
    monitors=[dict(left=0,top=0,width=120,height=80)]*2
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def grab(self,box):
        width,height=int(box['width']),int(box['height'])
        return ScreenShot.from_size(bytes([29,71,131,255])*(width*height),width,height)

def synthetic_screen(case):
    for item in (patch('mss.mss',FakeMss),
                 patch('computer_mcp.capture_daemon._active_window_title',return_value='Synthetic fixture')):
        item.start();case.addCleanup(item.stop)
