from dataclasses import asdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,threading
from urllib.parse import urlparse
from pathlib import Path
class RainwaterTankWebServer:
 def __init__(self,latest_level,host="0.0.0.0",port=8765):self.latest,self.host,self.port,self.server=latest_level,host,port,None
 def start(self):
  if self.server:return
  dashboard_html = (Path(__file__).resolve().parent.parent / "webs" / "rainwater_tank.html").read_text(encoding="utf-8")
  latest=self.latest
  class H(BaseHTTPRequestHandler):
   def send(self,k,b):
    self.send_response(k);self.send_header("Content-Type","text/html; charset=utf-8" if isinstance(b,str) else "application/json");self.send_header("Access-Control-Allow-Origin","*");self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(b.encode() if isinstance(b,str) else b)
   def do_GET(self):
    path=urlparse(self.path).path
    if path in ("/","/index.html"):return self.send(200,dashboard_html)
    if path!="/api/rainwater-tank/current-level":return self.send(404,b'{"error":"not_found"}')
    level=latest();return self.send(200,json.dumps(asdict(level)).encode() if level else b'{"error":"measurement_unavailable"}')
   def log_message(self,*args):pass
  self.server=ThreadingHTTPServer((self.host,self.port),H);threading.Thread(target=self.server.serve_forever,daemon=True).start()
 def close(self):
  if self.server:self.server.shutdown();self.server.server_close();self.server=None
