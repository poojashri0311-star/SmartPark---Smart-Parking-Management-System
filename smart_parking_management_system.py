"""
SMARTPARK - Smart Parking Management System
Run in IDLE: open this file -> Run -> Run Module (F5)

One-time setup for the UPI QR code (run in Command Prompt, not in IDLE):
    pip install "qrcode[pil]" pillow
"""

import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
from datetime import datetime, timedelta
import math
import os
import html
import json
import re
import secrets
import socket
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, parse_qs, urlparse

# QR payment support
try:
    import qrcode
    from PIL import ImageTk
    QR_AVAILABLE = True
except ImportError:
    qrcode = None
    ImageTk = None
    QR_AVAILABLE = False

try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    BASE_DIR = os.getcwd()

APP_TITLE = "SMARTPARK • Smart Parking Management"
DB_NAME = "smart_parking.db"
RECEIPT_DIR = os.path.join(BASE_DIR, "receipts")

# Easy-to-change demo settings
VEHICLE_RATES = {"Bike": 10, "Car": 30, "Van": 40, "Other": 50}
NO_SHOW_FINE = 50
GRACE_MINUTES = 30

# Put the UPI ID that should RECEIVE parking payments here
# (or type it on the exit/payment screen).
UPI_ID = "yourupi@upi"
UPI_PAYEE_NAME = "SMARTPARK Parking"

# HACKATHON DEMO MODE: True = dummy payment page, no real money, no UPI ID needed.
# Scanning the QR opens a fake payment website; tapping Pay marks it as paid
# and the receipt is generated automatically.
DEMO_MODE = True
# Optional: put ANY website address here (for example "https://example.com") and the QR
# will open that site instead - handy if the phone is not on the same Wi-Fi.
# The "Simulate Payment Success" button then completes the payment on the computer.
DEMO_QR_URL = ""

BG = "#0f172a"
SIDEBAR = "#0b1220"
PANEL = "#172033"
INPUT = "#1e293b"
BLUE = "#2563eb"
GREEN = "#16a34a"
RED = "#dc2626"
AMBER = "#f59e0b"
TEXT = "#f8fafc"
MUTED = "#94a3b8"

DARK_THEME = {
    "BG": "#0f172a", "SIDEBAR": "#0b1220", "PANEL": "#172033",
    "INPUT": "#1e293b", "TEXT": "#f8fafc", "MUTED": "#94a3b8",
    "BLUE": "#2563eb", "GREEN": "#16a34a", "RED": "#dc2626",
    "AMBER": "#f59e0b", "HEADER": "#111827", "BORDER": "#334155",
    "TABLE": "#111827", "TABLE_HEAD": "#1e3a8a", "SUBTLE": "#1e293b",
    "INFO": "#10213f"
}

BRIGHT_THEME = {
    "BG": "#f4f7fb", "SIDEBAR": "#ffffff", "PANEL": "#ffffff",
    "INPUT": "#ffffff", "TEXT": "#172033", "MUTED": "#64748b",
    "BLUE": "#2563eb", "GREEN": "#15803d", "RED": "#dc2626",
    "AMBER": "#d97706", "HEADER": "#ffffff", "BORDER": "#cbd5e1",
    "TABLE": "#ffffff", "TABLE_HEAD": "#dbeafe", "SUBTLE": "#eef2f7",
    "INFO": "#eaf2ff"
}

UPI_PATTERN = r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+$"


# ---------------------------------------------------------------------------
# ONLINE PAYMENT PAGE (opened when the customer scans the QR code)
#
# The app runs a tiny web server on this computer. The QR code contains the
# address of a payment page on that server. The customer's phone (on the same
# Wi-Fi) opens the page, taps "Pay" (which opens their UPI app with the amount
# filled in), then taps "I have paid". The cashier confirms in the desktop app
# and the receipt is then shown on the phone and saved on the computer.
# ---------------------------------------------------------------------------

PAY_PORT = 8765
PAYMENTS = {}                      # token -> payment details (shared with the web server)
PAYMENTS_LOCK = threading.Lock()


def get_lan_ip():
    """Return this computer's Wi-Fi/LAN address (what the phone must connect to)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


RECEIPT_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Parking Receipt __TXN__</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;background:#eef2f7;margin:0;padding:18px;color:#172033}
.card{max-width:460px;margin:0 auto;background:#fff;border-radius:14px;padding:24px;box-shadow:0 4px 18px rgba(0,0,0,.12)}
h1{margin:0;color:#2563eb;font-size:22px;text-align:center}
.sub{text-align:center;color:#64748b;font-size:13px;margin:4px 0 14px}
.paid{display:block;width:max-content;margin:8px auto 14px;border:3px solid #16a34a;color:#16a34a;font-weight:800;padding:4px 18px;border-radius:8px;letter-spacing:3px;transform:rotate(-4deg)}
table{width:100%;border-collapse:collapse;font-size:14px}
td{padding:8px 4px;border-bottom:1px solid #e2e8f0;vertical-align:top}
td:first-child{color:#64748b;width:42%}
td:last-child{font-weight:600;text-align:right;word-break:break-all}
.total td{font-size:18px;border-bottom:none;color:#172033}
.btns{display:flex;gap:10px;margin-top:18px}
.btn{flex:1;text-align:center;background:#2563eb;color:#fff;border:0;border-radius:8px;padding:12px;font-size:15px;font-weight:700;text-decoration:none;cursor:pointer}
.btn.alt{background:#475569}
.foot{text-align:center;color:#64748b;font-size:12px;margin-top:14px}
@media print{body{background:#fff;padding:0}.card{box-shadow:none}.btns{display:none}}
</style></head><body>
<div class="card">
<h1>SMARTPARK</h1><div class="sub">Parking Payment Receipt</div>
<span class="paid">PAID</span>
<table>__ROWS__
<tr class="total"><td>Amount Paid</td><td>&#8377;__FEE__</td></tr></table>
<div class="btns"><button class="btn" onclick="window.print()">Print / Save as PDF</button>__DL__</div>
<div class="foot">Thank you for parking with us!</div>
</div>
<script>if(location.hash==="#print"){setTimeout(function(){window.print()},400)}</script>
</body></html>"""


def build_receipt_html(d, download_url=None):
    """Build a printable HTML receipt from a dictionary of payment details."""
    e = html.escape
    rows = [
        ("Transaction ID", d["txn"]),
        ("Parking ID", d["parking_id"]),
        ("Vehicle No", d["vehicle"]),
        ("Slot", d["slot"]),
        ("Entry", d["entry"]),
        ("Exit", d["exit"]),
        ("Duration", f"{d['minutes']} minutes"),
        ("Payment Method", d["method"]),
    ]
    if d.get("upi"):
        rows.append(("Paid to UPI ID", d["upi"]))
    rows.append(("Paid On", d["paid_at"]))
    body_rows = "".join(
        f"<tr><td>{e(str(k))}</td><td>{e(str(v))}</td></tr>" for k, v in rows
    )
    dl = (
        f'<a class="btn alt" href="{e(download_url)}">Download</a>'
        if download_url else ""
    )
    return (
        RECEIPT_TEMPLATE
        .replace("__TXN__", e(str(d["txn"])))
        .replace("__ROWS__", body_rows)
        .replace("__FEE__", e(str(d["fee"])))
        .replace("__DL__", dl)
    )


PAY_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SMARTPARK Payment</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;background:#0f172a;margin:0;padding:18px;color:#f8fafc}
.card{max-width:460px;margin:0 auto;background:#172033;border-radius:14px;padding:24px}
h1{margin:0;color:#60a5fa;font-size:22px;text-align:center}
.sub{text-align:center;color:#94a3b8;font-size:13px;margin:4px 0 12px}
.amt{text-align:center;font-size:44px;font-weight:800;margin:10px 0 14px}
table{width:100%;border-collapse:collapse;font-size:14px;margin-bottom:16px}
td{padding:7px 4px;border-bottom:1px solid #334155}
td:first-child{color:#94a3b8}
td:last-child{text-align:right;font-weight:600}
.btn{display:block;width:100%;box-sizing:border-box;text-align:center;background:#2563eb;color:#fff;border:0;border-radius:10px;padding:15px;font-size:17px;font-weight:700;text-decoration:none;cursor:pointer;margin-top:12px}
.btn.green{background:#16a34a}
.hint{color:#94a3b8;font-size:12px;margin:8px 2px 0}
.warn{background:#7f1d1d;border-radius:8px;padding:12px;font-size:14px}
#wait{display:none;background:#10213f;border-radius:10px;padding:16px;margin-top:14px;text-align:center;font-size:15px}
</style></head><body>
<div class="card">
<h1>SMARTPARK</h1><div class="sub">__SUB__</div>
<div class="amt">&#8377;__FEE__</div>
<table>
<tr><td>Vehicle</td><td>__VEHICLE__</td></tr>
<tr><td>Slot</td><td>__SLOT__</td></tr>
<tr><td>Entry</td><td>__ENTRY__</td></tr>
<tr><td>Exit</td><td>__EXIT__</td></tr>
<tr><td>Duration</td><td>__DURATION__ min</td></tr>
</table>
<div id="step">
__ACTIONS__
</div>
<div id="wait">__WAIT__</div>
</div>
<script>
var token="__TOKEN__";
function showWait(){document.getElementById("step").style.display="none";document.getElementById("wait").style.display="block";}
function claim(){fetch("/claim/"+token,{method:"POST"}).then(showWait);}
function poll(){
  fetch("/status/"+token).then(function(r){return r.json();}).then(function(s){
    if(s.status==="paid"){location.replace("/receipt/"+token);}
    else if(s.status==="claimed"){showWait();}
  }).catch(function(){});
}
setInterval(poll,2000);poll();
</script>
</body></html>"""


def build_pay_page(token, p):
    e = html.escape
    if DEMO_MODE:
        sub = "Demo Payment Gateway &bull; Hackathon Prototype"
        actions = (
            '<button class="btn" onclick="claim()">Pay &#8377;%.2f</button>'
            '<p class="hint">This is a dummy payment page for the demo. '
            'No real money is charged.</p>' % p["fee"]
        )
        wait = "&#10003; Payment successful!<br>Generating your receipt..."
    else:
        sub = "Parking Payment"
        upi = p.get("upi", "")
        if re.match(UPI_PATTERN, upi or ""):
            link = (
                "upi://pay?pa=" + quote(upi, safe="@._-")
                + "&pn=" + quote(UPI_PAYEE_NAME, safe="")
                + "&am=" + f"{p['fee']:.2f}"
                + "&cu=INR"
                + "&tn=" + quote("SmartPark " + p["slot"], safe="")
            )
            pay_btn = f'<a class="btn" href="{e(link, quote=True)}">Pay &#8377;{p["fee"]:.2f} with UPI</a>'
        else:
            pay_btn = '<div class="warn">The parking operator has not set a UPI ID yet. Please pay at the counter.</div>'
        actions = (
            pay_btn
            + '<button class="btn green" onclick="claim()">I have paid</button>'
            + '<p class="hint">1) Tap the blue button &mdash; your UPI app opens with the amount filled in.<br>'
            + '2) Complete the payment, come back to this page and tap "I have paid".<br>'
            + '3) Your receipt appears here after the cashier confirms.</p>'
        )
        wait = "Waiting for the cashier to confirm your payment...<br>Your receipt will appear here automatically."
    return (
        PAY_TEMPLATE
        .replace("__SUB__", sub)
        .replace("__FEE__", f"{p['fee']:.2f}")
        .replace("__VEHICLE__", e(p["vehicle"]))
        .replace("__SLOT__", e(p["slot"]))
        .replace("__ENTRY__", e(p["entry"]))
        .replace("__EXIT__", e(p["exit"]))
        .replace("__DURATION__", str(p["minutes"]))
        .replace("__ACTIONS__", actions)
        .replace("__WAIT__", wait)
        .replace("__TOKEN__", e(token, quote=True))
    )


# ---------------------------------------------------------------------------
# PRE-BOOKING WEBSITE
# ---------------------------------------------------------------------------
BOOKING_PORT = 8787
BOOKING_DB_PATH = os.path.join(BASE_DIR, DB_NAME)

BOOKING_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SMARTPARK • Pre-Booking</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:linear-gradient(135deg,#0f172a,#172554);color:#f8fafc;padding:22px}.wrap{max-width:900px;margin:auto}.brand{font-size:30px;font-weight:800;color:#60a5fa}.sub{color:#94a3b8;margin:4px 0 22px}.card{background:#172033;border:1px solid #334155;border-radius:18px;padding:22px;margin-bottom:18px;box-shadow:0 10px 30px rgba(0,0,0,.22)}h2{margin:0 0 8px}.hint{color:#94a3b8;font-size:13px;margin:0 0 18px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}label{display:block;font-size:13px;font-weight:700;color:#cbd5e1;margin-bottom:6px}input,select{width:100%;padding:12px;border-radius:10px;border:1px solid #475569;background:#0f172a;color:#f8fafc;font-size:15px}.full{grid-column:1/-1}.btn{border:0;border-radius:10px;padding:13px 18px;background:#2563eb;color:white;font-size:15px;font-weight:800;cursor:pointer;text-decoration:none;display:inline-block}.btn.green{background:#16a34a}.btn.red{background:#dc2626}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.notice{padding:13px;border-radius:10px;background:#10213f;color:#bfdbfe;margin:14px 0}.fine{color:#fbbf24;font-weight:700}.error{background:#7f1d1d;color:#fecaca;padding:14px;border-radius:10px;margin-bottom:14px}.success{background:#14532d;color:#dcfce7;padding:16px;border-radius:10px;margin-bottom:14px}.details{display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:14px}.details div{padding:9px;border-bottom:1px solid #334155}.details b{color:#94a3b8}.small{font-size:12px;color:#94a3b8}@media(max-width:650px){body{padding:12px}.grid,.details{grid-template-columns:1fr}.full{grid-column:auto}}
</style></head><body><div class="wrap"><div class="brand">SMARTPARK</div><div class="sub">Reserve your parking slot before you arrive</div>__BODY__</div></body></html>"""

def _booking_db():
    conn=sqlite3.connect(BOOKING_DB_PATH,timeout=10); conn.row_factory=sqlite3.Row; return conn

def _booking_dt(value): return datetime.strptime(value,"%Y-%m-%dT%H:%M")
def _booking_id(): return "BKG-"+datetime.now().strftime("%Y%m%d%H%M%S")+"-"+secrets.token_hex(2).upper()
def _booking_page(body): return BOOKING_PAGE.replace("__BODY__",body)
def _booking_error(message): return _booking_page('<div class="card"><div class="error">'+html.escape(message)+'</div><a class="btn" href="/">Back to Pre-Booking</a></div>')

def _booking_slots(conn,vehicle_type,start_dt,end_dt):
    rows=conn.execute("SELECT slot_no FROM slots WHERE slot_type=? AND status='Available' ORDER BY slot_no",(vehicle_type,)).fetchall(); result=[]
    for row in rows:
        slot=row["slot_no"]
        overlap=conn.execute("SELECT 1 FROM bookings WHERE slot_no=? AND status IN ('Reserved','Confirmed') AND start_datetime < ? AND end_datetime > ? LIMIT 1",(slot,end_dt.strftime("%Y-%m-%d %H:%M"),start_dt.strftime("%Y-%m-%d %H:%M"))).fetchone()
        active=conn.execute("SELECT 1 FROM parking_sessions WHERE slot_no=? AND status='Active' LIMIT 1",(slot,)).fetchone()
        if not overlap and not active: result.append(slot)
    return result

def _booking_form_body(message=""):
    today=datetime.now().strftime("%Y-%m-%d")
    msg='<div class="error">'+html.escape(message)+'</div>' if message else ''
    body="""__MSG__<div class="card"><h2>📅 Pre-Book a Parking Slot</h2><p class="hint">Choose any future date and time. The slot is reserved immediately in SmartPark.</p><div class="grid">
<div><label>Vehicle Number</label><input id="vehicle" name="vehicle_no" form="bookForm" placeholder="e.g. TN39AB1234" required></div>
<div><label>Vehicle Type</label><select id="vehicle_type" name="vehicle_type" form="bookForm"><option>Car</option><option>Bike</option><option>Van</option><option>Other</option></select></div>
<div><label>Arrival / Start</label><input id="start" type="datetime-local" name="start" form="bookForm" min="__TODAY__T00:00" required></div>
<div><label>Exit / End</label><input id="end" type="datetime-local" name="end" form="bookForm" min="__TODAY__T00:00" required></div>
<div class="full"><label>Parking Slot</label><select id="slot" name="slot_no" form="bookForm" required><option value="">Select date/time first</option></select></div></div>
<div class="notice">⏱ <b>Arrival rule:</b> your 30-minute arrival window starts at the <b>booked start time</b>. If you do not arrive or cancel by that deadline, the booking becomes <b>No-Show</b>, the slot is released, and a <span class="fine">₹50 fine</span> is applied.</div>
<form id="bookForm" method="POST" action="/book"><div class="row"><button class="btn" type="submit">Reserve Slot</button><a class="btn green" href="/">Refresh</a></div></form><p class="small">The vehicle must already be registered in the SmartPark desktop application. A vehicle that is currently parked or already has an active/future booking cannot be pre-booked again.</p></div>
<div class="card"><h2>🔎 Manage a Booking</h2><p class="hint">Check a booking using its Booking ID.</p><form method="GET" action="/booking" class="row"><input name="id" placeholder="BKG-..." required style="flex:1;min-width:220px"><button class="btn" type="submit">View Booking</button></form></div>
<script>
async function loadSlots(){const v=document.getElementById('vehicle_type').value,s=document.getElementById('start').value,e=document.getElementById('end').value,sel=document.getElementById('slot');if(!s||!e){sel.innerHTML='<option value="">Choose start and end time</option>';return;}sel.innerHTML='<option>Checking availability...</option>';try{const r=await fetch('/slots?vehicle_type='+encodeURIComponent(v)+'&start='+encodeURIComponent(s)+'&end='+encodeURIComponent(e));const d=await r.json();sel.innerHTML='';if(d.error){sel.innerHTML='<option value="">'+d.error+'</option>';return;}if(!d.slots.length){sel.innerHTML='<option value="">No slots available for this time</option>';return;}d.slots.forEach(x=>{const o=document.createElement('option');o.value=x;o.textContent=x+' • Available';sel.appendChild(o);});}catch(x){sel.innerHTML='<option value="">Could not check availability</option>';}}
['vehicle_type','start','end'].forEach(id=>document.getElementById(id).addEventListener('change',loadSlots));
</script>"""
    return body.replace("__MSG__",msg).replace("__TODAY__",today)


class BookingServer(ThreadingHTTPServer):
    allow_reuse_address=True; daemon_threads=True

class BookingHandler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def _send(self,code,body,ctype="text/html; charset=utf-8"):
        data=body.encode("utf-8") if isinstance(body,str) else body; self.send_response(code); self.send_header("Content-Type",ctype); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        parsed=urlparse(self.path); path=parsed.path
        if path=="/": self._send(200,_booking_page(_booking_form_body())); return
        if path=="/slots":
            q=parse_qs(parsed.query)
            try:
                vt=q.get("vehicle_type",[""])[0]; st=_booking_dt(q.get("start",[""])[0]); et=_booking_dt(q.get("end",[""])[0]); now=datetime.now()
                if et<=st: raise ValueError("End time must be later than start time.")
                if st<now.replace(second=0,microsecond=0): raise ValueError("Start time cannot be in the past.")
                conn=_booking_db(); slots=_booking_slots(conn,vt,st,et); conn.close(); self._send(200,json.dumps({"slots":slots}),"application/json; charset=utf-8")
            except Exception as exc: self._send(400,json.dumps({"error":str(exc),"slots":[]}),"application/json; charset=utf-8")
            return
        if path=="/booking": self._show_booking(parse_qs(parsed.query).get("id",[""])[0].strip()); return
        self._send(404,_booking_error("Page not found."))
    def do_POST(self):
        parsed=urlparse(self.path); length=int(self.headers.get("Content-Length","0")); data=parse_qs(self.rfile.read(length).decode("utf-8"))
        if parsed.path=="/book": self._create_booking(data); return
        if parsed.path=="/cancel": self._cancel_booking(data.get("booking_id",[""])[0].strip()); return
        self._send(404,_booking_error("Page not found."))
    def _create_booking(self,data):
        vehicle=data.get("vehicle_no",[""])[0].strip().upper(); vt=data.get("vehicle_type",[""])[0].strip(); sr=data.get("start",[""])[0].strip(); er=data.get("end",[""])[0].strip(); slot=data.get("slot_no",[""])[0].strip(); conn=None
        try:
            if not vehicle or not sr or not er or not slot: raise ValueError("Please fill in all booking fields.")
            st,et=_booking_dt(sr),_booking_dt(er); now=datetime.now()
            if st<now.replace(second=0,microsecond=0): raise ValueError("The selected arrival time is in the past.")
            if et<=st: raise ValueError("Exit/end time must be later than arrival/start time.")
            conn=_booking_db(); vr=conn.execute("SELECT * FROM vehicles WHERE vehicle_no=?",(vehicle,)).fetchone()
            if not vr: raise ValueError("Vehicle is not registered in SmartPark. Register it in the desktop app first.")
            if vr["vehicle_type"]!=vt: raise ValueError(f"Vehicle {vehicle} is registered as {vr['vehicle_type']}, not {vt}.")
            parked=conn.execute("SELECT slot_no FROM parking_sessions WHERE vehicle_no=? AND status='Active'",(vehicle,)).fetchone()
            if parked: raise ValueError(f"Vehicle {vehicle} is currently parked in slot {parked['slot_no']}. It cannot be pre-booked now.")
            existing=conn.execute("SELECT booking_id FROM bookings WHERE vehicle_no=? AND status IN ('Reserved','Confirmed','Checked-In') ORDER BY id DESC LIMIT 1",(vehicle,)).fetchone()
            if existing: raise ValueError(f"Vehicle already has an active/future booking: {existing['booking_id']}.")
            srw=conn.execute("SELECT * FROM slots WHERE slot_no=?",(slot,)).fetchone()
            if not srw or srw["slot_type"]!=vt: raise ValueError("The selected slot does not match the vehicle type.")
            if srw["status"]!="Available": raise ValueError("That slot is no longer available. Refresh the page and choose another slot.")
            overlap=conn.execute("SELECT booking_id,vehicle_no FROM bookings WHERE slot_no=? AND status IN ('Reserved','Confirmed') AND start_datetime < ? AND end_datetime > ? LIMIT 1",(slot,et.strftime("%Y-%m-%d %H:%M"),st.strftime("%Y-%m-%d %H:%M"))).fetchone()
            if overlap: raise ValueError(f"Slot {slot} is already booked for {overlap['vehicle_no']} during that time.")
            active=conn.execute("SELECT 1 FROM parking_sessions WHERE slot_no=? AND status='Active'",(slot,)).fetchone()
            if active: raise ValueError(f"Slot {slot} is currently occupied.")
            bid=_booking_id(); deadline=st+timedelta(minutes=GRACE_MINUTES)
            conn.execute("""INSERT INTO bookings (booking_id,vehicle_no,slot_no,start_date,end_date,start_time,end_time,start_datetime,end_datetime,created_at,status,fine,notes,arrival_deadline) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(bid,vehicle,slot,st.strftime("%Y-%m-%d"),et.strftime("%Y-%m-%d"),st.strftime("%H:%M"),et.strftime("%H:%M"),st.strftime("%Y-%m-%d %H:%M"),et.strftime("%Y-%m-%d %H:%M"),now.strftime("%Y-%m-%d %H:%M:%S"),"Reserved",0,"Created from SmartPark Pre-Booking Website.",deadline.strftime("%Y-%m-%d %H:%M")))
            conn.execute("UPDATE slots SET status='Reserved',vehicle_no=?,booking_id=? WHERE slot_no=?",(vehicle,bid,slot)); conn.commit()
            body=f"""<div class="card"><div class="success"><h2>✅ Pre-Booking Confirmed</h2><p>Your parking slot has been reserved successfully.</p></div><div class="details"><div><b>Booking ID</b><br>{html.escape(bid)}</div><div><b>Vehicle</b><br>{html.escape(vehicle)}</div><div><b>Slot</b><br>{html.escape(slot)}</div><div><b>Status</b><br>RESERVED</div><div><b>Arrival</b><br>{st.strftime("%d-%m-%Y %I:%M %p")}</div><div><b>Exit</b><br>{et.strftime("%d-%m-%Y %I:%M %p")}</div><div><b>Arrival Deadline</b><br>{deadline.strftime("%d-%m-%Y %I:%M %p")}</div><div><b>No-Show Fine</b><br>₹{NO_SHOW_FINE}</div></div><div class="notice">Your 30-minute arrival window starts at <b>{st.strftime("%I:%M %p")}</b>. Arrive during that window and SmartPark will connect the vehicle entry to this booking. Otherwise it becomes No-Show and the ₹50 fine is applied.</div><div class="row"><a class="btn" href="/booking?id={quote(bid)}">View / Cancel Booking</a><a class="btn green" href="/">New Booking</a></div></div>"""
            self._send(200,_booking_page(body))
        except Exception as exc:
            if conn: conn.rollback()
            self._send(400,_booking_page(_booking_form_body(str(exc))))
        finally:
            if conn: conn.close()
    def _show_booking(self,bid):
        if not bid: self._send(400,_booking_error("Enter a Booking ID.")); return
        conn=_booking_db(); row=conn.execute("SELECT * FROM bookings WHERE booking_id=?",(bid,)).fetchone(); conn.close()
        if not row: self._send(404,_booking_error("Booking not found.")); return
        cancel=""
        if row["status"] in ("Reserved","Confirmed"):
            cancel=f"""<form method="POST" action="/cancel" onsubmit="return confirm('Cancel this booking?')"><input type="hidden" name="booking_id" value="{html.escape(bid)}"><button class="btn red" type="submit">Cancel Booking — No Fine Before Deadline</button></form>"""
        body=f"""<div class="card"><h2>📋 Booking Details</h2><div class="details"><div><b>Booking ID</b><br>{html.escape(row['booking_id'])}</div><div><b>Status</b><br>{html.escape(row['status'])}</div><div><b>Vehicle</b><br>{html.escape(row['vehicle_no'])}</div><div><b>Slot</b><br>{html.escape(row['slot_no'])}</div><div><b>Arrival</b><br>{html.escape(row['start_datetime'])}</div><div><b>Exit</b><br>{html.escape(row['end_datetime'])}</div><div><b>Arrival Deadline</b><br>{html.escape(row['arrival_deadline'] or '—')}</div><div><b>Fine</b><br>₹{float(row['fine'] or 0):.0f}</div></div><div class="notice">Cancellation before the arrival deadline carries <b>no fine</b>. A booking that reaches the deadline without arrival or cancellation becomes <b>No-Show</b> and gets the ₹{NO_SHOW_FINE} fine.</div><div class="row">{cancel}<a class="btn green" href="/">Back</a></div></div>"""; self._send(200,_booking_page(body))
    def _cancel_booking(self,bid):
        if not bid: self._send(400,_booking_error("Booking ID is required.")); return
        conn=_booking_db()
        try:
            row=conn.execute("SELECT * FROM bookings WHERE booking_id=?",(bid,)).fetchone()
            if not row: raise ValueError("Booking not found.")
            if row["status"] not in ("Reserved","Confirmed"): raise ValueError(f"This booking is already {row['status']} and cannot be cancelled.")
            deadline=datetime.strptime(row["arrival_deadline"],"%Y-%m-%d %H:%M") if row["arrival_deadline"] else None
            if deadline and datetime.now()>deadline: raise ValueError("The cancellation deadline has passed. SmartPark will handle this as No-Show.")
            conn.execute("UPDATE bookings SET status='Cancelled',fine=0,notes=? WHERE booking_id=?",("Cancelled from Pre-Booking Website before arrival deadline.",bid)); conn.execute("UPDATE slots SET status='Available',vehicle_no=NULL,booking_id=NULL WHERE slot_no=? AND booking_id=?",(row["slot_no"],bid)); conn.commit()
            self._send(200,_booking_page(f"""<div class="card"><div class="success"><h2>✅ Booking Cancelled</h2><p>Booking <b>{html.escape(bid)}</b> was cancelled successfully. No fine was charged.</p></div><a class="btn" href="/">Back to Pre-Booking</a></div>"""))
        except Exception as exc: conn.rollback(); self._send(400,_booking_error(str(exc)))
        finally: conn.close()


class PayServer(ThreadingHTTPServer):
    """Web server that refuses to share its port with another running copy."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):      # Windows
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        super().server_bind()


class PayHandler(BaseHTTPRequestHandler):
    """Tiny web server used by the QR code payment page."""

    def log_message(self, *args):
        pass  # keep the IDLE shell quiet

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _payment(self, token):
        with PAYMENTS_LOCK:
            p = PAYMENTS.get(token)
            return dict(p) if p else None

    def do_GET(self):
        path, _, query = self.path.partition("?")
        parts = [x for x in path.split("/") if x]

        if not parts:
            self._send(200, "SMARTPARK payment server is running.", "text/plain; charset=utf-8")
            return

        if len(parts) == 2 and parts[0] in ("pay", "status", "receipt"):
            p = self._payment(parts[1])
            if p is None:
                self._send(404, "<h2>This payment link is not recognised. Please ask the cashier to show the QR code again.</h2>")
                return

            if parts[0] == "pay":
                if p["status"] == "paid":
                    self._send(302, "", extra={"Location": f"/receipt/{parts[1]}"})
                else:
                    self._send(200, build_pay_page(parts[1], p))
            elif parts[0] == "status":
                self._send(200, json.dumps({"status": p["status"]}), "application/json")
            else:  # receipt
                if p["status"] != "paid" or not p.get("receipt"):
                    self._send(200, "<h2>Payment not confirmed yet. Please wait for the cashier.</h2>")
                    return
                extra = {}
                if "download=1" in query:
                    extra["Content-Disposition"] = f'attachment; filename="Receipt_{p["txn"]}.html"'
                self._send(200, p["receipt"], extra=extra)
            return

        self._send(404, "Not found", "text/plain; charset=utf-8")

    def do_POST(self):
        parts = [x for x in self.path.split("?")[0].split("/") if x]
        if len(parts) == 2 and parts[0] == "claim":
            with PAYMENTS_LOCK:
                p = PAYMENTS.get(parts[1])
                if p is None:
                    self._send(404, json.dumps({"error": "invalid"}), "application/json")
                    return
                if p["status"] == "pending":
                    p["status"] = "claimed"
                status = p["status"]
            self._send(200, json.dumps({"status": status}), "application/json")
            return
        self._send(404, "Not found", "text/plain; charset=utf-8")



class SmartParkingApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1320x800")
        self.root.minsize(1150, 700)
        self.root.configure(bg=BG)

        self.db = sqlite3.connect(DB_NAME)
        self.db.row_factory = sqlite3.Row
        self.theme_name = "dark"
        self.theme = DARK_THEME.copy()
        self.current_page_method = self.show_dashboard
        self.create_tables()
        self.seed_slots()
        self.start_payment_server()
        self.start_booking_server()
        self.setup_styles()
        self.build_shell()
        self.apply_theme(refresh=False)
        self.show_dashboard()
        self.update_clock()
        self.process_booking_expiry()

        self.root.protocol("WM_DELETE_WINDOW", self.close_app)

    # ---------------- DATABASE ----------------

    def create_tables(self):
        c = self.db.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS owners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                contact TEXT NOT NULL UNIQUE
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_no TEXT NOT NULL UNIQUE,
                vehicle_type TEXT NOT NULL,
                owner_name TEXT NOT NULL,
                owner_contact TEXT NOT NULL,
                persons INTEGER NOT NULL DEFAULT 1,
                elder_care INTEGER NOT NULL DEFAULT 0,
                parking_slot TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS slots (
                slot_no TEXT PRIMARY KEY,
                slot_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Available',
                vehicle_no TEXT,
                booking_id TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id TEXT UNIQUE,
                vehicle_no TEXT NOT NULL,
                slot_no TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                start_datetime TEXT NOT NULL,
                end_datetime TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                fine REAL DEFAULT 0,
                notes TEXT DEFAULT '',
                arrival_deadline TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS parking_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parking_id TEXT UNIQUE,
                vehicle_no TEXT NOT NULL,
                slot_no TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                exit_date TEXT,
                exit_time TEXT,
                entry_datetime TEXT NOT NULL,
                exit_datetime TEXT,
                duration_minutes INTEGER DEFAULT 0,
                fee REAL DEFAULT 0,
                payment_method TEXT,
                payment_status TEXT DEFAULT 'Pending',
                transaction_id TEXT,
                status TEXT NOT NULL,
                booking_id TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id TEXT UNIQUE,
                vehicle_no TEXT NOT NULL,
                parking_id TEXT,
                complaint_type TEXT NOT NULL,
                description TEXT,
                reported_by TEXT,
                created_at TEXT NOT NULL,
                status TEXT DEFAULT 'Open'
            )
        """)

        # Backward-compatible migrations for an older smart_parking.db.
        migrations = {
            "vehicles": [
                ("parking_slot", "TEXT"),
                ("elder_care", "INTEGER DEFAULT 0")
            ],
            "parking_sessions": [
                ("parking_id", "TEXT"),
                ("vehicle_no", "TEXT"),
                ("slot_no", "TEXT"),
                ("entry_date", "TEXT"),
                ("entry_time", "TEXT"),
                ("exit_date", "TEXT"),
                ("exit_time", "TEXT"),
                ("entry_datetime", "TEXT"),
                ("exit_datetime", "TEXT"),
                ("duration_minutes", "INTEGER DEFAULT 0"),
                ("fee", "REAL DEFAULT 0"),
                ("payment_method", "TEXT"),
                ("payment_status", "TEXT DEFAULT 'Pending'"),
                ("transaction_id", "TEXT"),
                ("status", "TEXT"),
                ("booking_id", "TEXT")
            ],
            "bookings": [
                ("booking_id", "TEXT"),
                ("vehicle_no", "TEXT"),
                ("slot_no", "TEXT"),
                ("start_date", "TEXT"),
                ("end_date", "TEXT"),
                ("start_time", "TEXT"),
                ("end_time", "TEXT"),
                ("start_datetime", "TEXT"),
                ("end_datetime", "TEXT"),
                ("created_at", "TEXT"),
                ("status", "TEXT"),
                ("fine", "REAL DEFAULT 0"),
                ("notes", "TEXT DEFAULT ''"),
                ("arrival_deadline", "TEXT")
            ],
            "complaints": [
                ("complaint_id", "TEXT"),
                ("vehicle_no", "TEXT"),
                ("parking_id", "TEXT"),
                ("complaint_type", "TEXT"),
                ("description", "TEXT"),
                ("reported_by", "TEXT"),
                ("created_at", "TEXT"),
                ("status", "TEXT DEFAULT 'Open'")
            ]
        }

        for table, columns in migrations.items():
            existing = {
                row[1] for row in self.db.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for column, definition in columns:
                if column not in existing:
                    try:
                        self.db.execute(
                            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                        )
                    except sqlite3.OperationalError:
                        pass

        try:
            self.db.execute(
                "UPDATE parking_sessions SET status='Active' "
                "WHERE status IS NULL AND exit_datetime IS NULL"
            )
            self.db.execute(
                "UPDATE parking_sessions SET status='Completed' "
                "WHERE status IS NULL AND exit_datetime IS NOT NULL"
            )
            self.db.execute(
                "UPDATE parking_sessions SET payment_status='Pending' "
                "WHERE payment_status IS NULL"
            )
            self.db.execute(
                "UPDATE complaints SET status='Open' WHERE status IS NULL"
            )
        except sqlite3.OperationalError:
            pass

        self.db.commit()

    def seed_slots(self):
        # 20 slots per vehicle type, matching the Slot Location map and Route Guide.
        c = self.db.cursor()
        groups = [
            ("B", "Bike", 20),
            ("C", "Car", 20),
            ("V", "Van", 20)
        ]
        for prefix, slot_type, count in groups:
            for i in range(1, count + 1):
                c.execute(
                    "INSERT OR IGNORE INTO slots(slot_no, slot_type) VALUES(?, ?)",
                    (f"{prefix}-{i:02d}", slot_type)
                )
        self.db.commit()

    # ---------------- GENERAL HELPERS ----------------

    def now(self):
        return datetime.now()

    def make_id(self, prefix):
        return prefix + datetime.now().strftime("%Y%m%d%H%M%S%f")[-12:]

    def normalize_vehicle(self, value):
        return value.strip().upper()

    def valid_phone(self, value):
        return bool(re.fullmatch(r"\d{10}", value.strip()))

    def date_to_db(self, date_text):
        """Accept DD-MM-YYYY and store YYYY-MM-DD."""
        value = date_text.strip()
        try:
            return datetime.strptime(value, "%d-%m-%Y").strftime("%Y-%m-%d")
        except ValueError:
            raise ValueError("Date must be in DD-MM-YYYY format, for example 08-10-2026.")

    def display_date(self, db_date):
        if not db_date:
            return ""
        try:
            return datetime.strptime(db_date, "%Y-%m-%d").strftime("%d-%m-%Y")
        except ValueError:
            return db_date

    def validate_time(self, time_text):
        """Accept 9:00 AM, 09:00 AM, 12:00 PM, etc."""
        value = " ".join(time_text.strip().upper().split())
        for fmt in ("%I:%M %p", "%I:%M%p"):
            try:
                return datetime.strptime(value, fmt).strftime("%H:%M")
            except ValueError:
                pass
        raise ValueError(
            "Time must be in 12-hour format such as 09:00 AM or 02:00 PM."
        )

    def display_time(self, db_time):
        if not db_time:
            return ""
        try:
            return datetime.strptime(db_time, "%H:%M").strftime("%I:%M %p")
        except ValueError:
            return db_time

    def combine_date_time(self, date_text, time_text):
        db_date = self.date_to_db(date_text)
        db_time = self.validate_time(time_text)
        return datetime.strptime(f"{db_date} {db_time}", "%Y-%m-%d %H:%M")

    def pretty_datetime(self, value):
        """Format 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD HH:MM:SS' for display."""
        if not value:
            return ""
        for fmt_in, fmt_out in (
            ("%Y-%m-%d %H:%M:%S", "%d-%m-%Y %I:%M:%S %p"),
            ("%Y-%m-%d %H:%M", "%d-%m-%Y %I:%M %p"),
        ):
            try:
                return datetime.strptime(value, fmt_in).strftime(fmt_out)
            except (ValueError, TypeError):
                continue
        return value

    def hours_for_fee(self, minutes):
        return max(1, math.ceil(max(1, minutes) / 60))

    def time_values(self):
        """Hour / minute / AM-PM choices; AM/PM has no default."""
        return (
            [""] + [str(i) for i in range(1, 13)],
            [""] + [f"{i:02d}" for i in range(60)],
            ["", "AM", "PM"]
        )

    def time_from_parts(self, hour, minute, ampm):
        """Convert explicit 12-hour controls into a 24-hour HH:MM value."""
        hour = str(hour).strip()
        minute = str(minute).strip()
        ampm = str(ampm).strip().upper()

        if not hour or not minute or ampm not in ("AM", "PM"):
            raise ValueError("Please select Hour, Minute and AM/PM.")

        try:
            h = int(hour)
            m = int(minute)
        except ValueError:
            raise ValueError("Hour and Minute must be valid numbers.")

        if h < 1 or h > 12 or m < 0 or m > 59:
            raise ValueError("Please select a valid 12-hour time.")

        h24 = h % 12
        if ampm == "PM":
            h24 += 12

        return f"{h24:02d}:{m:02d}"

    def process_booking_expiry(self):
        """Auto-cancel reservations whose vehicle never arrived (No-Show)."""
        try:
            now_text = self.now().strftime("%Y-%m-%d %H:%M")
            rows = self.db.execute(
                """SELECT booking_id, vehicle_no, slot_no
                   FROM bookings
                   WHERE status IN ('Reserved','Confirmed')
                     AND arrival_deadline IS NOT NULL
                     AND arrival_deadline <= ?""",
                (now_text,)
            ).fetchall()

            for row in rows:
                self.db.execute(
                    """UPDATE bookings
                       SET status='No-Show', fine=?, notes=?
                       WHERE booking_id=? AND status IN ('Reserved','Confirmed')""",
                    (NO_SHOW_FINE,
                     f"No-show: vehicle did not arrive within {GRACE_MINUTES} minutes.",
                     row["booking_id"])
                )
                self.db.execute(
                    """UPDATE slots
                       SET status='Available', vehicle_no=NULL, booking_id=NULL
                       WHERE slot_no=? AND booking_id=? AND status='Reserved'""",
                    (row["slot_no"], row["booking_id"])
                )

            if rows:
                self.db.commit()
        except sqlite3.Error:
            pass

        try:
            self.root.after(10000, self.process_booking_expiry)
        except tk.TclError:
            pass

    def cancel_booking(self, tree):
        """Cancel a selected booking without applying the no-show fine."""
        selected = tree.selection()
        if not selected:
            messagebox.showwarning(
                "Select Booking", "Please select a booking to cancel.",
                parent=self.root
            )
            return

        values = tree.item(selected[0], "values")
        if not values:
            return
        booking_id = values[0]
        row = self.db.execute(
            "SELECT * FROM bookings WHERE booking_id=?", (booking_id,)
        ).fetchone()
        if not row:
            messagebox.showerror("Booking Not Found", "The selected booking no longer exists.", parent=self.root)
            return

        if row["status"] not in ("Reserved", "Confirmed"):
            messagebox.showinfo(
                "Cannot Cancel",
                f"This booking is already {row['status']} and cannot be cancelled.",
                parent=self.root
            )
            return

        if not messagebox.askyesno(
            "Cancel Booking",
            f"Cancel booking {booking_id} for vehicle {row['vehicle_no']}?\n\n"
            "User cancellation has NO fine.",
            parent=self.root
        ):
            return

        self.db.execute(
            "UPDATE bookings SET status='Cancelled', fine=0, notes=? WHERE booking_id=?",
            ("Cancelled by user before arrival deadline.", booking_id)
        )
        self.db.execute(
            """UPDATE slots
               SET status='Available', vehicle_no=NULL, booking_id=NULL
               WHERE slot_no=? AND booking_id=?""",
            (row["slot_no"], booking_id)
        )
        self.db.commit()

        messagebox.showinfo(
            "Booking Cancelled",
            f"Booking {booking_id} has been cancelled.\n\nNo fine is charged.",
            parent=self.root
        )
        self.show_bookings()

    # ---------------- PRE-BOOKING WEBSITE ----------------

    def start_booking_server(self):
        self.booking_ip = get_lan_ip()
        self.booking_server = None
        self.booking_port = BOOKING_PORT
        global BOOKING_DB_PATH
        BOOKING_DB_PATH = os.path.join(BASE_DIR, DB_NAME)
        for port in range(BOOKING_PORT, BOOKING_PORT + 20):
            try:
                self.booking_server = BookingServer(("0.0.0.0", port), BookingHandler)
                self.booking_port = port
                threading.Thread(target=self.booking_server.serve_forever, daemon=True).start()
                break
            except OSError:
                self.booking_server = None

    def booking_url(self):
        return f"http://{self.booking_ip}:{self.booking_port}/"

    # ---------------- ONLINE PAYMENT SERVER ----------------

    def start_payment_server(self):
        """Start the small web server that serves the QR payment page."""
        self.pay_ip = get_lan_ip()
        self.pay_server = None
        self.pay_port = PAY_PORT
        # If an older copy of the program is still open and using the port,
        # silently use the next free one so the QR always reaches THIS program.
        for port in range(PAY_PORT, PAY_PORT + 20):
            try:
                self.pay_server = PayServer(("0.0.0.0", port), PayHandler)
                self.pay_port = port
                threading.Thread(
                    target=self.pay_server.serve_forever, daemon=True
                ).start()
                break
            except OSError:
                self.pay_server = None

    def pay_url(self, token):
        return f"http://{self.pay_ip}:{self.pay_port}/pay/{token}"

    # ---------------- RECEIPTS ----------------

    def save_receipt_files(self, transaction_id, receipt_text, receipt_html):
        """Save the receipt as .txt and as a printable .html file."""
        os.makedirs(RECEIPT_DIR, exist_ok=True)
        txt_path = os.path.join(RECEIPT_DIR, f"Receipt_{transaction_id}.txt")
        html_path = os.path.join(RECEIPT_DIR, f"Receipt_{transaction_id}.html")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(receipt_text)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(receipt_html)
        return txt_path, html_path

    def open_receipt(self, path, print_it=False):
        """Open the HTML receipt in the browser (optionally with the print dialog)."""
        try:
            uri = Path(path).resolve().as_uri()
            if print_it:
                uri += "#print"
            webbrowser.open(uri)
        except Exception as exc:
            messagebox.showerror("Receipt", f"Could not open the receipt:\n{exc}")

    # ---------------- THEME / STYLE ----------------

    def apply_theme(self, refresh=True):
        """Apply the selected theme to the complete visible UI."""
        global BG, SIDEBAR, PANEL, INPUT, BLUE, GREEN, RED, AMBER, TEXT, MUTED
        BG = self.theme["BG"]
        SIDEBAR = self.theme["SIDEBAR"]
        PANEL = self.theme["PANEL"]
        INPUT = self.theme["INPUT"]
        BLUE = self.theme["BLUE"]
        GREEN = self.theme["GREEN"]
        RED = self.theme["RED"]
        AMBER = self.theme["AMBER"]
        TEXT = self.theme["TEXT"]
        MUTED = self.theme["MUTED"]

        self.root.configure(bg=BG)
        self.setup_styles()
        self._recolor_widget_tree(self.root)
        if hasattr(self, "theme_toggle"):
            self.theme_toggle.configure(text=self.theme_button_text())
        if refresh and hasattr(self, "current_page_method"):
            try:
                self.current_page_method()
            except tk.TclError:
                pass

    def _recolor_widget_tree(self, widget):
        """Recolor existing Tk widgets, including frames and common controls."""
        dark_to_light = {
            "#0f172a": BRIGHT_THEME["BG"], "#0b1220": BRIGHT_THEME["SIDEBAR"],
            "#172033": BRIGHT_THEME["PANEL"], "#1e293b": BRIGHT_THEME["INPUT"],
            "#111827": BRIGHT_THEME["HEADER"], "#f8fafc": BRIGHT_THEME["TEXT"],
            "#94a3b8": BRIGHT_THEME["MUTED"], "#cbd5e1": "#334155",
            "#334155": BRIGHT_THEME["BORDER"], "#1e3a8a": BRIGHT_THEME["TABLE_HEAD"],
            "#10213f": BRIGHT_THEME["INFO"],
        }
        light_to_dark = {v: k for k, v in dark_to_light.items()}
        mapping = dark_to_light if self.theme_name == "bright" else light_to_dark

        try:
            cfg = widget.configure()
            for option in ("bg", "background", "fg", "foreground", "insertbackground"):
                if option in cfg:
                    try:
                        current = widget.cget(option)
                        if current in mapping:
                            widget.configure(**{option: mapping[current]})
                    except (tk.TclError, TypeError):
                        pass
        except tk.TclError:
            return

        for child in widget.winfo_children():
            self._recolor_widget_tree(child)

    def toggle_theme(self):
        self.theme_name = "bright" if self.theme_name == "dark" else "dark"
        self.theme = BRIGHT_THEME.copy() if self.theme_name == "bright" else DARK_THEME.copy()
        self.apply_theme(refresh=True)

    def theme_button_text(self):
        return "☀ Bright Mode" if self.theme_name == "dark" else "🌙 Dark Mode"

    # ---------------- STYLE / SHELL ----------------

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        t = self.theme

        style.configure(
            "Treeview",
            background=t["TABLE"],
            foreground=t["TEXT"],
            fieldbackground=t["TABLE"],
            borderwidth=0,
            rowheight=32,
            font=("Segoe UI", 10)
        )
        style.map(
            "Treeview",
            background=[("selected", "#1d4ed8")],
            foreground=[("selected", "white")]
        )
        style.configure(
            "Treeview.Heading",
            background=t["TABLE_HEAD"],
            foreground=t["TEXT"],
            font=("Segoe UI", 10, "bold"),
            padding=8
        )

        style.configure(
            "Dark.TCombobox",
            fieldbackground=t["INPUT"],
            background=t["INPUT"],
            foreground=t["TEXT"],
            arrowcolor=t["TEXT"],
            bordercolor=t["BORDER"],
            lightcolor=t["INPUT"],
            darkcolor=t["INPUT"],
            padding=7
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", t["INPUT"]), ("disabled", t["TABLE"])],
            foreground=[("readonly", t["TEXT"]), ("disabled", "#64748b")],
            selectbackground=[("readonly", t["INPUT"])],
            selectforeground=[("readonly", t["TEXT"])],
            background=[("readonly", t["INPUT"])]
        )

        style.configure(
            "Dark.TEntry",
            fieldbackground=t["INPUT"],
            foreground=t["TEXT"],
            insertcolor=t["TEXT"],
            bordercolor=t["BORDER"],
            lightcolor=t["INPUT"],
            darkcolor=t["INPUT"],
            padding=8
        )

    def build_shell(self):
        header = tk.Frame(self.root, bg="#111827", height=72)
        header.pack(fill="x")

        tk.Label(
            header, text="SMARTPARK", bg="#111827", fg="#60a5fa",
            font=("Segoe UI", 22, "bold")
        ).pack(side="left", padx=(24, 10), pady=16)

        tk.Label(
            header, text="Vehicle & Parking Management System",
            bg="#111827", fg="#cbd5e1", font=("Segoe UI", 11)
        ).pack(side="left")

        self.clock_label = tk.Label(
            header, bg="#111827", fg=MUTED, font=("Segoe UI", 10)
        )
        self.clock_label.pack(side="right", padx=(8, 20))

        self.theme_toggle = tk.Button(
            header, text=self.theme_button_text(), command=self.toggle_theme,
            bg="#2563eb", fg="white", activebackground="#1d4ed8",
            activeforeground="white", relief="flat", bd=0,
            padx=13, pady=7, font=("Segoe UI", 9, "bold"), cursor="hand2"
        )
        self.theme_toggle.pack(side="right", padx=8)

        self.sidebar = tk.Frame(self.root, bg=SIDEBAR, width=205)
        self.sidebar.pack(side="left", fill="y")

        self.content = tk.Frame(self.root, bg=BG)
        self.content.pack(side="right", fill="both", expand=True)

        nav_items = [
            ("🏠  Dashboard", self.show_dashboard),
            ("🚗  Vehicles", self.show_vehicles),
            ("🅿  Parking", self.show_parking),
            ("📍  Slot Location", self.show_slot_location),
            ("📅  Pre-Booking", self.show_bookings),
            ("🔎  Particular History", self.show_particular_history),
            ("📜  History", self.show_history),
            ("⚠  Complaints", self.show_complaints),
            ("📊  Reports", self.show_reports),
            ("⚙  Settings", self.show_settings),
        ]

        for label, command in nav_items:
            tk.Button(
                self.sidebar,
                text=label,
                command=command,
                anchor="w",
                relief="flat",
                bd=0,
                bg=SIDEBAR,
                fg="#cbd5e1",
                activebackground="#1d4ed8",
                activeforeground="white",
                font=("Segoe UI", 10, "bold"),
                padx=18,
                pady=13,
                cursor="hand2"
            ).pack(fill="x")

        tk.Label(
            self.sidebar,
            text="PL015 • HACKATHON",
            bg=SIDEBAR,
            fg="#64748b",
            font=("Segoe UI", 9)
        ).pack(side="bottom", pady=16)

    def clear_content(self):
        for widget in self.content.winfo_children():
            widget.destroy()

    def page_title(self, title, subtitle=""):
        tk.Label(
            self.content, text=title, bg=BG, fg=TEXT,
            font=("Segoe UI", 23, "bold")
        ).pack(anchor="w", padx=28, pady=(22, 3))

        if subtitle:
            tk.Label(
                self.content, text=subtitle, bg=BG, fg=MUTED,
                font=("Segoe UI", 10)
            ).pack(anchor="w", padx=30, pady=(0, 18))

    def card(self, parent, value, label):
        frame = tk.Frame(parent, bg=PANEL, padx=18, pady=15)
        frame.pack(side="left", fill="x", expand=True, padx=5)

        tk.Label(
            frame, text=str(value), bg=PANEL, fg="#60a5fa",
            font=("Segoe UI", 23, "bold")
        ).pack(anchor="w")

        tk.Label(
            frame, text=label, bg=PANEL, fg=MUTED,
            font=("Segoe UI", 9, "bold")
        ).pack(anchor="w")

    def make_entry(self, parent, variable, width=32):
        return tk.Entry(
            parent,
            textvariable=variable,
            width=width,
            bg=INPUT,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground="#2563eb",
            selectforeground="white",
            relief="flat",
            bd=0,
            font=("Segoe UI", 10)
        )

    def make_combo(self, parent, variable, values, width=20):
        return ttk.Combobox(
            parent,
            textvariable=variable,
            values=values,
            state="readonly",
            width=width,
            style="Dark.TCombobox"
        )

    def action_button(self, parent, text, command, bg=BLUE, width=None):
        kwargs = dict(
            text=text, command=command, bg=bg, fg="white",
            activebackground=bg, activeforeground="white",
            relief="flat", bd=0, padx=15, pady=9,
            font=("Segoe UI", 10, "bold"), cursor="hand2"
        )
        if width:
            kwargs["width"] = width
        return tk.Button(parent, **kwargs)

    def make_table(self, parent, columns, widths=None):
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="both", expand=True, padx=28, pady=10)

        tree = ttk.Treeview(outer, columns=columns, show="headings")
        for i, col in enumerate(columns):
            tree.heading(col, text=col)
            tree.column(
                col,
                width=(widths[i] if widths and i < len(widths) else 130),
                minwidth=80,
                anchor="center"
            )

        ybar = ttk.Scrollbar(outer, orient="vertical", command=tree.yview)
        xbar = ttk.Scrollbar(outer, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)

        tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        return tree

    # ---------------- DASHBOARD ----------------

    def show_dashboard(self):
        self.current_page_method = self.show_dashboard
        self.clear_content()
        self.page_title(
            "Dashboard",
            "Live overview of vehicles, reservations, parking and payments"
        )

        c = self.db.cursor()

        total = c.execute("SELECT COUNT(*) FROM slots").fetchone()[0]
        available = c.execute(
            "SELECT COUNT(*) FROM slots WHERE status='Available'"
        ).fetchone()[0]
        occupied = c.execute(
            "SELECT COUNT(*) FROM slots WHERE status='Occupied'"
        ).fetchone()[0]
        reserved = c.execute(
            "SELECT COUNT(*) FROM slots WHERE status='Reserved'"
        ).fetchone()[0]

        today = self.now().strftime("%Y-%m-%d")
        revenue = c.execute(
            """SELECT COALESCE(SUM(fee),0)
               FROM parking_sessions
               WHERE status='Completed' AND substr(exit_datetime,1,10)=?""",
            (today,)
        ).fetchone()[0]

        bookings_today = c.execute(
            "SELECT COUNT(*) FROM bookings WHERE substr(created_at,1,10)=?",
            (today,)
        ).fetchone()[0]

        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="x", padx=22)

        for value, label in [
            (total, "TOTAL SLOTS"),
            (available, "AVAILABLE"),
            (occupied, "OCCUPIED"),
            (reserved, "RESERVED"),
            (f"₹{revenue:.0f}", "TODAY'S REVENUE"),
            (bookings_today, "TODAY'S BOOKINGS")
        ]:
            self.card(row, value, label)

        type_summary = tk.Frame(self.content, bg=BG)
        type_summary.pack(fill="x", padx=22, pady=(12, 0))

        type_counts = c.execute(
            """SELECT v.vehicle_type, COUNT(*) AS count
               FROM parking_sessions ps
               JOIN vehicles v ON v.vehicle_no=ps.vehicle_no
               WHERE substr(ps.entry_datetime,1,10)=?
               GROUP BY v.vehicle_type""",
            (today,)
        ).fetchall()
        count_map = {r["vehicle_type"]: r["count"] for r in type_counts}

        for vehicle_type in ("Car", "Bike", "Van"):
            self.card(type_summary, count_map.get(vehicle_type, 0), f"TODAY'S {vehicle_type.upper()}S")

        panel = tk.Frame(self.content, bg=PANEL, padx=22, pady=22)
        panel.pack(fill="both", expand=True, padx=28, pady=24)

        tk.Label(
            panel, text="Quick Actions", bg=PANEL, fg=TEXT,
            font=("Segoe UI", 15, "bold")
        ).pack(anchor="w")

        actions = [
            ("➕ Register Vehicle", self.vehicle_form),
            ("📅 New Booking", self.show_bookings),
            ("🚪 Record Entry", self.entry_form),
            ("🔎 Particular History", self.show_particular_history),
            ("➕ Add Complaint", self.complaint_form),
        ]

        actions_frame = tk.Frame(panel, bg=PANEL)
        actions_frame.pack(fill="x", pady=20)

        for text, command in actions:
            self.action_button(actions_frame, text, command).pack(
                side="left", padx=5
            )

        rule = tk.Frame(panel, bg="#1e293b", padx=15, pady=14)
        rule.pack(fill="x", pady=10)

        tk.Label(
            rule,
            text="BOOKING RULE",
            bg="#1e293b",
            fg="#fbbf24",
            font=("Segoe UI", 10, "bold")
        ).pack(anchor="w")

        tk.Label(
            rule,
            text=(
                "A pre-booked vehicle must arrive within "
                f"{GRACE_MINUTES} minutes of booking. "
                "If it does not check in during that window, the booking is "
                "automatically marked No-Show, the slot is released and the "
                f"configurable ₹{NO_SHOW_FINE} fine is recorded."
            ),
            bg="#1e293b",
            fg="#cbd5e1",
            wraplength=950,
            justify="left"
        ).pack(anchor="w", pady=(5, 0))

    # ---------------- VEHICLES ----------------

    def show_vehicles(self):
        self.current_page_method = self.show_vehicles
        self.clear_content()
        self.page_title(
            "Vehicle Management",
            "Register, search, update and delete vehicle records"
        )

        bar = tk.Frame(self.content, bg=BG)
        bar.pack(fill="x", padx=28)

        search_var = tk.StringVar()
        tk.Label(
            bar, text="Search", bg=BG, fg=MUTED,
            font=("Segoe UI", 10, "bold")
        ).pack(side="left")

        search_entry = self.make_entry(bar, search_var, 30)
        search_entry.pack(side="left", padx=8, ipady=6)

        tree = self.make_table(
            self.content,
            (
                "ID", "Vehicle No", "Type", "Owner", "Contact",
                "Persons", "Elder Care", "Slot", "Entry Time", "Exit Time"
            ),
            [55, 135, 80, 155, 120, 70, 90, 75, 155, 155]
        )

        def load():
            for item in tree.get_children():
                tree.delete(item)

            q = "%" + search_var.get().strip() + "%"
            rows = self.db.execute(
                """SELECT
                       v.id, v.vehicle_no, v.vehicle_type, v.owner_name,
                       v.owner_contact, v.persons, v.elder_care,
                       COALESCE(
                           (SELECT ps.slot_no
                            FROM parking_sessions ps
                            WHERE ps.vehicle_no=v.vehicle_no
                            ORDER BY ps.id DESC LIMIT 1),
                           v.parking_slot, ''
                       ) AS display_slot,
                       (SELECT ps.entry_datetime
                        FROM parking_sessions ps
                        WHERE ps.vehicle_no=v.vehicle_no
                        ORDER BY ps.id DESC LIMIT 1) AS latest_entry,
                       (SELECT ps.exit_datetime
                        FROM parking_sessions ps
                        WHERE ps.vehicle_no=v.vehicle_no
                        ORDER BY ps.id DESC LIMIT 1) AS latest_exit
                   FROM vehicles v
                   WHERE v.vehicle_no LIKE ?
                      OR v.owner_name LIKE ?
                      OR v.owner_contact LIKE ?
                   ORDER BY v.id DESC""",
                (q, q, q)
            ).fetchall()

            for row in rows:
                entry_text = self.pretty_datetime(row["latest_entry"]) if row["latest_entry"] else "—"
                exit_text = self.pretty_datetime(row["latest_exit"]) if row["latest_exit"] else "—"
                tree.insert(
                    "", "end",
                    values=(
                        row["id"], row["vehicle_no"], row["vehicle_type"],
                        row["owner_name"], row["owner_contact"], row["persons"],
                        "YES" if row["elder_care"] else "NO",
                        row["display_slot"] or "—", entry_text, exit_text
                    )
                )

        self.action_button(bar, "🔎 Search", load).pack(side="left", padx=5)

        self.action_button(
            bar, "➕ Add Vehicle", lambda: self.vehicle_form(load), GREEN
        ).pack(side="right", padx=5)

        self.action_button(
            bar, "🗑 Delete", lambda: self.delete_vehicle(tree, load), RED
        ).pack(side="right", padx=5)

        tree.bind("<Double-1>", lambda event: self.edit_vehicle(tree, load))

        load()

    def vehicle_form(self, refresh=None, row=None):
        # Scrollable Add/Edit Vehicle window with a fixed Save button.
        win = tk.Toplevel(self.root)
        win.title("Add / Edit Vehicle")
        win.geometry("540x620")
        win.minsize(480, 500)
        win.configure(bg=BG)
        win.grab_set()

        # When editing, read the real stored values from the database.
        db_vehicle = None
        if row:
            db_vehicle = self.db.execute(
                "SELECT * FROM vehicles WHERE id=?", (row[0],)
            ).fetchone()
        current_slot = (db_vehicle["parking_slot"] or "") if db_vehicle else ""

        header = tk.Frame(win, bg=BG)
        header.pack(fill="x", padx=24, pady=(18, 8))

        tk.Label(
            header, text="Vehicle Details", bg=BG, fg=TEXT,
            font=("Segoe UI", 18, "bold")
        ).pack(anchor="w")

        tk.Label(
            header,
            text="Enter the vehicle and owner details, then choose a parking slot.",
            bg=BG, fg=MUTED, font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(3, 0))

        # Fixed footer first so it always stays visible.
        footer = tk.Frame(win, bg="#111827", height=72, padx=18, pady=12)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        scroll_area = tk.Frame(win, bg=BG)
        scroll_area.pack(fill="both", expand=True, padx=18, pady=(4, 0))

        canvas = tk.Canvas(scroll_area, bg=BG, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(scroll_area, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        form = tk.Frame(canvas, bg=BG)
        form_window = canvas.create_window((0, 0), window=form, anchor="nw")

        def update_scroll_region(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(form_window, width=canvas.winfo_width())

        form.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", update_scroll_region)

        def mousewheel(event):
            if event.delta:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<MouseWheel>", mousewheel)
        form.bind("<MouseWheel>", mousewheel)

        def bind_scroll_recursive(widget):
            widget.bind("<MouseWheel>", mousewheel, add="+")
            for child in widget.winfo_children():
                bind_scroll_recursive(child)

        fields = [
            ("Vehicle Number", ""),
            ("Vehicle Type", "Car"),
            ("Owner Name", ""),
            ("Owner Contact", ""),
            ("Number of Persons", "1"),
            ("Elder Care Needed", "No"),
            ("Parking Slot", "")
        ]

        variables = []
        slot_widget = None

        for label, default in fields:
            tk.Label(
                form, text=label, bg=BG, fg="#cbd5e1",
                font=("Segoe UI", 9, "bold")
            ).pack(anchor="w", pady=(12, 4))

            var = tk.StringVar(value=default)
            variables.append(var)

            if label == "Vehicle Type":
                widget = self.make_combo(form, var, list(VEHICLE_RATES.keys()), 35)
            elif label == "Elder Care Needed":
                widget = self.make_combo(form, var, ["No", "Yes"], 35)
            elif label == "Parking Slot":
                widget = self.make_combo(form, var, [], 35)
                slot_widget = widget
            else:
                widget = self.make_entry(form, var, 35)

            widget.pack(fill="x", ipady=5)

        def refresh_vehicle_slots(*_):
            vehicle_type = variables[1].get()

            rows = self.db.execute(
                """SELECT slot_no,status,vehicle_no
                   FROM slots WHERE slot_type=? ORDER BY slot_no""",
                (vehicle_type,)
            ).fetchall()

            values = []
            for r in rows:
                label = r["slot_no"]
                if r["status"] != "Available":
                    label += f" — {r['status'].upper()}"
                values.append(label)

            slot_widget["values"] = values

            if row:
                for value in values:
                    if value.split(" — ")[0] == current_slot:
                        variables[6].set(value)
                        break
            elif values:
                available = [v for v in values if " — " not in v]
                variables[6].set(available[0] if available else "")

        if row and db_vehicle:
            variables[0].set(db_vehicle["vehicle_no"])
            variables[1].set(db_vehicle["vehicle_type"])
            variables[2].set(db_vehicle["owner_name"])
            variables[3].set(db_vehicle["owner_contact"])
            variables[4].set(str(db_vehicle["persons"]))
            variables[5].set("Yes" if db_vehicle["elder_care"] else "No")
            variables[6].set(current_slot)

        variables[1].trace_add("write", refresh_vehicle_slots)
        refresh_vehicle_slots()

        def save():
            vehicle_no = self.normalize_vehicle(variables[0].get())
            vehicle_type = variables[1].get().strip()
            owner = variables[2].get().strip()
            contact = variables[3].get().strip()
            persons = variables[4].get().strip()
            elder_care = 1 if variables[5].get() == "Yes" else 0
            parking_slot = variables[6].get().split(" — ")[0].strip()

            if not vehicle_no or not owner or not vehicle_type:
                messagebox.showerror(
                    "Invalid Details",
                    "Please complete Vehicle Number, Vehicle Type and Owner Name.",
                    parent=win
                )
                return

            if not self.valid_phone(contact):
                messagebox.showerror(
                    "Invalid Contact",
                    "Owner contact must contain exactly 10 digits.",
                    parent=win
                )
                return

            if not persons.isdigit() or int(persons) < 1:
                messagebox.showerror(
                    "Invalid Persons",
                    "Number of persons must be at least 1.",
                    parent=win
                )
                return

            if parking_slot:
                slot_row = self.db.execute(
                    "SELECT slot_type,status,vehicle_no FROM slots WHERE slot_no=?",
                    (parking_slot,)
                ).fetchone()

                if not slot_row:
                    messagebox.showerror(
                        "Invalid Slot",
                        "The selected parking slot does not exist.",
                        parent=win
                    )
                    return

                if slot_row["slot_type"] != vehicle_type:
                    messagebox.showerror(
                        "Wrong Slot Type",
                        f"{parking_slot} is a {slot_row['slot_type']} slot, "
                        f"not a {vehicle_type} slot.",
                        parent=win
                    )
                    return

                own_slot = (
                    (row and current_slot == parking_slot)
                    or slot_row["vehicle_no"] == vehicle_no
                )
                if slot_row["status"] != "Available" and not own_slot:
                    messagebox.showerror(
                        "Slot Unavailable",
                        f"{parking_slot} is currently {slot_row['status'].upper()}.",
                        parent=win
                    )
                    return

            try:
                duplicate = self.db.execute(
                    "SELECT id FROM vehicles WHERE vehicle_no=? AND id<>?",
                    (vehicle_no, row[0] if row else -1)
                ).fetchone()
                if duplicate:
                    messagebox.showerror(
                        "Vehicle Already Registered",
                        f"Vehicle {vehicle_no} is already registered.\n\n"
                        "The same vehicle cannot be registered again.",
                        parent=win
                    )
                    return

                if row:
                    self.db.execute(
                        """UPDATE vehicles
                           SET vehicle_no=?,vehicle_type=?,owner_name=?,
                               owner_contact=?,persons=?,elder_care=?,parking_slot=?
                           WHERE id=?""",
                        (vehicle_no, vehicle_type, owner, contact,
                         int(persons), elder_care, parking_slot or None, row[0])
                    )
                else:
                    self.db.execute(
                        """INSERT INTO vehicles
                           (vehicle_no,vehicle_type,owner_name,
                            owner_contact,persons,elder_care,parking_slot)
                           VALUES(?,?,?,?,?,?,?)""",
                        (vehicle_no, vehicle_type, owner, contact,
                         int(persons), elder_care, parking_slot or None)
                    )

                self.db.execute(
                    "INSERT OR IGNORE INTO owners(name,contact) VALUES(?,?)",
                    (owner, contact)
                )

                self.db.commit()

                messagebox.showinfo("Success", "Vehicle saved successfully.", parent=win)
                win.destroy()

                if refresh:
                    refresh()

            except sqlite3.IntegrityError:
                messagebox.showerror(
                    "Duplicate",
                    "This vehicle number already exists.",
                    parent=win
                )

        self.action_button(
            footer, "💾  SAVE VEHICLE", save, GREEN
        ).pack(side="right", fill="x", expand=True)

        self.action_button(
            footer, "Cancel", win.destroy, "#475569"
        ).pack(side="left", padx=(0, 10))

        bind_scroll_recursive(form)
        canvas.yview_moveto(0)

    def edit_vehicle(self, tree, refresh):
        selected = tree.selection()
        if not selected:
            return
        values = tree.item(selected[0], "values")
        self.vehicle_form(refresh, values)

    def delete_vehicle(self, tree, refresh):
        selected = tree.selection()
        if not selected:
            messagebox.showwarning("Select Vehicle", "Select a vehicle first.")
            return

        values = tree.item(selected[0], "values")
        vehicle_no = values[1]

        active = self.db.execute(
            "SELECT 1 FROM parking_sessions WHERE vehicle_no=? AND status='Active'",
            (vehicle_no,)
        ).fetchone()

        if active:
            messagebox.showerror(
                "Cannot Delete",
                "This vehicle is currently parked. Complete its exit first."
            )
            return

        if messagebox.askyesno(
            "Delete Vehicle",
            f"Delete vehicle {vehicle_no} from the vehicle master record?\n"
            "Past parking history will be retained."
        ):
            self.db.execute("DELETE FROM vehicles WHERE id=?", (values[0],))
            self.db.commit()
            refresh()

    # ---------------- SLOT LOCATION MAP ----------------

    def show_slot_location(self):
        """Visual parking-layout map so users can understand slot positions."""
        self.current_page_method = self.show_slot_location
        self.clear_content()
        self.page_title(
            "Slot Location Map",
            "Tap any slot to see its position, availability and assigned vehicle"
        )

        top = tk.Frame(self.content, bg=BG)
        top.pack(fill="x", padx=28, pady=(0, 10))

        self.action_button(top, "🔄 Refresh Map", self.show_slot_location).pack(side="left")
        self.action_button(top, "🅿 Open Parking", self.show_parking, BLUE).pack(side="left", padx=8)
        self.action_button(top, "🧭 Route from Gate", self.show_route_guide, GREEN).pack(side="left", padx=8)

        info = tk.Frame(self.content, bg=PANEL)
        info.pack(fill="x", padx=28, pady=(0, 12))
        tk.Label(
            info,
            text=(
                "Use this map before choosing a default slot. "
                "Slots are arranged visually as left corner → middle → right corner. "
                "The entrance and driving aisle are marked so users can choose a convenient area."
            ),
            bg=PANEL, fg="#cbd5e1", font=("Segoe UI", 10),
            justify="left", wraplength=1050, padx=16, pady=12
        ).pack(fill="x")

        legend = tk.Frame(self.content, bg=BG)
        legend.pack(fill="x", padx=28, pady=(0, 8))
        for label, color in [
            ("AVAILABLE", "#16a34a"),
            ("RESERVED", "#d97706"),
            ("OCCUPIED", "#dc2626")
        ]:
            tk.Label(
                legend, text=f"● {label}", bg=BG, fg=color,
                font=("Segoe UI", 9, "bold")
            ).pack(side="left", padx=(0, 22))

        # The detail panel is packed at the bottom FIRST so it never gets
        # pushed off-screen by the expanding map below.
        detail_panel = tk.Frame(self.content, bg=PANEL)
        detail_panel.pack(fill="x", side="bottom", padx=28, pady=(0, 18))
        detail_label = tk.Label(
            detail_panel,
            text="Tap a slot on the map to see its exact position and current details.",
            bg=PANEL, fg="#93c5fd", font=("Segoe UI", 10, "bold"),
            justify="left", anchor="w", padx=16, pady=12
        )
        detail_label.pack(fill="x")

        holder = tk.Frame(self.content, bg=BG)
        holder.pack(fill="both", expand=True, padx=28, pady=(0, 10))

        canvas = tk.Canvas(holder, bg="#0b1220", highlightthickness=1,
                           highlightbackground="#334155")
        scrollbar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        map_frame = tk.Frame(canvas, bg="#0b1220")
        window_id = canvas.create_window((0, 0), window=map_frame, anchor="nw")

        def resize_map(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            if canvas.winfo_width() > 20:
                canvas.itemconfigure(window_id, width=max(canvas.winfo_width(), 900))

        map_frame.bind("<Configure>", resize_map)
        canvas.bind("<Configure>", resize_map)

        def wheel(event):
            if event.delta:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<MouseWheel>", wheel)
        map_frame.bind("<MouseWheel>", wheel)

        def slot_color(status):
            return {
                "Available": "#166534",
                "Reserved": "#b45309",
                "Occupied": "#991b1b"
            }.get(status, "#334155")

        def slot_detail(slot_no):
            row = self.db.execute(
                """SELECT s.*, v.owner_name, v.vehicle_type
                   FROM slots s
                   LEFT JOIN vehicles v ON v.vehicle_no=s.vehicle_no
                   WHERE s.slot_no=?""",
                (slot_no,)
            ).fetchone()

            if not row:
                detail_label.config(text=f"SLOT {slot_no}\nThis slot is not in the database yet.")
                return

            detail = (
                f"SLOT {slot_no}   |   Position: {self.slot_position_text(slot_no)}\n"
                f"Status: {row['status'].upper()}   |   Vehicle: {row['vehicle_no'] or '—'}   |   "
                f"Owner: {row['owner_name'] or '—'}   |   "
                f"Type: {row['vehicle_type'] or row['slot_type'] or '—'}"
            )
            detail_label.config(text=detail)

        def draw_slot(parent, slot_no, row_index, col_index):
            row = self.db.execute(
                "SELECT status, vehicle_no FROM slots WHERE slot_no=?",
                (slot_no,)
            ).fetchone()
            status = row["status"] if row else "Available"
            vehicle = row["vehicle_no"] if row else None

            card = tk.Frame(
                parent, bg=slot_color(status), width=105, height=70,
                highlightthickness=2, highlightbackground="#475569"
            )
            card.grid(row=row_index, column=col_index, padx=7, pady=7, sticky="nsew")
            card.grid_propagate(False)

            tk.Label(
                card, text=slot_no, bg=slot_color(status), fg="white",
                font=("Segoe UI", 11, "bold")
            ).pack(pady=(10, 0))
            tk.Label(
                card,
                text=status.upper() if not vehicle else "PARKED"
                if status == "Occupied" else status.upper(),
                bg=slot_color(status), fg="#e2e8f0",
                font=("Segoe UI", 7, "bold")
            ).pack(pady=(3, 0))

            def click(_event=None, sn=slot_no):
                slot_detail(sn)

            for widget in (card, *card.winfo_children()):
                widget.bind("<Button-1>", click)
                widget.bind("<MouseWheel>", wheel)
                widget.configure(cursor="hand2")

        for prefix, title in [("C", "CAR PARKING"), ("B", "BIKE PARKING"), ("V", "VAN PARKING")]:
            section = tk.Frame(map_frame, bg="#0b1220")
            section.pack(fill="x", padx=18, pady=(18, 4))

            tk.Label(
                section, text=title, bg="#0b1220", fg="#e2e8f0",
                font=("Segoe UI", 12, "bold")
            ).pack(anchor="w", pady=(0, 3))
            tk.Label(
                section,
                text="LEFT CORNER              CENTER / EASY ACCESS              RIGHT CORNER",
                bg="#0b1220", fg="#64748b", font=("Segoe UI", 8, "bold")
            ).pack(anchor="w", pady=(0, 5))

            grid = tk.Frame(section, bg="#0b1220")
            grid.pack(fill="x")
            for c in range(10):
                grid.columnconfigure(c, weight=1)

            for i in range(1, 21):
                row_idx = 0 if i <= 10 else 2
                col_idx = (i - 1) % 10
                draw_slot(grid, f"{prefix}-{i:02d}", row_idx, col_idx)

            tk.Label(
                grid, text="DRIVING AISLE / WALKWAY",
                bg="#1e293b", fg="#94a3b8", font=("Segoe UI", 8, "bold"), height=1
            ).grid(row=1, column=0, columnspan=10, sticky="ew", pady=2)

        entrance = tk.Frame(map_frame, bg="#0b1220")
        entrance.pack(fill="x", padx=18, pady=(18, 24))
        tk.Label(
            entrance, text="⬇  MAIN ENTRANCE / ENTRY & EXIT  ⬇",
            bg="#1d4ed8", fg="white", font=("Segoe UI", 11, "bold"), pady=10
        ).pack(fill="x")

    def slot_position_text(self, slot_no):
        """Return a simple human-readable location description for a slot."""
        try:
            prefix, number_text = slot_no.split("-")
            number = int(number_text)
        except (ValueError, AttributeError):
            return "Parking area"

        if number <= 3:
            side = "left corner"
        elif number >= 18:
            side = "right corner"
        else:
            side = "middle area"

        type_name = {"C": "car", "B": "bike", "V": "van"}.get(prefix, "parking")
        return f"{side} of the {type_name} parking area"

    # ---------------- PARKING ----------------

    def show_parking(self):
        self.current_page_method = self.show_parking
        self.clear_content()
        self.page_title(
            "Parking Management",
            "Every slot shows live availability, vehicle, owner and entry/exit details"
        )

        bar = tk.Frame(self.content, bg=BG)
        bar.pack(fill="x", padx=28)

        self.action_button(bar, "🚪 Record Entry", self.entry_form, GREEN).pack(side="left")
        self.action_button(bar, "🚗 Record Exit", self.exit_form, RED).pack(side="left", padx=8)
        self.action_button(bar, "🔄 Refresh", self.show_parking).pack(side="left")

        legend = tk.Frame(self.content, bg=BG)
        legend.pack(fill="x", padx=28, pady=(12, 0))
        for text, color in [
            ("🟢 AVAILABLE", "#22c55e"),
            ("🟡 RESERVED", "#f59e0b"),
            ("🔴 OCCUPIED / UNAVAILABLE", "#ef4444")
        ]:
            tk.Label(
                legend, text=text, bg=BG, fg=color,
                font=("Segoe UI", 9, "bold")
            ).pack(side="left", padx=(0, 22))

        tree = self.make_table(
            self.content,
            (
                "Slot", "Type", "Status", "Vehicle No",
                "Owner Name", "Entry Date", "Entry Time",
                "Exit Date", "Exit Time"
            ),
            [75, 75, 145, 130, 170, 105, 110, 105, 110]
        )

        rows = self.db.execute(
            """SELECT
                   s.slot_no,
                   s.slot_type,
                   s.status,
                   COALESCE(s.vehicle_no,'') AS vehicle_no,
                   COALESCE(v.owner_name,'') AS owner_name,
                   ps.entry_date,
                   ps.entry_time,
                   ps.exit_date,
                   ps.exit_time
               FROM slots s
               LEFT JOIN vehicles v
                 ON v.vehicle_no = s.vehicle_no
               LEFT JOIN parking_sessions ps
                 ON ps.vehicle_no = s.vehicle_no
                AND ps.status = 'Active'
               ORDER BY
                   CASE s.status
                       WHEN 'Occupied' THEN 1
                       WHEN 'Reserved' THEN 2
                       ELSE 3
                   END,
                   s.slot_no"""
        ).fetchall()

        for row in rows:
            status = row["status"]
            display_status = (
                "🟢 AVAILABLE" if status == "Available"
                else "🟡 RESERVED" if status == "Reserved"
                else "🔴 OCCUPIED / UNAVAILABLE"
            )

            tree.insert(
                "", "end",
                values=(
                    row["slot_no"],
                    row["slot_type"],
                    display_status,
                    row["vehicle_no"] or "—",
                    row["owner_name"] or "—",
                    self.display_date(row["entry_date"]) or "—",
                    row["entry_time"] or "—",
                    self.display_date(row["exit_date"]) or "—",
                    row["exit_time"] or "—"
                )
            )

        tk.Label(
            self.content,
            text=(
                "A slot becomes RESERVED when a booking is created, "
                "OCCUPIED when the vehicle actually enters, and AVAILABLE "
                "again after the vehicle exits. Past entry/exit records remain "
                "in Particular History."
            ),
            bg=BG, fg=MUTED, wraplength=1050, justify="left"
        ).pack(anchor="w", padx=28, pady=(2, 12))

    def entry_form(self):
        win = tk.Toplevel(self.root)
        win.title("Vehicle Entry")
        win.geometry("500x560")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.grab_set()

        tk.Label(
            win, text="Record Vehicle Entry", bg=BG, fg=TEXT,
            font=("Segoe UI", 18, "bold")
        ).pack(anchor="w", padx=28, pady=(22, 5))

        tk.Label(
            win,
            text="Select the registered vehicle. Its assigned slot is loaded automatically; no slot selection is needed here.",
            bg=BG, fg=MUTED, wraplength=420, justify="left"
        ).pack(anchor="w", padx=28, pady=(0, 18))

        vehicle_var = tk.StringVar()
        elder_var = tk.StringVar(value="No")
        form = tk.Frame(win, bg=BG)
        form.pack(fill="x", padx=28)

        tk.Label(form, text="Vehicle Number", bg=BG, fg="#cbd5e1").pack(
            anchor="w", pady=(5, 4)
        )
        vehicle_combo = self.make_combo(form, vehicle_var, [], 35)
        vehicle_combo.pack(fill="x")

        assigned_info = tk.Label(
            form, text="Choose a registered vehicle to see its assigned slot.",
            bg=PANEL, fg="#60a5fa", padx=14, pady=14, justify="left"
        )
        assigned_info.pack(fill="x", pady=18)

        rows = self.db.execute(
            "SELECT vehicle_no FROM vehicles ORDER BY vehicle_no"
        ).fetchall()
        vehicle_combo["values"] = [r["vehicle_no"] for r in rows]

        def refresh_info(*_):
            vehicle = self.normalize_vehicle(vehicle_var.get())
            row = self.db.execute(
                "SELECT * FROM vehicles WHERE vehicle_no=?", (vehicle,)
            ).fetchone()

            if not row:
                assigned_info.config(
                    text="Choose a registered vehicle to see its assigned slot."
                )
                return

            slot = row["parking_slot"] or "NOT ASSIGNED"
            slot_row = self.db.execute(
                "SELECT status FROM slots WHERE slot_no=?", (slot,)
            ).fetchone() if row["parking_slot"] else None
            slot_status = slot_row["status"] if slot_row else "—"

            elder_var.set("Yes" if row["elder_care"] else "No")

            assigned_info.config(
                text=(
                    f"Vehicle: {row['vehicle_no']}\n"
                    f"Owner: {row['owner_name']}\n"
                    f"Vehicle Type: {row['vehicle_type']}\n"
                    f"Assigned Slot: {slot}\n"
                    f"Slot Status: {slot_status}"
                )
            )

        vehicle_var.trace_add("write", refresh_info)

        elder_box = tk.Frame(form, bg=PANEL, padx=12, pady=10)
        elder_box.pack(fill="x", pady=(0, 8))
        tk.Label(
            elder_box, text="Elder Care Needed?", bg=PANEL, fg=TEXT,
            font=("Segoe UI", 10, "bold")
        ).pack(side="left")
        elder_combo = self.make_combo(elder_box, elder_var, ["No", "Yes"], 10)
        elder_combo.pack(side="right")

        elder_alert = tk.Label(
            form, text="", bg=BG, fg=AMBER, font=("Segoe UI", 10, "bold"),
            wraplength=420, justify="left"
        )
        elder_alert.pack(fill="x")

        def elder_changed(*_):
            if elder_var.get() == "Yes":
                elder_alert.config(
                    text="🧑‍🦽 CARETAKER ALERT: An elder is travelling with this vehicle. "
                         "Parking staff should provide assistance at entry and guide the "
                         "family safely to the assigned slot."
                )
            else:
                elder_alert.config(text="")

        elder_var.trace_add("write", elder_changed)

        def confirm():
            vehicle = self.normalize_vehicle(vehicle_var.get())
            if not vehicle:
                messagebox.showerror(
                    "Select Vehicle", "Please select a registered vehicle.", parent=win
                )
                return

            vehicle_row = self.db.execute(
                "SELECT * FROM vehicles WHERE vehicle_no=?", (vehicle,)
            ).fetchone()

            if not vehicle_row:
                messagebox.showerror(
                    "Vehicle Not Registered",
                    "Register this vehicle and assign a slot before entry.",
                    parent=win
                )
                return

            slot = vehicle_row["parking_slot"]
            if not slot:
                messagebox.showerror(
                    "No Assigned Slot",
                    "This vehicle has no assigned slot. Edit the vehicle registration and choose a slot first.",
                    parent=win
                )
                return

            active = self.db.execute(
                "SELECT 1 FROM parking_sessions WHERE vehicle_no=? AND status='Active'",
                (vehicle,)
            ).fetchone()
            if active:
                messagebox.showerror(
                    "Already Parked",
                    "This vehicle already has an active parking session.",
                    parent=win
                )
                return

            slot_row = self.db.execute(
                "SELECT * FROM slots WHERE slot_no=?", (slot,)
            ).fetchone()
            if not slot_row:
                messagebox.showerror("Invalid Slot", "The assigned slot no longer exists.", parent=win)
                return

            if slot_row["status"] not in ("Available", "Reserved"):
                messagebox.showerror(
                    "Slot Unavailable",
                    f"Assigned slot {slot} is currently {slot_row['status'].upper()}. "
                    "Please choose another slot in vehicle registration.",
                    parent=win
                )
                return

            if slot_row["vehicle_no"] and slot_row["vehicle_no"] != vehicle:
                messagebox.showerror(
                    "Slot Reserved",
                    f"Slot {slot} is reserved for vehicle {slot_row['vehicle_no']}. "
                    "Please choose another slot in vehicle registration.",
                    parent=win
                )
                return

            now = self.now()
            self.db.execute(
                "UPDATE vehicles SET elder_care=? WHERE vehicle_no=?",
                (1 if elder_var.get() == "Yes" else 0, vehicle)
            )
            parking_id = self.make_id("P")
            booking_id = slot_row["booking_id"]

            self.db.execute(
                """INSERT INTO parking_sessions
                   (parking_id,vehicle_no,slot_no,entry_date,entry_time,entry_datetime,
                    status,booking_id)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    parking_id, vehicle, slot,
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%H:%M:%S"),
                    now.strftime("%Y-%m-%d %H:%M:%S"),
                    "Active", booking_id
                )
            )

            # A pre-booked vehicle that arrives in time must NOT later be
            # auto-marked as No-Show, so mark the booking as checked in.
            if booking_id:
                self.db.execute(
                    """UPDATE bookings SET status='Checked-In', notes=?
                       WHERE booking_id=? AND status IN ('Reserved','Confirmed')""",
                    ("Vehicle checked in on time.", booking_id)
                )

            self.db.execute(
                "UPDATE slots SET status='Occupied',vehicle_no=? WHERE slot_no=?",
                (vehicle, slot)
            )
            self.db.commit()

            messagebox.showinfo(
                "Vehicle Entry Recorded",
                f"Vehicle {vehicle} entered successfully.\n\n"
                f"Assigned Slot: {slot}\n"
                f"Entry: {now.strftime('%d-%m-%Y %I:%M:%S %p')}\n"
                + ("\n🧑‍🦽 CARETAKER ALERT: Elder assistance requested." if elder_var.get() == "Yes" else ""),
                parent=win
            )
            win.destroy()
            self.show_parking()

        self.action_button(
            form, "✅ Confirm Vehicle Entry", confirm, GREEN
        ).pack(fill="x", pady=10)

        vehicle_combo.bind("<<ComboboxSelected>>", refresh_info)
        if rows:
            vehicle_var.set(rows[0]["vehicle_no"])
            refresh_info()

    def exit_form(self):
        win = tk.Toplevel(self.root)
        win.title("Vehicle Exit & Payment")
        screen_h = self.root.winfo_screenheight()
        screen_w = self.root.winfo_screenwidth()
        win_h = min(720, screen_h - 90)
        win.geometry(f"1040x{win_h}+{max(0, (screen_w - 1040) // 2)}+10")
        win.configure(bg=BG)
        win.resizable(False, True)
        win.grab_set()

        tk.Label(
            win, text="Record Vehicle Exit", bg=BG, fg=TEXT,
            font=("Segoe UI", 18, "bold")
        ).pack(anchor="w", padx=28, pady=(14, 2))

        vehicle_var = tk.StringVar()
        payment_var = tk.StringVar(value="UPI")
        calc = {"value": 0.0, "session": None, "exit_dt": None,
                "minutes": 0, "entry_dt": None, "token": None, "done": False}

        # Fixed footer: the Confirm Payment button always stays visible.
        footer = tk.Frame(win, bg=BG)
        footer.pack(side="bottom", fill="x", padx=28, pady=10)

        qr_frame = tk.Frame(win, bg=PANEL, width=400)
        qr_frame.pack(side="right", fill="y", padx=(0, 28), pady=(8, 4))
        qr_frame.pack_propagate(False)

        form = tk.Frame(win, bg=BG)
        form.pack(fill="both", expand=True, padx=(28, 12))

        tk.Label(form, text="Vehicle Number", bg=BG, fg="#cbd5e1").pack(
            anchor="w", pady=(6, 4)
        )

        entry = self.make_entry(form, vehicle_var)
        entry.pack(fill="x", ipady=5)

        details = tk.Label(
            form, text="Enter a parked vehicle number and click Calculate Fee.",
            bg=PANEL, fg="#93c5fd", justify="left", anchor="w",
            padx=14, pady=10
        )
        details.pack(fill="x", pady=10)

        tk.Label(form, text="Payment Method", bg=BG, fg="#cbd5e1").pack(
            anchor="w", pady=(2, 4)
        )

        payment_combo = self.make_combo(
            form, payment_var, ["Cash", "UPI", "Debit/Credit Card", "Other"], 30
        )
        payment_combo.pack(fill="x")

        upi_default = "" if UPI_ID == "yourupi@upi" else UPI_ID
        upi_var = tk.StringVar(value=upi_default)

        upi_frame = tk.Frame(form, bg=PANEL)
        tk.Label(
            upi_frame, text="UPI ID (money is received here)",
            bg=PANEL, fg=TEXT, font=("Segoe UI", 9, "bold")
        ).pack(anchor="w", padx=12, pady=(8, 3))

        upi_entry = self.make_entry(upi_frame, upi_var)
        upi_entry.pack(fill="x", padx=12, ipady=5)

        tk.Label(
            upi_frame,
            text="Customer scans the QR → a payment page opens in the phone browser → "
                 "taps Pay (UPI app opens) → taps \"I have paid\" → you confirm below → receipt.",
            bg=PANEL, fg=MUTED, font=("Segoe UI", 8), wraplength=500,
            justify="left"
        ).pack(anchor="w", padx=12, pady=(4, 9))

        tk.Label(
            qr_frame, text="SCAN TO PAY", bg=PANEL, fg="#60a5fa",
            font=("Segoe UI", 14, "bold")
        ).pack(pady=(14, 6))
        qr_label = tk.Label(qr_frame, bg=PANEL)
        qr_label.pack(pady=4)
        qr_info = tk.Label(
            qr_frame, text="", bg=PANEL, fg=MUTED,
            font=("Segoe UI", 9), justify="center", wraplength=360
        )
        qr_info.pack(pady=6, padx=12)
        cust_status = tk.Label(
            qr_frame, text="", bg=PANEL, fg="#93c5fd",
            font=("Segoe UI", 9, "bold"), justify="center", wraplength=360
        )
        cust_status.pack(pady=6, padx=12)

        def install_qr():
            """Install the QR packages from inside the program."""
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "qrcode[pil]", "pillow"],
                    capture_output=True, text=True, stdin=subprocess.DEVNULL
                )
                if result.returncode == 0:
                    messagebox.showinfo(
                        "Installed",
                        "QR package installed.\n\nClose this program and run it again "
                        "(Run > Run Module).",
                        parent=win
                    )
                else:
                    messagebox.showerror(
                        "Install failed",
                        "Could not install automatically. Open Command Prompt and run:\n"
                        'pip install "qrcode[pil]" pillow\n\n' + result.stderr[-400:],
                        parent=win
                    )
            except Exception as exc:
                messagebox.showerror("Install failed", str(exc), parent=win)

        install_btn = self.action_button(
            qr_frame, "⬇ Install QR package now", install_qr, AMBER
        )

        def simulate_payment():
            fn = complete_holder.get("fn")
            if calc["session"] is None or fn is None:
                messagebox.showinfo(
                    "Demo", "Calculate the fee first (enter the vehicle number).",
                    parent=win
                )
                return
            fn()

        if DEMO_MODE:
            self.action_button(
                qr_frame, "▶ Simulate Payment Success (Demo)",
                simulate_payment, GREEN
            ).pack(side="bottom", fill="x", padx=14, pady=14)

        def make_pay_qr():
            """Draw the QR code (right-hand panel) that opens the payment page."""
            qr_label.config(image="", text="")
            qr_label.image = None
            install_btn.pack_forget()

            if payment_var.get() != "UPI":
                qr_info.config(text="Choose UPI as the payment method to get a QR code.")
                cust_status.config(text="")
                return

            if calc["session"] is None:
                qr_info.config(
                    text="Enter the vehicle number and click Calculate Fee.\n"
                         "The QR code will appear here."
                )
                cust_status.config(text="")
                return

            if not QR_AVAILABLE:
                qr_info.config(
                    text="The QR code package is not installed.\n"
                         "Click the button below, then close and restart this program."
                )
                install_btn.pack(pady=8)
                return

            if self.pay_server is None and not DEMO_QR_URL.strip():
                qr_info.config(
                    text=f"The payment page server could not start (port {PAY_PORT} is busy).\n"
                         "Close other copies of this program and try again."
                )
                return

            payee = upi_var.get().strip()
            with PAYMENTS_LOCK:
                payment = PAYMENTS.get(calc["token"])
                if payment:
                    payment["upi"] = payee

            url = DEMO_QR_URL.strip() or self.pay_url(calc["token"])

            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=8,
                border=3
            )
            qr.add_data(url)
            qr.make(fit=True)

            img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
            img.thumbnail((270, 270))
            photo = ImageTk.PhotoImage(img)
            qr_label.config(image=photo)
            qr_label.image = photo

            warning = "" if (DEMO_MODE or re.match(UPI_PATTERN, payee)) else (
                "\n\n⚠ Enter your UPI ID on the left, otherwise the customer's "
                "Pay button will not work."
            )
            qr_info.config(
                text=(
                    f"Amount: ₹{calc['value']:.2f}\n"
                    "Scan with the phone's CAMERA or Google Lens.\n"
                    f"{url}\n"
                    "Phone must be on the same Wi-Fi as this computer."
                    + warning
                )
            )

        def on_payment_change(event=None):
            if payment_var.get() == "UPI":
                if not DEMO_MODE:
                    upi_frame.pack(fill="x", pady=(8, 0), after=payment_combo)
                if calc["session"] is None and vehicle_var.get().strip():
                    calculate(silent=True)
            else:
                upi_frame.pack_forget()
            make_pay_qr()

        payment_combo.bind("<<ComboboxSelected>>", on_payment_change)

        def on_upi_change(*_):
            if payment_var.get() == "UPI" and calc["session"] is not None:
                make_pay_qr()

        upi_var.trace_add("write", on_upi_change)
        on_payment_change()

        def poll_customer():
            """Show what the customer is doing on their phone."""
            try:
                if not win.winfo_exists():
                    return
                token = calc["token"]
                if token and payment_var.get() == "UPI":
                    with PAYMENTS_LOCK:
                        status = (PAYMENTS.get(token) or {}).get("status")
                    fn = complete_holder.get("fn")
                    if DEMO_MODE and status == "claimed" and fn and not calc["done"]:
                        fn()          # dummy payment: complete the exit automatically
                        return
                    if status == "claimed":
                        cust_status.config(
                            text="📱 Customer tapped \"I have paid\". Check your UPI app for the "
                                 "money, then press Confirm below.",
                            fg=AMBER
                        )
                    elif status == "pending":
                        cust_status.config(
                            text="Waiting for the customer to scan and pay...",
                            fg="#93c5fd"
                        )
                win.after(1500, poll_customer)
            except tk.TclError:
                pass

        poll_customer()

        complete_holder = {"button": None, "fn": None}

        def calculate(silent=False):
            vehicle = self.normalize_vehicle(vehicle_var.get())

            session = self.db.execute(
                """SELECT * FROM parking_sessions
                   WHERE vehicle_no=? AND status='Active'
                   ORDER BY id DESC LIMIT 1""",
                (vehicle,)
            ).fetchone()

            if not session:
                if not silent:
                    messagebox.showerror(
                        "Not Found",
                        "No active parking session was found for this vehicle.",
                        parent=win
                    )
                return

            entry_dt = datetime.strptime(
                session["entry_datetime"], "%Y-%m-%d %H:%M:%S"
            )
            exit_dt = self.now()

            minutes = max(1, int((exit_dt - entry_dt).total_seconds() / 60))

            vehicle_row = self.db.execute(
                "SELECT vehicle_type FROM vehicles WHERE vehicle_no=?",
                (vehicle,)
            ).fetchone()

            vehicle_type = vehicle_row["vehicle_type"] if vehicle_row else "Other"
            billed_hours = self.hours_for_fee(minutes)
            fee = billed_hours * VEHICLE_RATES.get(vehicle_type, 50)

            token = secrets.token_urlsafe(6)
            with PAYMENTS_LOCK:
                PAYMENTS[token] = {
                    "status": "pending",
                    "vehicle": vehicle,
                    "slot": session["slot_no"],
                    "fee": float(fee),
                    "minutes": minutes,
                    "entry": entry_dt.strftime("%d-%m-%Y %I:%M:%S %p"),
                    "exit": exit_dt.strftime("%d-%m-%Y %I:%M:%S %p"),
                    "upi": upi_var.get().strip(),
                }

            calc.update({
                "value": fee,
                "session": session,
                "exit_dt": exit_dt,
                "minutes": minutes,
                "entry_dt": entry_dt,
                "token": token,
                "done": False
            })

            details.config(
                text=(
                    f"Parking ID: {session['parking_id']}      Slot: {session['slot_no']}\n"
                    f"ENTER: {entry_dt.strftime('%d-%m-%Y  %I:%M:%S %p')}\n"
                    f"EXIT:  {exit_dt.strftime('%d-%m-%Y  %I:%M:%S %p')}\n"
                    f"Duration: {minutes} minutes      Billed Hours: {billed_hours}\n"
                    f"Parking Fee: ₹{fee:.2f}"
                )
            )

            make_pay_qr()

            if complete_holder["button"] is not None:
                complete_holder["button"].destroy()

            def complete_payment():
                method = payment_var.get()
                payee = upi_var.get().strip() if method == "UPI" else ""

                if method == "UPI" and not DEMO_MODE:
                    if not re.match(UPI_PATTERN, payee):
                        messagebox.showerror(
                            "Invalid UPI ID",
                            "Enter a valid UPI ID before confirming the payment.",
                            parent=win
                        )
                        upi_entry.focus_set()
                        return

                    confirm = messagebox.askyesno(
                        "Confirm UPI Payment",
                        f"Have you received ₹{fee:.2f} in your UPI app?\n\n"
                        "Check your UPI app / bank SMS before confirming.\n"
                        "This program cannot verify the bank transaction by itself.",
                        parent=win
                    )
                    if not confirm:
                        return

                if calc["done"]:
                    return
                calc["done"] = True
                if DEMO_MODE and method == "UPI":
                    method = "UPI (Demo)"
                    payee = ""

                transaction_id = self.make_id("TXN")

                self.db.execute(
                    """UPDATE parking_sessions
                       SET exit_date=?,exit_time=?,exit_datetime=?,
                           duration_minutes=?,fee=?,
                           payment_method=?,payment_status='Paid',
                           transaction_id=?,status='Completed'
                       WHERE id=?""",
                    (
                        exit_dt.strftime("%Y-%m-%d"),
                        exit_dt.strftime("%H:%M:%S"),
                        exit_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        minutes, fee, method, transaction_id, session["id"]
                    )
                )

                self.db.execute(
                    """UPDATE slots
                       SET status='Available',vehicle_no=NULL,booking_id=NULL
                       WHERE slot_no=?""",
                    (session["slot_no"],)
                )

                if session["booking_id"]:
                    self.db.execute(
                        """UPDATE bookings SET status='Completed'
                           WHERE booking_id=? AND status='Checked-In'""",
                        (session["booking_id"],)
                    )

                self.db.commit()

                paid_at = self.now().strftime("%d-%m-%Y %I:%M:%S %p")
                entry_txt = entry_dt.strftime("%d-%m-%Y %I:%M:%S %p")
                exit_txt = exit_dt.strftime("%d-%m-%Y %I:%M:%S %p")

                receipt_text = (
                    "SMARTPARK • Parking Receipt\n"
                    "==============================\n"
                    f"Transaction ID : {transaction_id}\n"
                    f"Parking ID     : {session['parking_id']}\n"
                    f"Vehicle No     : {vehicle}\n"
                    f"Slot           : {session['slot_no']}\n"
                    f"Payment Method : {method}\n"
                    + (f"UPI ID         : {payee}\n" if payee else "")
                    + f"Entry          : {entry_txt}\n"
                    f"Exit           : {exit_txt}\n"
                    f"Duration       : {minutes} minutes\n"
                    f"Parking Fee    : ₹{fee:.2f}\n"
                    f"Paid On        : {paid_at}\n"
                    "Payment Status : PAID\n"
                    "==============================\n"
                    "Thank you for parking with us!\n"
                )

                receipt_data = {
                    "txn": transaction_id,
                    "parking_id": session["parking_id"],
                    "vehicle": vehicle,
                    "slot": session["slot_no"],
                    "method": method,
                    "upi": payee,
                    "entry": entry_txt,
                    "exit": exit_txt,
                    "minutes": minutes,
                    "fee": f"{fee:.2f}",
                    "paid_at": paid_at,
                }

                # Publish the receipt to the customer's phone page.
                token_now = calc["token"]
                if token_now:
                    served_html = build_receipt_html(
                        receipt_data,
                        download_url=f"/receipt/{token_now}?download=1"
                    )
                    with PAYMENTS_LOCK:
                        p = PAYMENTS.get(token_now)
                        if p:
                            p.update(status="paid", receipt=served_html, txn=transaction_id)

                txt_path = html_path = None
                try:
                    txt_path, html_path = self.save_receipt_files(
                        transaction_id, receipt_text, build_receipt_html(receipt_data)
                    )
                except OSError as exc:
                    messagebox.showwarning(
                        "Receipt Not Saved",
                        f"The payment was recorded, but the receipt file could not be saved:\n{exc}",
                        parent=win
                    )

                receipt = tk.Toplevel(win)
                receipt.title("Payment Receipt")
                receipt.geometry("470x640")
                receipt.configure(bg=BG)
                receipt.resizable(False, False)
                receipt.grab_set()

                tk.Label(
                    receipt, text="✓ PAYMENT RECEIPT",
                    bg=BG, fg=GREEN, font=("Segoe UI", 20, "bold")
                ).pack(pady=(22, 14))

                tk.Label(
                    receipt, text=receipt_text, bg=PANEL, fg=TEXT,
                    font=("Consolas", 10), justify="left",
                    padx=20, pady=18
                ).pack(fill="x", padx=24)

                if html_path:
                    tk.Label(
                        receipt, text=f"Saved in: {RECEIPT_DIR}", bg=BG, fg=MUTED,
                        font=("Segoe UI", 8), wraplength=420, justify="left"
                    ).pack(padx=24, pady=(8, 0), anchor="w")

                    btns = tk.Frame(receipt, bg=BG)
                    btns.pack(fill="x", padx=24, pady=(12, 0))
                    self.action_button(
                        btns, "📄 Open Receipt",
                        lambda: self.open_receipt(html_path)
                    ).pack(side="left", expand=True, fill="x", padx=(0, 5))
                    self.action_button(
                        btns, "🖨 Print / PDF",
                        lambda: self.open_receipt(html_path, True), AMBER
                    ).pack(side="left", expand=True, fill="x", padx=(5, 0))

                if token_now:
                    tk.Label(
                        receipt,
                        text="The receipt is also shown on the customer's phone.",
                        bg=BG, fg=MUTED, font=("Segoe UI", 9)
                    ).pack(pady=(10, 0))

                def done():
                    receipt.destroy()
                    win.destroy()
                    self.show_parking()

                self.action_button(
                    receipt, "Done", done, GREEN
                ).pack(fill="x", padx=24, pady=18)

            complete_holder["button"] = self.action_button(
                footer, "💳 Confirm Payment Received & Complete Exit",
                complete_payment, GREEN
            )
            complete_holder["button"].pack(fill="x")
            complete_holder["fn"] = complete_payment

        self.action_button(
            form, "🧮 Calculate Fee", calculate
        ).pack(fill="x", pady=(10, 5))

        entry.focus_set()

    # ---------------- ANIMATED ROUTE GUIDE ----------------

    def show_route_guide(self):
        """Show an aisle-safe route from the gate to a selected slot."""
        win = tk.Toplevel(self.root)
        win.title("Parking Route Guide")
        win.geometry("940x700")
        win.configure(bg=BG)
        win.grab_set()

        tk.Label(
            win, text="🧭 Smart Route from Main Gate",
            bg=BG, fg=TEXT, font=("Segoe UI", 20, "bold")
        ).pack(anchor="w", padx=24, pady=(20, 3))
        tk.Label(
            win,
            text="The vehicle follows the driving aisle, turns at a junction, then enters the destination slot — never diagonally through another parking space.",
            bg=BG, fg=MUTED, font=("Segoe UI", 10)
        ).pack(anchor="w", padx=26, pady=(0, 12))

        controls = tk.Frame(win, bg=PANEL, padx=14, pady=12)
        controls.pack(fill="x", padx=24)

        tk.Label(
            controls, text="Destination Slot", bg=PANEL, fg=TEXT,
            font=("Segoe UI", 10, "bold")
        ).pack(side="left")

        slot_var = tk.StringVar()
        slot_values = [
            r["slot_no"]
            for r in self.db.execute(
                "SELECT slot_no FROM slots ORDER BY slot_no"
            ).fetchall()
        ]
        combo = self.make_combo(controls, slot_var, slot_values, 18)
        combo.pack(side="left", padx=10)
        if slot_values:
            slot_var.set(slot_values[0])

        canvas = tk.Canvas(
            win, bg="#0b1220", highlightthickness=1,
            highlightbackground="#334155", height=500
        )
        canvas.pack(fill="both", expand=True, padx=24, pady=16)

        animation_job = {"id": None}

        def layout():
            w = max(canvas.winfo_width(), 860)
            left = 90
            right = w - 90
            col_step = (right - left) / 9

            row_specs = [
                ("V", 72, "VAN ROW 1"),
                ("V", 118, "VAN ROW 2"),
                ("C", 164, "CAR ROW 1"),
                ("C", 210, "CAR ROW 2"),
                ("B", 278, "BIKE ROW 1"),
                ("B", 324, "BIKE ROW 2"),
            ]

            rows = {}
            for prefix, y, title in row_specs:
                rows[(prefix, 0 if "1" in title else 1)] = {
                    "y": y, "aisle_y": y + 24, "title": title
                }

            slots = {}
            row_y = {"V": (72, 118), "C": (164, 210), "B": (278, 324)}
            for prefix, (y1, y2) in row_y.items():
                for i in range(1, 21):
                    x = left + ((i - 1) % 10) * col_step
                    actual_row = 0 if i <= 10 else 1
                    slot_y = y1 if actual_row == 0 else y2
                    slots[f"{prefix}-{i:02d}"] = (x, slot_y, actual_row)

            gate = (w * 0.50, 455)
            main_aisle_y = 390
            left_corridor_x = 48
            right_corridor_x = w - 48
            return w, slots, rows, gate, main_aisle_y, left_corridor_x, right_corridor_x

        def destination_info():
            w, slots, rows, gate, main_y, left_x, right_x = layout()
            slot = slot_var.get()
            if slot not in slots:
                return w, slots, rows, gate, main_y, left_x, right_x, None, None

            x, y, row_index = slots[slot]
            prefix = slot.split("-")[0]
            row = rows[(prefix, row_index)]
            return (
                w, slots, rows, gate, main_y, left_x, right_x,
                (x, y, row_index, prefix), row
            )

        def route_points():
            (w, slots, rows, gate, main_y, left_x, right_x, dest, row) = destination_info()

            if not dest:
                return [gate], None

            x, y, row_index, prefix = dest
            corridor_x = left_x if x < w / 2 else right_x
            row_aisle_y = row["aisle_y"]
            entry_y = y + 16

            points = [
                gate,
                (gate[0], main_y),
                (corridor_x, main_y),
                (corridor_x, row_aisle_y),
                (x, row_aisle_y),
                (x, entry_y),
            ]
            return points, dest

        def draw():
            if animation_job["id"] is not None:
                try:
                    win.after_cancel(animation_job["id"])
                except Exception:
                    pass
                animation_job["id"] = None

            canvas.delete("all")
            w, slots, rows, gate, main_y, left_x, right_x = layout()
            slot = slot_var.get()

            canvas.create_text(
                w / 2, 22, text="PARKING AREA • AISLE ROUTE",
                fill="#cbd5e1", font=("Segoe UI", 12, "bold")
            )

            canvas.create_rectangle(
                28, main_y - 22, w - 28, main_y + 22,
                fill="#1e293b", outline="#475569"
            )
            canvas.create_text(
                w / 2, main_y, text="MAIN DRIVING AISLE",
                fill="#94a3b8", font=("Segoe UI", 10, "bold")
            )

            canvas.create_line(left_x, 48, left_x, main_y, fill="#334155", width=12)
            canvas.create_line(right_x, 48, right_x, main_y, fill="#334155", width=12)
            canvas.create_text(
                left_x + 4, 48, text="ACCESS", fill="#64748b", anchor="sw",
                font=("Segoe UI", 7, "bold")
            )
            canvas.create_text(
                right_x - 4, 48, text="ACCESS", fill="#64748b", anchor="se",
                font=("Segoe UI", 7, "bold")
            )

            status_colors = {
                "Available": "#166534",
                "Reserved": "#b45309",
                "Occupied": "#991b1b"
            }

            for prefix, label, title_y in [
                ("V", "VAN", 60), ("C", "CAR", 151), ("B", "BIKE", 265)
            ]:
                canvas.create_text(
                    58, title_y, text=label, fill="#64748b", anchor="w",
                    font=("Segoe UI", 8, "bold")
                )

            for sn, (x, y, row_index) in slots.items():
                row_db = self.db.execute(
                    "SELECT status, vehicle_no FROM slots WHERE slot_no=?", (sn,)
                ).fetchone()
                status = row_db["status"] if row_db else "Available"
                fill = status_colors.get(status, "#334155")
                outline = "#facc15" if sn == slot else "#64748b"

                canvas.create_rectangle(
                    x - 27, y - 14, x + 27, y + 14,
                    fill=fill, outline=outline, width=3 if sn == slot else 1
                )
                canvas.create_text(
                    x, y, text=sn, fill="white", font=("Segoe UI", 7, "bold")
                )

            points, dest = route_points()
            if dest:
                _, _, _, prefix = dest
                row = rows[(prefix, dest[2])]
                canvas.create_line(
                    left_x, row["aisle_y"], right_x, row["aisle_y"],
                    fill="#334155", width=8
                )
                canvas.create_text(
                    w / 2, row["aisle_y"] - 10,
                    text=f"{row['title']} ACCESS AISLE",
                    fill="#64748b", font=("Segoe UI", 7, "bold")
                )

            canvas.create_rectangle(
                gate[0] - 55, gate[1] - 18, gate[0] + 55, gate[1] + 18,
                fill="#2563eb", outline="white", width=2
            )
            canvas.create_text(
                gate[0], gate[1], text="MAIN GATE",
                fill="white", font=("Segoe UI", 9, "bold")
            )

            if dest:
                x, y, _, _ = dest
                canvas.create_oval(
                    x - 20, y - 20, x + 20, y + 20, outline="#facc15", width=3
                )
                canvas.create_text(
                    x, y - 25, text=f"DESTINATION: {slot}",
                    fill="#facc15", font=("Segoe UI", 9, "bold")
                )

            return points, dest

        def animate():
            points, dest = draw()
            if not dest or len(points) < 2:
                return

            for a, b in zip(points, points[1:]):
                canvas.create_line(
                    a[0], a[1], b[0], b[1],
                    fill="#38bdf8", dash=(10, 6), width=4
                )

            for a, b in zip(points, points[1:]):
                mx = (a[0] + b[0]) / 2
                my = (a[1] + b[1]) / 2
                canvas.create_oval(
                    mx - 4, my - 4, mx + 4, my + 4, fill="#38bdf8", outline=""
                )

            marker = canvas.create_oval(
                points[0][0] - 9, points[0][1] - 9,
                points[0][0] + 9, points[0][1] + 9,
                fill="#22c55e", outline="white", width=2
            )

            segment_lengths = []
            total = 0.0
            for a, b in zip(points, points[1:]):
                length = math.hypot(b[0] - a[0], b[1] - a[1])
                segment_lengths.append(length)
                total += length

            if total <= 0:
                return

            speed = 7.0
            elapsed = 0.0

            def step():
                nonlocal elapsed
                if not win.winfo_exists():
                    return

                elapsed += speed
                remaining = elapsed

                for i, length in enumerate(segment_lengths):
                    if remaining <= length:
                        a = points[i]
                        b = points[i + 1]
                        ratio = 0 if length == 0 else remaining / length
                        x = a[0] + (b[0] - a[0]) * ratio
                        y = a[1] + (b[1] - a[1]) * ratio
                        canvas.coords(marker, x - 9, y - 9, x + 9, y + 9)
                        animation_job["id"] = win.after(30, step)
                        return
                    remaining -= length

                x, y = points[-1]
                canvas.coords(marker, x - 9, y - 9, x + 9, y + 9)
                canvas.create_text(
                    x, y + 30, text="✓ PARK HERE",
                    fill="#22c55e", font=("Segoe UI", 9, "bold")
                )
                animation_job["id"] = None

            step()

        combo.bind("<<ComboboxSelected>>", lambda e: draw())
        self.action_button(controls, "▶ Start Route", animate, GREEN).pack(side="left", padx=8)
        self.action_button(controls, "↻ Preview Route", draw, BLUE).pack(side="left", padx=4)
        self.action_button(controls, "Close", win.destroy, "#475569").pack(side="right")

        win.after(100, draw)

    # ---------------- PRE-BOOKING ----------------

    def show_bookings(self):
        self.current_page_method = self.show_bookings
        self.clear_content()
        self.page_title(
            "Pre-Booking",
            "Reserve a parking slot days in advance — the 30-minute arrival window starts at the booked time"
        )

        info = tk.Frame(self.content, bg="#10213f", padx=18, pady=14)
        info.pack(fill="x", padx=28, pady=(0, 12))
        tk.Label(
            info,
            text=f"📅 PRE-BOOKING: You can reserve a slot for a future date and time. The {GRACE_MINUTES}-minute arrival window starts at the booked start time. "
                 f"Example: a 2:00 PM booking has an arrival deadline of 2:30 PM. Cancel before the deadline for no fine; otherwise No-Show = ₹{NO_SHOW_FINE} fine.",
            bg="#10213f", fg="#bfdbfe", font=("Segoe UI", 10, "bold"),
            wraplength=1100, justify="left"
        ).pack(anchor="w")

        panel = tk.Frame(self.content, bg=PANEL, padx=22, pady=20)
        panel.pack(fill="x", padx=28)

        vehicle_var = tk.StringVar()
        type_var = tk.StringVar(value="Car")
        start_date_var = tk.StringVar(value=self.now().strftime("%d-%m-%Y"))
        end_date_var = tk.StringVar(value=self.now().strftime("%d-%m-%Y"))
        start_hour_var = tk.StringVar(value="")
        start_minute_var = tk.StringVar(value="")
        start_ampm_var = tk.StringVar(value="")
        end_hour_var = tk.StringVar(value="")
        end_minute_var = tk.StringVar(value="")
        end_ampm_var = tk.StringVar(value="")
        slot_var = tk.StringVar()

        left = tk.Frame(panel, bg=PANEL)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        right = tk.Frame(panel, bg=PANEL)
        right.grid(row=0, column=1, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_columnconfigure(1, weight=1)

        def field(parent, label, variable, combo_values=None):
            tk.Label(parent, text=label, bg=PANEL, fg="#cbd5e1",
                     font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(5, 4))
            widget = (
                self.make_combo(parent, variable, combo_values, 32)
                if combo_values else self.make_entry(parent, variable, 32)
            )
            widget.pack(fill="x", ipady=5)
            return widget

        field(left, "Vehicle Number", vehicle_var)
        field(left, "Vehicle Type", type_var, list(VEHICLE_RATES.keys()))
        field(left, "ENTER / START DATE (DD-MM-YYYY)", start_date_var)

        start_hours, start_minutes, start_ampms = self.time_values()

        tk.Label(left, text="ENTER / START TIME", bg=PANEL, fg="#cbd5e1",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(5, 4))
        start_time_frame = tk.Frame(left, bg=PANEL)
        start_time_frame.pack(fill="x", pady=(0, 5))
        self.make_combo(start_time_frame, start_hour_var, start_hours, 7).pack(side="left")
        tk.Label(start_time_frame, text=":", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=3)
        self.make_combo(start_time_frame, start_minute_var, start_minutes, 7).pack(side="left")
        self.make_combo(start_time_frame, start_ampm_var, start_ampms, 9).pack(side="left", padx=(8, 0))
        tk.Label(left, text="Choose Hour, Minute and AM/PM. AM/PM is intentionally not preselected.",
                 bg=PANEL, fg="#64748b", font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 8))

        field(right, "EXIT / END DATE (DD-MM-YYYY)", end_date_var)

        tk.Label(right, text="EXIT / END TIME", bg=PANEL, fg="#cbd5e1",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(5, 4))
        end_time_frame = tk.Frame(right, bg=PANEL)
        end_time_frame.pack(fill="x", pady=(0, 5))
        self.make_combo(end_time_frame, end_hour_var, start_hours, 7).pack(side="left")
        tk.Label(end_time_frame, text=":", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=3)
        self.make_combo(end_time_frame, end_minute_var, start_minutes, 7).pack(side="left")
        self.make_combo(end_time_frame, end_ampm_var, start_ampms, 9).pack(side="left", padx=(8, 0))
        tk.Label(right, text="Choose Hour, Minute and AM/PM. AM/PM is intentionally not preselected.",
                 bg=PANEL, fg="#64748b", font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 8))

        tk.Label(right, text="Parking Slot", bg=PANEL, fg="#cbd5e1",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(5, 4))
        slot_combo = self.make_combo(right, slot_var, [], 32)
        slot_combo.pack(fill="x", ipady=5)

        slot_note = tk.Label(
            right, text="Choose the slot that is convenient on the Slot Location map.",
            bg=PANEL, fg="#60a5fa", justify="left", padx=10, pady=10
        )
        slot_note.pack(fill="x", pady=14)

        def refresh_vehicle_type():
            vehicle = self.normalize_vehicle(vehicle_var.get())
            row = self.db.execute(
                "SELECT vehicle_type, parking_slot FROM vehicles WHERE vehicle_no=?",
                (vehicle,)
            ).fetchone()
            if row:
                type_var.set(row["vehicle_type"])
                slot_var.set(row["parking_slot"] or "")

        def refresh_available_slots(*_):
            vehicle_type = type_var.get()
            vehicle = self.normalize_vehicle(vehicle_var.get())
            rows = self.db.execute(
                """SELECT slot_no FROM slots
                   WHERE slot_type=? AND status='Available'
                   ORDER BY slot_no""", (vehicle_type,)
            ).fetchall()
            values = [r["slot_no"] for r in rows]
            slot_combo["values"] = values
            current = slot_var.get()
            if current not in values:
                vehicle_row = self.db.execute(
                    "SELECT parking_slot FROM vehicles WHERE vehicle_no=?", (vehicle,)
                ).fetchone()
                preferred = vehicle_row["parking_slot"] if vehicle_row else ""
                slot_var.set(preferred if preferred in values else (values[0] if values else ""))

        type_var.trace_add("write", refresh_available_slots)
        vehicle_var.trace_add("write", lambda *_: (refresh_vehicle_type(), refresh_available_slots()))
        refresh_available_slots()

        def create_booking():
            vehicle = self.normalize_vehicle(vehicle_var.get())
            if not vehicle or not slot_var.get().strip():
                messagebox.showerror("Missing Details", "Enter a registered vehicle number and select a parking slot.", parent=self.root)
                return

            vehicle_row = self.db.execute("SELECT * FROM vehicles WHERE vehicle_no=?", (vehicle,)).fetchone()
            if not vehicle_row:
                messagebox.showerror("Vehicle Not Registered", "Please register this vehicle first.", parent=self.root)
                return

            currently_parked = self.db.execute(
                "SELECT parking_id,slot_no FROM parking_sessions WHERE vehicle_no=? AND status='Active' "
                "ORDER BY id DESC LIMIT 1",
                (vehicle,)
            ).fetchone()
            if currently_parked:
                messagebox.showerror(
                    "Vehicle Already Parked",
                    f"Vehicle {vehicle} is already parked in slot {currently_parked['slot_no']}.\n\n"
                    "It cannot be pre-booked again while it has an active parking session.",
                    parent=self.root
                )
                return

            try:
                start_time_text = self.time_from_parts(
                    start_hour_var.get(), start_minute_var.get(), start_ampm_var.get()
                )
                end_time_text = self.time_from_parts(
                    end_hour_var.get(), end_minute_var.get(), end_ampm_var.get()
                )
                start_dt = datetime.strptime(
                    f"{self.date_to_db(start_date_var.get())} {start_time_text}",
                    "%Y-%m-%d %H:%M"
                )
                end_dt = datetime.strptime(
                    f"{self.date_to_db(end_date_var.get())} {end_time_text}",
                    "%Y-%m-%d %H:%M"
                )
            except ValueError as exc:
                messagebox.showerror("Invalid Date / Time", str(exc), parent=self.root)
                return

            now = self.now()
            # PRE-BOOKING: future dates/times are allowed. The 30-minute grace
            # period is an ARRIVAL deadline starting from the booked start time.
            if start_dt < now.replace(second=0, microsecond=0):
                messagebox.showerror("Invalid Arrival Time", "The selected arrival time cannot be in the past.", parent=self.root)
                return
            if end_dt <= start_dt:
                messagebox.showerror("Invalid Time Range", "Exit/End date and time must be later than the Enter/Start time.", parent=self.root)
                return

            slot = slot_var.get().strip().split(" — ")[0]
            slot_row = self.db.execute("SELECT * FROM slots WHERE slot_no=?", (slot,)).fetchone()
            if not slot_row or slot_row["status"] != "Available":
                messagebox.showerror("Slot Unavailable", "This slot is no longer available. Refresh and choose another slot.", parent=self.root)
                return
            if slot_row["slot_type"] != vehicle_row["vehicle_type"]:
                messagebox.showerror("Wrong Slot Type", f"{slot} is a {slot_row['slot_type']} slot, not a {vehicle_row['vehicle_type']} slot.", parent=self.root)
                return

            existing_booking = self.db.execute(
                """SELECT booking_id,start_datetime,end_datetime,status
                   FROM bookings
                   WHERE vehicle_no=?
                     AND status IN ('Reserved','Confirmed')
                   ORDER BY id DESC LIMIT 1""",
                (vehicle,)
            ).fetchone()
            if existing_booking:
                messagebox.showerror(
                    "Vehicle Already Pre-Booked",
                    f"Vehicle {vehicle} already has an active/future booking.\n\n"
                    f"Booking ID: {existing_booking['booking_id']}\n"
                    f"Start: {self.pretty_datetime(existing_booking['start_datetime'])}\n"
                    f"End: {self.pretty_datetime(existing_booking['end_datetime'])}\n\n"
                    "The same vehicle cannot be pre-booked again until this booking "
                    "is completed, cancelled, or marked No-Show.",
                    parent=self.root
                )
                return

            slot_overlap = self.db.execute(
                """SELECT booking_id,vehicle_no,start_datetime,end_datetime
                   FROM bookings
                   WHERE slot_no=? AND status IN ('Reserved','Confirmed')
                     AND start_datetime < ? AND end_datetime > ?
                   LIMIT 1""",
                (slot, end_dt.strftime('%Y-%m-%d %H:%M'), start_dt.strftime('%Y-%m-%d %H:%M'))
            ).fetchone()
            if slot_overlap:
                messagebox.showerror("Slot Already Booked", f"{slot} is already reserved for {slot_overlap['vehicle_no']} during that period.", parent=self.root)
                return

            booking_id = self.make_id("BKG")
            deadline = start_dt + timedelta(minutes=GRACE_MINUTES)
            created_text = now.strftime("%Y-%m-%d %H:%M:%S")
            deadline_text = deadline.strftime("%Y-%m-%d %H:%M")

            self.db.execute(
                """INSERT INTO bookings
                   (booking_id,vehicle_no,slot_no,start_date,end_date,start_time,end_time,
                    start_datetime,end_datetime,created_at,status,arrival_deadline)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (booking_id, vehicle, slot,
                 start_dt.strftime('%Y-%m-%d'), end_dt.strftime('%Y-%m-%d'),
                 start_dt.strftime('%H:%M'), end_dt.strftime('%H:%M'),
                 start_dt.strftime('%Y-%m-%d %H:%M'), end_dt.strftime('%Y-%m-%d %H:%M'),
                 created_text, "Reserved", deadline_text)
            )
            self.db.execute(
                "UPDATE slots SET status='Reserved',vehicle_no=?,booking_id=? WHERE slot_no=?",
                (vehicle, booking_id, slot)
            )
            self.db.execute("UPDATE vehicles SET parking_slot=? WHERE vehicle_no=?", (slot, vehicle))
            self.db.commit()

            messagebox.showinfo(
                "Booking Confirmed",
                f"Booking ID: {booking_id}\n\nVehicle: {vehicle}\nSlot: {slot}\n\n"
                f"Arrival: {start_dt.strftime('%d-%m-%Y %I:%M %p')}\n"
                f"Exit: {end_dt.strftime('%d-%m-%Y %I:%M %p')}\n\n"
                f"ARRIVAL DEADLINE: {deadline.strftime('%d-%m-%Y %I:%M %p')}\n"
                f"The vehicle must arrive within {GRACE_MINUTES} minutes of the booked start time.\n"
                "After the deadline, the booking is automatically cancelled as NO-SHOW and the slot is released.",
                parent=self.root
            )
            self.show_bookings()

        self.action_button(panel, "📅 Create Pre-Booking", create_booking).grid(row=1, column=0, columnspan=2, pady=20)

        tk.Label(self.content, text="Bookings", bg=BG, fg=TEXT,
                 font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=28, pady=(12, 2))

        controls = tk.Frame(self.content, bg=BG)
        controls.pack(fill="x", side="bottom", padx=28, pady=(0, 12))

        tree = self.make_table(
            self.content,
            ("Booking ID", "Vehicle", "Slot", "Enter Date", "Enter Time", "Exit Date", "Exit Time", "Created", "Arrival Deadline", "Status", "Fine"),
            [145, 120, 70, 100, 95, 100, 95, 145, 145, 100, 65]
        )
        rows = self.db.execute(
            """SELECT booking_id,vehicle_no,slot_no,start_date,start_time,end_date,end_time,
                      created_at,arrival_deadline,status,fine FROM bookings ORDER BY id DESC"""
        ).fetchall()
        for row in rows:
            deadline = self.pretty_datetime(row["arrival_deadline"]) if row["arrival_deadline"] else "—"
            created = self.pretty_datetime(row["created_at"]) if row["created_at"] else "—"
            tree.insert("", "end", values=(
                row["booking_id"], row["vehicle_no"], row["slot_no"],
                self.display_date(row["start_date"]), self.display_time(row["start_time"]),
                self.display_date(row["end_date"]), self.display_time(row["end_time"]),
                created, deadline, row["status"], f"₹{row['fine'] or 0:.0f}"
            ))

        self.action_button(controls, "❌ Cancel Selected Booking", lambda: self.cancel_booking(tree), RED).pack(side="right")
        self.action_button(controls, "🌐 Open Pre-Booking Website", lambda: webbrowser.open(self.booking_url()), BLUE).pack(side="right", padx=8)
        tk.Label(controls, text=f"Customer website: {self.booking_url()}", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")

    # ---------------- PARTICULAR HISTORY ----------------

    def show_particular_history(self):
        self.current_page_method = self.show_particular_history
        self.clear_content()
        self.page_title(
            "Particular History",
            "Enter one vehicle number to view its complete parking, booking, payment and complaint history"
        )

        search_bar = tk.Frame(self.content, bg=BG)
        search_bar.pack(fill="x", padx=28)

        query_var = tk.StringVar()

        tk.Label(
            search_bar, text="Vehicle Number", bg=BG, fg=MUTED,
            font=("Segoe UI", 10, "bold")
        ).pack(side="left")

        self.make_entry(search_bar, query_var, 30).pack(side="left", padx=8, ipady=6)

        results = tk.Frame(self.content, bg=BG)
        results.pack(fill="both", expand=True, padx=28, pady=15)

        def search():
            for widget in results.winfo_children():
                widget.destroy()

            vehicle_no = self.normalize_vehicle(query_var.get())

            vehicle = self.db.execute(
                "SELECT * FROM vehicles WHERE vehicle_no=?", (vehicle_no,)
            ).fetchone()

            if not vehicle:
                tk.Label(
                    results,
                    text="Vehicle not found. Register the vehicle first.",
                    bg=BG, fg="#f87171", font=("Segoe UI", 13, "bold")
                ).pack(pady=30)
                return

            info = tk.Frame(results, bg=PANEL, padx=18, pady=16)
            info.pack(fill="x")

            current = self.db.execute(
                """SELECT * FROM parking_sessions
                   WHERE vehicle_no=? AND status='Active'
                   ORDER BY id DESC LIMIT 1""",
                (vehicle_no,)
            ).fetchone()

            if current:
                current_text = (
                    f"🟢 CURRENTLY PARKED   Slot: {current['slot_no']}   "
                    f"Entry: {self.pretty_datetime(current['entry_datetime'])}"
                )
            else:
                current_text = "⚪ CURRENT STATUS: Not currently parked"

            tk.Label(
                info,
                text=(
                    f"Vehicle: {vehicle['vehicle_no']}    "
                    f"Type: {vehicle['vehicle_type']}    "
                    f"Owner: {vehicle['owner_name']}    "
                    f"Contact: {vehicle['owner_contact']}    "
                    f"Persons: {vehicle['persons']}    "
                    f"Registered Slot: {vehicle['parking_slot'] or '—'}\n\n"
                    f"{current_text}"
                ),
                bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold"), justify="left"
            ).pack(side="left", anchor="w")

            self.action_button(
                info, "＋ Add Complaint",
                lambda: self.complaint_form(vehicle_no), RED
            ).pack(side="right", padx=5)

            tk.Label(
                results, text="Past Parking Records", bg=BG, fg=TEXT,
                font=("Segoe UI", 14, "bold")
            ).pack(anchor="w", pady=(14, 4))

            history_tree = self.make_table(
                results,
                (
                    "Parking ID", "Slot", "Enter Date", "Enter Time",
                    "Exit Date", "Exit Time", "Duration", "Fee", "Payment", "Status"
                ),
                [145, 70, 100, 105, 100, 105, 90, 80, 110, 100]
            )

            sessions = self.db.execute(
                "SELECT * FROM parking_sessions WHERE vehicle_no=? ORDER BY id DESC",
                (vehicle_no,)
            ).fetchall()

            total_paid = 0

            for session in sessions:
                total_paid += session["fee"] or 0

                duration = (
                    f"{session['duration_minutes']} min"
                    if session["duration_minutes"] else "-"
                )

                history_tree.insert(
                    "", "end",
                    values=(
                        session["parking_id"],
                        session["slot_no"],
                        self.display_date(session["entry_date"]),
                        session["entry_time"],
                        self.display_date(session["exit_date"]),
                        session["exit_time"] or "-",
                        duration,
                        f"₹{(session['fee'] or 0):.0f}",
                        session["payment_method"] or "-",
                        session["status"]
                    )
                )

            tk.Label(
                results, text="Booking History", bg=BG, fg=TEXT,
                font=("Segoe UI", 14, "bold")
            ).pack(anchor="w", pady=(12, 4))

            booking_tree = self.make_table(
                results,
                ("Booking ID", "Slot", "Start", "End", "Created", "Status", "Fine"),
                [145, 70, 150, 150, 150, 110, 80]
            )

            bookings = self.db.execute(
                """SELECT booking_id,slot_no,start_datetime,end_datetime,created_at,status,fine
                   FROM bookings WHERE vehicle_no=? ORDER BY id DESC""",
                (vehicle_no,)
            ).fetchall()

            for booking in bookings:
                booking_tree.insert(
                    "", "end",
                    values=(
                        booking["booking_id"],
                        booking["slot_no"],
                        self.pretty_datetime(booking["start_datetime"]),
                        self.pretty_datetime(booking["end_datetime"]),
                        self.pretty_datetime(booking["created_at"]),
                        booking["status"],
                        f"₹{(booking['fine'] or 0):.0f}"
                    )
                )

            tk.Label(
                results,
                text=f"Total Visits: {len(sessions)}    •    "
                     f"Total Parking Paid: ₹{total_paid:.0f}",
                bg=BG, fg="#60a5fa", font=("Segoe UI", 10, "bold")
            ).pack(anchor="w", pady=7)

            complaints = self.db.execute(
                """SELECT complaint_id,complaint_type,description,created_at,status
                   FROM complaints WHERE vehicle_no=? ORDER BY id DESC""",
                (vehicle_no,)
            ).fetchall()

            tk.Label(
                results, text="Complaint History", bg=BG, fg=TEXT,
                font=("Segoe UI", 14, "bold")
            ).pack(anchor="w", pady=(12, 4))

            complaint_tree = self.make_table(
                results,
                ("Complaint ID", "Type", "Description", "Date", "Status"),
                [145, 180, 360, 150, 110]
            )

            for complaint in complaints:
                complaint_tree.insert(
                    "", "end",
                    values=(
                        complaint["complaint_id"],
                        complaint["complaint_type"],
                        complaint["description"],
                        complaint["created_at"],
                        complaint["status"]
                    )
                )

        self.action_button(search_bar, "🔎 Search", search).pack(side="left")

        tk.Label(
            search_bar, text="Example: TN38AB1234", bg=BG, fg="#64748b"
        ).pack(side="left", padx=10)

    def show_vehicle_report(self):
        """Backward-compatible alias for the Particular History page."""
        self.show_particular_history()

    def show_history(self):
        self.current_page_method = self.show_history
        self.clear_content()
        self.page_title(
            "Overall History",
            "All vehicles, parking visits, entry/exit times and today's collection"
        )

        today = self.now().strftime("%Y-%m-%d")
        c = self.db.cursor()

        total_entries = c.execute(
            "SELECT COUNT(*) FROM parking_sessions WHERE substr(entry_datetime,1,10)=?",
            (today,)
        ).fetchone()[0]
        total_exits = c.execute(
            "SELECT COUNT(*) FROM parking_sessions WHERE status='Completed' AND substr(exit_datetime,1,10)=?",
            (today,)
        ).fetchone()[0]
        revenue = c.execute(
            "SELECT COALESCE(SUM(fee),0) FROM parking_sessions WHERE status='Completed' AND substr(exit_datetime,1,10)=?",
            (today,)
        ).fetchone()[0]
        parked = c.execute(
            "SELECT COUNT(*) FROM parking_sessions WHERE status='Active'"
        ).fetchone()[0]

        cards = tk.Frame(self.content, bg=BG)
        cards.pack(fill="x", padx=22)
        for value, label in [
            (total_entries, "TODAY'S ENTRIES"),
            (total_exits, "TODAY'S EXITS"),
            (parked, "CURRENTLY PARKED"),
            (f"₹{revenue:.0f}", "TODAY'S REVENUE")
        ]:
            self.card(cards, value, label)

        type_rows = c.execute(
            """SELECT v.vehicle_type AS vehicle_type,
                      COUNT(ps.id) AS entries,
                      SUM(CASE WHEN ps.status='Completed' AND substr(ps.exit_datetime,1,10)=? THEN 1 ELSE 0 END) AS exits,
                      COALESCE(SUM(CASE WHEN ps.status='Completed' AND substr(ps.exit_datetime,1,10)=? THEN ps.fee ELSE 0 END),0) AS revenue
               FROM parking_sessions ps
               JOIN vehicles v ON v.vehicle_no=ps.vehicle_no
               WHERE substr(ps.entry_datetime,1,10)=?
                  OR (ps.status='Completed' AND substr(ps.exit_datetime,1,10)=?)
               GROUP BY v.vehicle_type
               ORDER BY CASE v.vehicle_type WHEN 'Car' THEN 1 WHEN 'Bike' THEN 2 WHEN 'Van' THEN 3 ELSE 4 END""",
            (today, today, today, today)
        ).fetchall()

        tk.Label(
            self.content, text="Today's Vehicle Summary", bg=BG, fg=TEXT,
            font=("Segoe UI", 14, "bold")
        ).pack(anchor="w", padx=28, pady=(16, 2))

        summary_tree = self.make_table(
            self.content,
            ("Vehicle Type", "Entries", "Exits", "Revenue"),
            [150, 120, 120, 150]
        )
        for r in type_rows:
            summary_tree.insert(
                "", "end",
                values=(r["vehicle_type"], r["entries"], r["exits"], f"₹{r['revenue']:.0f}")
            )

        tk.Label(
            self.content, text="All Parking Activity", bg=BG, fg=TEXT,
            font=("Segoe UI", 14, "bold")
        ).pack(anchor="w", padx=28, pady=(10, 2))

        tree = self.make_table(
            self.content,
            ("Date", "Vehicle No", "Owner", "Type", "Slot", "Entry Time", "Exit Time", "Duration", "Fee", "Status"),
            [90, 125, 145, 75, 70, 145, 145, 85, 80, 95]
        )

        rows = c.execute(
            """SELECT ps.*, v.owner_name, v.vehicle_type
               FROM parking_sessions ps
               JOIN vehicles v ON v.vehicle_no=ps.vehicle_no
               ORDER BY ps.id DESC"""
        ).fetchall()
        for r in rows:
            entry = self.pretty_datetime(r["entry_datetime"]) if r["entry_datetime"] else "—"
            exit_ = self.pretty_datetime(r["exit_datetime"]) if r["exit_datetime"] else "—"
            duration = f"{r['duration_minutes']} min" if r["duration_minutes"] else "—"
            tree.insert("", "end", values=(
                self.display_date(r["entry_date"]), r["vehicle_no"], r["owner_name"],
                r["vehicle_type"], r["slot_no"], entry, exit_, duration,
                f"₹{r['fee'] or 0:.0f}", r["status"]
            ))

    # ---------------- COMPLAINTS ----------------

    def show_complaints(self):
        self.current_page_method = self.show_complaints
        self.clear_content()
        self.page_title(
            "Complaints",
            "Create and manage complaints linked to a particular vehicle"
        )

        bar = tk.Frame(self.content, bg=BG)
        bar.pack(fill="x", padx=28)

        self.action_button(bar, "＋ Add Complaint", self.complaint_form, RED).pack(side="left")

        tree = self.make_table(
            self.content,
            (
                "Complaint ID", "Vehicle", "Type",
                "Description", "Reported At", "Status"
            ),
            [150, 130, 190, 360, 155, 120]
        )

        rows = self.db.execute(
            """SELECT complaint_id,vehicle_no,complaint_type,
                      description,created_at,status
               FROM complaints ORDER BY id DESC"""
        ).fetchall()

        for row in rows:
            tree.insert(
                "", "end",
                values=(
                    row["complaint_id"], row["vehicle_no"], row["complaint_type"],
                    row["description"], row["created_at"], row["status"]
                )
            )

        self.action_button(
            bar, "✏ Update Selected",
            lambda: self.update_complaint(tree), BLUE
        ).pack(side="right")

    def complaint_form(self, vehicle_no=None):
        win = tk.Toplevel(self.root)
        win.title("Add Complaint")
        win.geometry("560x600")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.grab_set()

        tk.Label(
            win, text="＋ Add Complaint", bg=BG, fg=TEXT,
            font=("Segoe UI", 19, "bold")
        ).pack(anchor="w", padx=28, pady=(22, 4))

        tk.Label(
            win, text="Record a complaint against a specific vehicle.",
            bg=BG, fg=MUTED
        ).pack(anchor="w", padx=30, pady=(0, 18))

        vehicle_var = tk.StringVar(value=vehicle_no or "")
        type_var = tk.StringVar(value="Wrong Parking")
        reported_by_var = tk.StringVar(value="Parking Staff")

        form = tk.Frame(win, bg=BG)
        form.pack(fill="x", padx=28)

        tk.Label(
            form, text="Vehicle Number", bg=BG, fg="#cbd5e1",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor="w", pady=(3, 4))

        self.make_entry(form, vehicle_var).pack(fill="x", ipady=6)

        tk.Label(
            form, text="Complaint Type", bg=BG, fg="#cbd5e1",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor="w", pady=(14, 4))

        self.make_combo(
            form, type_var,
            [
                "Wrong Parking",
                "Blocking Another Vehicle",
                "Overstay",
                "Suspicious/Unauthorized Parking",
                "Damage/Accident",
                "Other"
            ],
            35
        ).pack(fill="x", ipady=5)

        tk.Label(
            form, text="Reported By", bg=BG, fg="#cbd5e1",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor="w", pady=(14, 4))

        self.make_entry(form, reported_by_var).pack(fill="x", ipady=6)

        tk.Label(
            form, text="Complaint Description", bg=BG, fg="#cbd5e1",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor="w", pady=(14, 4))

        description = tk.Text(
            form, height=7, bg=INPUT, fg=TEXT, insertbackground=TEXT,
            selectbackground=BLUE, relief="flat", bd=0, font=("Segoe UI", 10)
        )
        description.pack(fill="x")

        def save():
            vehicle = self.normalize_vehicle(vehicle_var.get())

            if not vehicle:
                messagebox.showerror("Missing Vehicle", "Enter the vehicle number.", parent=win)
                return

            exists = self.db.execute(
                "SELECT 1 FROM vehicles WHERE vehicle_no=?", (vehicle,)
            ).fetchone()

            if not exists:
                messagebox.showerror(
                    "Vehicle Not Found",
                    "This vehicle is not registered in the system.",
                    parent=win
                )
                return

            complaint_id = self.make_id("CMP")

            self.db.execute(
                """INSERT INTO complaints
                   (complaint_id,vehicle_no,complaint_type,
                    description,reported_by,created_at,status)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    complaint_id, vehicle, type_var.get(),
                    description.get("1.0", "end").strip(),
                    reported_by_var.get().strip(),
                    self.now().strftime("%d-%m-%Y %I:%M %p"),
                    "Open"
                )
            )
            self.db.commit()

            messagebox.showinfo(
                "Complaint Added",
                f"Complaint {complaint_id} has been recorded.",
                parent=win
            )

            win.destroy()
            self.show_complaints()

        self.action_button(
            win, "📨 Submit Complaint", save, RED
        ).pack(fill="x", padx=28, pady=25)

    def update_complaint(self, tree):
        selected = tree.selection()

        if not selected:
            messagebox.showwarning("Select Complaint", "Select a complaint first.")
            return

        values = tree.item(selected[0], "values")
        complaint_id = values[0]

        win = tk.Toplevel(self.root)
        win.title("Update Complaint")
        win.geometry("350x230")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.grab_set()

        tk.Label(
            win, text=f"Complaint: {complaint_id}", bg=BG, fg=TEXT,
            font=("Segoe UI", 13, "bold")
        ).pack(pady=(25, 10))

        status_var = tk.StringVar(value=values[-1])

        self.make_combo(
            win, status_var,
            ["Open", "Under Review", "Resolved", "Rejected"], 25
        ).pack(padx=25, fill="x", ipady=5)

        def save():
            self.db.execute(
                "UPDATE complaints SET status=? WHERE complaint_id=?",
                (status_var.get(), complaint_id)
            )
            self.db.commit()
            win.destroy()
            self.show_complaints()

        self.action_button(win, "Save Status", save).pack(pady=25)

    # ---------------- REPORTS ----------------

    def show_reports(self):
        self.current_page_method = self.show_reports
        self.clear_content()
        self.page_title(
            "Reports & Statistics",
            "Daily parking activity, collection and slot availability"
        )

        today = self.now().strftime("%Y-%m-%d")
        c = self.db.cursor()

        completed = c.execute(
            """SELECT COUNT(*) FROM parking_sessions
               WHERE status='Completed' AND substr(exit_datetime,1,10)=?""",
            (today,)
        ).fetchone()[0]

        revenue = c.execute(
            """SELECT COALESCE(SUM(fee),0) FROM parking_sessions
               WHERE status='Completed' AND substr(exit_datetime,1,10)=?""",
            (today,)
        ).fetchone()[0]

        bookings = c.execute(
            "SELECT COUNT(*) FROM bookings WHERE substr(created_at,1,10)=?",
            (today,)
        ).fetchone()[0]

        no_shows = c.execute(
            """SELECT COUNT(*) FROM bookings
               WHERE status='No-Show' AND substr(created_at,1,10)=?""",
            (today,)
        ).fetchone()[0]

        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="x", padx=22)

        for value, label in [
            (completed, "COMPLETED EXITS"),
            (f"₹{revenue:.0f}", "TODAY'S COLLECTION"),
            (bookings, "TODAY'S BOOKINGS"),
            (no_shows, "NO-SHOWS")
        ]:
            self.card(row, value, label)

        panel = tk.Frame(self.content, bg=PANEL, padx=22, pady=22)
        panel.pack(fill="both", expand=True, padx=28, pady=25)

        tk.Label(
            panel, text="Parking Availability", bg=PANEL, fg=TEXT,
            font=("Segoe UI", 15, "bold")
        ).pack(anchor="w")

        slot_rows = c.execute(
            """SELECT slot_type,status,COUNT(*) AS count
               FROM slots GROUP BY slot_type,status
               ORDER BY slot_type,status"""
        ).fetchall()

        for row_data in slot_rows:
            tk.Label(
                panel,
                text=(
                    f"{row_data['slot_type']:<8}  "
                    f"{row_data['status']:<10}  "
                    f"{row_data['count']}"
                ),
                bg=PANEL, fg="#cbd5e1", font=("Consolas", 11)
            ).pack(anchor="w", pady=3)

        total = c.execute("SELECT COUNT(*) FROM slots").fetchone()[0]
        occupied = c.execute(
            "SELECT COUNT(*) FROM slots WHERE status='Occupied'"
        ).fetchone()[0]
        occupancy = (occupied / total * 100) if total else 0

        tk.Label(
            panel, text=f"Occupancy Rate: {occupancy:.1f}%",
            bg=PANEL, fg="#60a5fa", font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", pady=16)

        tk.Label(
            panel, text="Today's Revenue by Vehicle Type",
            bg=PANEL, fg=TEXT, font=("Segoe UI", 13, "bold")
        ).pack(anchor="w", pady=(8, 6))

        revenue_rows = c.execute(
            """SELECT v.vehicle_type, COUNT(ps.id) AS exits,
                      COALESCE(SUM(ps.fee),0) AS revenue
               FROM parking_sessions ps
               JOIN vehicles v ON v.vehicle_no=ps.vehicle_no
               WHERE ps.status='Completed'
                 AND substr(ps.exit_datetime,1,10)=?
               GROUP BY v.vehicle_type
               ORDER BY CASE v.vehicle_type WHEN 'Car' THEN 1 WHEN 'Bike' THEN 2 WHEN 'Van' THEN 3 ELSE 4 END""",
            (today,)
        ).fetchall()

        for r in revenue_rows:
            tk.Label(
                panel,
                text=f"{r['vehicle_type']:<8}  Exits: {r['exits']:<4}  Revenue: ₹{r['revenue']:.0f}",
                bg=PANEL, fg="#cbd5e1", font=("Consolas", 11)
            ).pack(anchor="w", pady=2)

    # ---------------- SETTINGS ----------------

    def show_settings(self):
        self.current_page_method = self.show_settings
        self.clear_content()
        self.page_title(
            "Settings",
            "Current demo pricing and booking rules"
        )

        panel = tk.Frame(self.content, bg=PANEL, padx=25, pady=25)
        panel.pack(fill="x", padx=28)

        tk.Label(
            panel, text="Parking Pricing", bg=PANEL, fg=TEXT,
            font=("Segoe UI", 15, "bold")
        ).pack(anchor="w", pady=(0, 12))

        for vehicle_type, rate in VEHICLE_RATES.items():
            tk.Label(
                panel, text=f"{vehicle_type}: ₹{rate} per billed hour",
                bg=PANEL, fg="#cbd5e1", font=("Segoe UI", 10)
            ).pack(anchor="w", pady=4)

        tk.Label(
            panel, text=f"No-Show Fine: ₹{NO_SHOW_FINE}",
            bg=PANEL, fg="#fbbf24", font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", pady=(15, 4))

        tk.Label(
            panel, text=f"Arrival Grace Period: {GRACE_MINUTES} minutes",
            bg=PANEL, fg="#fbbf24", font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", pady=4)

        upi_text = "Not set (enter it on the payment screen)" if UPI_ID == "yourupi@upi" else UPI_ID
        tk.Label(
            panel, text=f"Receiving UPI ID: {upi_text}",
            bg=PANEL, fg="#fbbf24", font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", pady=4)

        tk.Label(
            panel, text=f"Receipts are saved in: {RECEIPT_DIR}",
            bg=PANEL, fg="#fbbf24", font=("Segoe UI", 10, "bold"),
            wraplength=900, justify="left"
        ).pack(anchor="w", pady=4)

        tk.Label(
            panel,
            text=(f"QR payment page address: http://{self.pay_ip}:{self.pay_port}/  "
                  + ("(running)" if self.pay_server else "(NOT running - port busy)")),
            bg=PANEL, fg="#fbbf24", font=("Segoe UI", 10, "bold"),
            wraplength=900, justify="left"
        ).pack(anchor="w", pady=4)

        tk.Label(panel, text=(f"Pre-Booking website: {self.booking_url()}  " + ("(running)" if self.booking_server else "(NOT running - port busy)")), bg=PANEL, fg="#60a5fa", font=("Segoe UI", 10, "bold"), wraplength=900, justify="left").pack(anchor="w", pady=4)

        theme_row = tk.Frame(panel, bg=PANEL)
        theme_row.pack(fill="x", pady=(20, 8))
        tk.Label(
            theme_row, text="Interface Theme", bg=PANEL, fg=TEXT,
            font=("Segoe UI", 11, "bold")
        ).pack(side="left")
        tk.Label(
            theme_row, text=("Dark" if self.theme_name == "dark" else "Bright"),
            bg=PANEL, fg=BLUE, font=("Segoe UI", 10, "bold")
        ).pack(side="left", padx=12)
        self.action_button(
            theme_row, self.theme_button_text(), self.toggle_theme, BLUE
        ).pack(side="right")

        tk.Label(
            panel,
            text=(
                "Choose the interface that suits your presentation: Dark for a "
                "premium night-dashboard look, or Bright for a clean modern campus style. "
                "The same parking data and features work in both themes."
            ),
            bg=PANEL, fg=MUTED, wraplength=900, justify="left"
        ).pack(anchor="w", pady=(8, 0))

        tk.Label(
            panel,
            text=(
                "For the hackathon, the pricing and booking rules are kept at the top "
                "of the Python file so your team can change them quickly."
            ),
            bg=PANEL, fg=MUTED, wraplength=900, justify="left"
        ).pack(anchor="w", pady=(12, 0))

    # ---------------- CLOCK / CLOSE ----------------

    def update_clock(self):
        self.clock_label.config(
            text=self.now().strftime("%d %b %Y • %I:%M:%S %p")
        )
        self.root.after(1000, self.update_clock)

    def close_app(self):
        try:
            if getattr(self, "booking_server", None):
                self.booking_server.shutdown()
                self.booking_server.server_close()
        except Exception:
            pass
        try:
            if getattr(self, "pay_server", None):
                self.pay_server.shutdown()
                self.pay_server.server_close()
        except Exception:
            pass
        try:
            self.db.commit()
            self.db.close()
        finally:
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = SmartParkingApp(root)
    root.mainloop()