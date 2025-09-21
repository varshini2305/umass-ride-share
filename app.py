import os
import re
from datetime import datetime, date, timezone, time as dtime
from typing import Tuple, Dict, Any, List
import certifi
import pandas as pd
import streamlit as st
from pymongo import MongoClient, ASCENDING, TEXT
from bson.objectid import ObjectId
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from datetime import datetime
import pytz   # or zoneinfo in Python 3.9+

# Optional: handle websocket closed errors gracefully (e.g., when user navigates away)
try:
    from tornado.websocket import WebSocketClosedError  # type: ignore
except Exception:  # pragma: no cover
    WebSocketClosedError = Exception  # fallback so we can except it even if import is unavailable

eastern = pytz.timezone("America/New_York")

# Now in EST/EDT
created_at = datetime.now(eastern).isoformat()
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---- Config ----
st.set_page_config(page_title="UMass Ride Share", page_icon="🚗", layout="wide")
st.title("🚗 UMass Ride Share — between Amherst ↔ Boston/NYC")

# Add JavaScript for WhatsApp fallback
st.markdown("""
<script>
function openWhatsAppWithFallback(phoneNumber, whatsappUrl) {
    // Try to open WhatsApp
    const whatsappWindow = window.open(whatsappUrl, '_blank');
    
    // If WhatsApp fails to open or user doesn't have it, fallback to default messaging
    setTimeout(function() {
        if (whatsappWindow && !whatsappWindow.closed) {
            // WhatsApp opened successfully
            return;
        } else {
            // WhatsApp failed, try to open default messaging app
            try {
                // Detect device type
                const isIPhone = /iPhone|iPad|iPod/.test(navigator.userAgent);
                const isMac = navigator.platform.indexOf('Mac') !== -1;
                
                if (isIPhone) {
                    // iPhone: try to open Messages app
                    window.location.href = 'message://' + phoneNumber;
                } else if (isMac) {
                    // Mac: try to open Messages app
                    window.location.href = 'message://' + phoneNumber;
                } else {
                    // Other devices: fallback to tel: link
                    window.location.href = 'tel:' + phoneNumber;
                }
            } catch (e) {
                // Final fallback to tel: link
                window.location.href = 'tel:' + phoneNumber;
            }
        }
    }, 1000);
}
</script>
""", unsafe_allow_html=True)

MONGODB_URI = os.getenv("MONGODB_URI", "")
DB_NAME = os.getenv("DB_NAME", "apps-on-demand")

# Email configuration
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")  # Set this in .env file
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")  # Set this in .env file
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

if not MONGODB_URI:
    st.warning("Set MONGODB_URI in .env or environment for persistence. Using in-memory fallback.")
    # In-memory fallback (for UI trial only)
    st.session_state.setdefault("_mem_docs", [])
    client = None
    db = None
    col = None
else:
    @st.cache_resource(show_spinner=False)
    def get_collection() -> Any:
        client_local = MongoClient(MONGODB_URI, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=30000)
        db_local = client_local[DB_NAME]
        collection = db_local["umass-ride-share"]
        try:
            collection.create_index([("route_key", ASCENDING), ("date", ASCENDING)])
            collection.create_index([("date", ASCENDING)])
            collection.create_index([("created_at", ASCENDING)])
            collection.create_index([("name", ASCENDING)])
            collection.create_index([("contact", ASCENDING)])
            collection.create_index([("prefs", TEXT)])
            collection.create_index([("email", ASCENDING)])
            collection.create_index([("notify_matches", ASCENDING)])
        except Exception as e:
            st.info(f"Indexing note: {e}")
        return collection

    col = get_collection()

CITIES = ["Amherst", "Boston", "New York", "Other"]
GENDERS = ["Prefer not to say", "Female", "Male", "Non-binary", "Other"]

def is_valid_phone_number(contact: str) -> bool:
    """Check if contact string is a valid phone number"""
    if not contact:
        return False
    
    # Remove common separators and spaces
    cleaned = re.sub(r'[\s\-\(\)\.]', '', contact)
    
    # Check if it's a US phone number (10 digits) or international (10-15 digits)
    if re.match(r'^\+?1?\d{10,15}$', cleaned):
        return True
    
    # Check if it looks like a phone number with common formats
    if re.match(r'^[\d\s\-\(\)\.\+]{10,20}$', contact):
        return True
    
    return False

def is_valid_email(contact: str) -> bool:
    """Check if contact string is a valid email address"""
    if not contact:
        return False
    
    # Basic email validation regex
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(email_pattern, contact))

def should_display_attribute(key: str, value: Any) -> bool:
    """Check if an attribute should be displayed based on its value"""
    if value is None:
        return False
    
    if key == "age" and value == 0:
        return False
    elif key == "gender" and value == "Prefer not to say":
        return False
    elif key == "bags" and value == 0:
        return False
    
    return True

def format_contact_display(contact: str) -> str:
    """Format contact for display with clickable phone numbers and emails"""
    if not contact:
        return ""
    
    if is_valid_phone_number(contact):
        # Clean the number for WhatsApp - remove ALL symbols and spaces, keep only digits
        cleaned_number = re.sub(r'[^\d]', '', contact)
        
        # Handle US numbers (remove +1 or 1 prefix, keep 10 digits)
        if cleaned_number.startswith('1') and len(cleaned_number) == 11:
            # 1XXXXXXXXXX -> XXXXXXXXXX (10 digits)
            whatsapp_number = cleaned_number[1:]
        elif len(cleaned_number) == 10:
            # XXXXXXXXXX -> XXXXXXXXXX (10 digits, no change)
            whatsapp_number = cleaned_number
        else:
            # International numbers - keep the full number with country code
            # Example: 919920581109 (Indian number)
            whatsapp_number = cleaned_number
        
        # Create WhatsApp link
        whatsapp_link = f"https://wa.me/{whatsapp_number}"
        
        # Create tel: link for native phone apps
        tel_link = f"tel:{cleaned_number}"
        
        # Create message: link for default messaging app (Messages on iPhone, SMS on Android)
        message_link = f"message://{cleaned_number}"
        
        # Display with clickable links and fallback options
        return f"""
        📱 **Phone Number:** {contact}
        
        **Quick Actions:**
        • [📞 Call]({tel_link}) - Opens phone app
        • [💬 WhatsApp]({whatsapp_link}) - Opens WhatsApp
        """
    elif is_valid_email(contact):
        # Create mailto: link for email apps
        mailto_link = f"mailto:{contact}"
        
        # Display with clickable email link
        return f"""
        📧 **Email Address:** {contact}
        
        [✉️ Send Email]({mailto_link})
        
        *Click the link above to open your default email app*
        """
    else:
        # Not a phone number or email, display as regular contact
        return f"📋 **Contact:** {contact}"

def normalize_city(city: str, other: str) -> str:
    if city == "Other":
        return other.strip()
    return city

def send_email_notification(recipient_email: str, matches: List[Dict[str, Any]], search_origin: str, search_destination: str, search_date: str) -> bool:
    """Send email notification about ride matches"""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        st.warning("Email not configured. Set EMAIL_SENDER and EMAIL_PASSWORD in .env file.")
        return False
    
    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = recipient_email
        msg['Subject'] = f"🚗 Ride Matches Found: {search_origin} → {search_destination} on {search_date}"
        
        # Create email body
        body = f"""
        <html>
        <body>
        <h2>🚗 UMass Ride Share - Matches Found!</h2>
        <p>We found <strong>{len(matches)} ride match(es)</strong> for your trip from <strong>{search_origin}</strong> to <strong>{search_destination}</strong> on <strong>{search_date}</strong>.</p>
        
        <h3>Available Rides:</h3>
        """
        
        for i, match in enumerate(matches, 1):
            date_str = match.get("date", "")
            body += f"""
            <div style="border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 5px;">
                <h4>Match #{i}: {match.get('name')}</h4>
                <p><strong>Route:</strong> {match.get('origin')} → {match.get('destination')}</p>
                <p><strong>Date:</strong> {date_str}</p>
                <p><strong>Time:</strong> {match.get('time_from')} – {match.get('time_to')}</p>
                <p><strong>Price:</strong> ${int(match.get('price_min', 0))} – ${int(match.get('price_max', 0))}</p>
                <p><strong>Bags:</strong> {match.get('bags', 0)}</p>
                <p><strong>Student:</strong> {'Yes' if match.get('is_student') else 'No'}</p>
                """
            
            if match.get('exact_location'):
                body += f"<p><strong>Pickup/Drop:</strong> {match.get('exact_location')}</p>"
            
            if match.get('prefs'):
                body += f"<p><strong>Preferences:</strong> {match.get('prefs')}</p>"
            
            body += f"""
                <p><strong>Contact:</strong> {match.get('contact')}</p>
            </div>
            """
        
        body += f"""
        <p><em>This email was sent from UMass Ride Share. Please contact the drivers directly to arrange your ride.</em></p>
        <p><em>To stop receiving notifications, uncheck the "Notify me of matches" option when posting your trip.</em></p>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        # Send email
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_SENDER, recipient_email, text)
        server.quit()
        
        return True
        
    except Exception as e:
        st.error(f"Failed to send email: {e}")
        return False

def check_and_notify_matches(origin: str, destination: str, trip_date: str, exclude_contact: str = None) -> None:
    """Check for matches and send notifications to users who opted in"""
    if col is None:
        return
    
    try:
        # Find users who want notifications for this route and date
        query = {
            "notify_matches": True,
            "email": {"$exists": True, "$ne": ""},
            "date": trip_date
        }
        
        # Add location similarity check
        potential_notifications = list(col.find(query))
        
        for user in potential_notifications:
            # Skip if this is the same user posting
            if user.get("contact") == exclude_contact:
                continue
            
            # Check if there's a location match
            user_origin = user.get("origin", "").lower().strip()
            user_dest = user.get("destination", "").lower().strip()
            search_origin = origin.lower().strip()
            search_dest = destination.lower().strip()
            
            # Check for origin match
            origin_match = (search_origin in user_origin or user_origin in search_origin or 
                          any(word in user_origin for word in search_origin.split()) or
                          any(word in search_origin for word in user_origin.split()))
            
            # Check for destination match
            dest_match = (search_dest in user_dest or user_dest in search_dest or
                         any(word in user_dest for word in search_dest.split()) or
                         any(word in search_dest for word in user_dest.split()))
            
            if origin_match and dest_match:
                # Find actual matches for this user's criteria
                matches = find_matches(
                    origin=origin,
                    destination=destination,
                    trip_date=trip_date
                )
                
                # Filter out the user's own posts from matches
                filtered_matches = [m for m in matches if m.get("contact") != user.get("contact")]
                
                if filtered_matches:
                    # Send notification
                    send_email_notification(
                        user.get("email"),
                        filtered_matches,
                        origin,
                        destination,
                        trip_date
                    )
                    
    except Exception as e:
        st.error(f"Error checking notifications: {e}")

def minutes(t: dtime) -> int:
    return t.hour * 60 + t.minute

def ranges_overlap(a_min: int, a_max: int, b_min: int, b_max: int) -> bool:
    return (a_min <= b_max) and (b_min <= a_max)

def price_overlap(a_min: float, a_max: float, b_min: float, b_max: float) -> bool:
    return (a_min <= b_max) and (b_min <= a_max)

def cleanup_expired_trips():
    """Automatically delete trips where the travel date has passed"""
    today_iso = date.today().isoformat()
    
    if col is None:
        # In-memory cleanup
        before = len(st.session_state["_mem_docs"])
        st.session_state["_mem_docs"] = [
            d for d in st.session_state["_mem_docs"]
            if d.get("date") >= today_iso
        ]
        deleted_count = before - len(st.session_state["_mem_docs"])
        if deleted_count > 0:
            st.success(f"✅ Cleaned up {deleted_count} expired trip(s)")
        # else:
            # st.info("ℹ️ No expired trips to clean up")
        return deleted_count
    else:
        # MongoDB cleanup
        try:
            result = col.delete_many({"date": {"$lt": today_iso}})
            if result.deleted_count > 0:
                st.success(f"✅ Cleaned up {result.deleted_count} expired trip(s)")
            # else:
                # st.info("ℹ️ No expired trips to clean up")
            return result.deleted_count
        except Exception as e:
            st.error(f"❌ Error during cleanup: {e}")
            return 0

def save_doc(doc: Dict[str, Any]) -> str:
    if col is None:
        # in-memory
        doc["_id"] = str(len(st.session_state["_mem_docs"]) + 1)
        st.session_state["_mem_docs"].append(doc)
        return doc["_id"]
    result = col.insert_one(doc)
    return str(result.inserted_id)

def delete_doc(doc_id: str, contact: str) -> bool:
    if col is None:
        before = len(st.session_state["_mem_docs"])
        st.session_state["_mem_docs"] = [
            d for d in st.session_state["_mem_docs"]
            if not (str(d.get("_id")) == doc_id and d.get("contact") == contact)
        ]
        return len(st.session_state["_mem_docs"]) < before
    res = col.delete_one({"_id": ObjectId(doc_id), "contact": contact})
    return res.deleted_count == 1

def fetch_by_contact(contact: str) -> List[Dict[str, Any]]:
    if col is None:
        return [d for d in st.session_state["_mem_docs"] if d.get("contact") == contact]
    return list(col.find({"contact": contact}).sort("created_at", -1))


from typing import List, Dict, Any, Optional
from datetime import time as dtime

# ---- Duplicate check helper ----
def doc_exists_for_contact_date_and_route(contact: str, trip_date_iso: str, route_key: str) -> bool:
    """Return True if a document already exists for the same contact, date, and route."""
    try:
        if col is None:
            return any(
                (d.get("contact") == contact and d.get("date") == trip_date_iso and d.get("route_key") == route_key)
                for d in st.session_state.get("_mem_docs", [])
            )
        return col.count_documents({"contact": contact, "date": trip_date_iso, "route_key": route_key}, limit=1) > 0
    except Exception:
        # If the DB check fails for any reason, be conservative and allow insert
        return False

def minutes(t: dtime) -> int:
    return t.hour * 60 + t.minute

def find_matches(
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    trip_date: Optional[str] = None,
    t_from: Optional[dtime] = dtime(0, 0),
    t_to: Optional[dtime] = dtime(23, 59),
    max_results: int = 50
) -> List[Dict[str, Any]]:
    if col is None:
        return []

    # Base query (exact date match on ISO string)
    query: Dict[str, Any] = {}
    if trip_date:
        query["date"] = trip_date

    try:
        docs: List[Dict[str, Any]] = list(col.find(query))
    except Exception as _:
        # Fallback: nothing we can do without DB
        return []

    # Origin/Destination similarity filtering (substring and word overlap)
    if origin or destination:
        origin_lower = origin.lower().strip() if origin else None
        dest_lower = destination.lower().strip() if destination else None

        filtered: List[Dict[str, Any]] = []
        for d in docs:
            score = 0.0
            d_origin = (d.get("origin", "") or "").lower().strip()
            d_dest = (d.get("destination", "") or "").lower().strip()

            if origin_lower:
                if origin_lower in d_origin or d_origin in origin_lower:
                    score += 1.0
                elif any(w and w in d_origin for w in origin_lower.split()):
                    score += 0.5
                elif any(w and w in origin_lower for w in d_origin.split()):
                    score += 0.5

            if dest_lower:
                if dest_lower in d_dest or d_dest in dest_lower:
                    score += 1.0
                elif any(w and w in d_dest for w in dest_lower.split()):
                    score += 0.5
                elif any(w and w in dest_lower for w in d_dest.split()):
                    score += 0.5

            if score > 0:
                d["_similarity_score"] = score
                filtered.append(d)

        docs = filtered

        # Sort by similarity score desc
        docs.sort(key=lambda x: x.get("_similarity_score", 0), reverse=True)

    # Time overlap filter
    if t_from and t_to:
        tA_min = minutes(t_from)
        tA_max = minutes(t_to)
        print(f"debug - {tA_max=}, {tA_min=}")
        for d in docs:
            print(f"{d=}")
        docs = [
            d for d in docs
            # if ((d.get("time_from_minutes") or 0) <= tA_max) and ((d.get("time_to_minutes") or 0) >= tA_min)
            if (d.get("time_from_minutes", 0) <= tA_max) and (d.get("time_to_minutes", 0) >= tA_min)
        ]

        # Add time distance score and sort secondary
        midA = (tA_min + tA_max) / 2.0
        for d in docs:
            midB = (float(d.get("time_from_minutes", 0)) + float(d.get("time_to_minutes", 0))) / 2.0
            d["_time_score"] = abs(midA - midB)

        docs.sort(key=lambda x: (x.get("_time_score", 0), -x.get("_similarity_score", 0)))

    return docs[:max_results]
# ---- UI helpers ----
def route_inputs(prefix: str = ""):
    col1, col2 = st.columns(2)
    with col1:
        o = st.selectbox(f"{prefix}Origin city", CITIES, index=0, key=f"{prefix}orig_city")
        o_other = st.text_input(f"{prefix}Origin (if Other)", key=f"{prefix}orig_other")
    with col2:
        d = st.selectbox(f"{prefix}Destination city", CITIES, index=1, key=f"{prefix}dest_city")
        d_other = st.text_input(f"{prefix}Destination (if Other)", key=f"{prefix}dest_other")
    origin = normalize_city(o, o_other)
    dest = normalize_city(d, d_other)
    return origin, dest

def time_range_inputs(prefix: str = "", default_from: dtime = dtime(0, 0), default_to: dtime = dtime(23, 59)) -> Tuple[dtime, dtime]:
    c1, c2 = st.columns(2)
    with c1:
        t_from = st.time_input(f"{prefix}Earliest time", value=default_from, key=f"{prefix}tfrom")
    with c2:
        t_to = st.time_input(f"{prefix}Latest time", value=default_to, key=f"{prefix}tto")
    if t_to <= t_from:
        st.warning("Latest time should be after earliest time.")
    return t_from, t_to

def price_range_inputs(prefix: str = "", default_min: float = 10.0, default_max: float = 60.0) -> Tuple[float, float]:
    c1, c2 = st.columns(2)
    with c1:
        pmin = st.number_input(f"{prefix}Price min ($)", min_value=0.0, value=default_min, step=1.0, key=f"{prefix}pmin")
    with c2:
        pmax = st.number_input(f"{prefix}Price max ($)", min_value=pmin, value=default_max, step=1.0, key=f"{prefix}pmax")
    return float(pmin), float(pmax)

# ---- Tabs ----
tab_search, tab_post, tab_manage = st.tabs(["Find matches", "Post trip", "Manage my posts"])

# Clean up expired trips on app load
cleanup_expired_trips()

with tab_post:
    st.subheader("Post your trip")
    with st.form("post_form", clear_on_submit=False):
        name = st.text_input("Display name *")
        contact = st.text_input("Phone Number (incl. international code if not US number)")
        email = st.text_input("Email address (optional, for ride match notifications)")
        is_student = st.checkbox("I am a UMass student", value=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            age = st.number_input("Age", min_value=0, max_value=120, value=0, step=1)
        with c2:
            gender = st.selectbox("Gender", GENDERS, index=0)
        with c3:
            bags = st.number_input("Number of bags", min_value=0, max_value=10, value=0, step=1)

        st.markdown("**Route**")
        origin, dest = route_inputs(prefix="post_")
        trip_date = st.date_input("Date", value=date.today())
        trip_date_iso = trip_date.isoformat()
        t_from, t_to = time_range_inputs(prefix="post_", default_from=dtime(0, 0), default_to=dtime(23, 59))
        pmin, pmax = price_range_inputs(prefix="post_")

        exact_loc = st.text_input("Exact pickup/drop details (optional)")
        prefs = st.text_area("Any preferences (text)", placeholder="e.g., quiet ride, okay with music, will book Uber, etc.")
        notify_matches = st.checkbox("Notify me when others post matching rides", value=False, help="You'll receive email notifications when someone posts a ride matching your route and date")

        submit = st.form_submit_button("Post trip")
        if submit:
            if not name or not contact or not origin or not dest:
                st.error("Name, contact, origin, and destination are required.")
            elif t_to <= t_from:
                st.error("Fix time range.")
            else:
                route_key = f"{origin.strip().replace(' ', '').lower()}→{dest.strip().replace(' ', '').lower()}"
                # Duplicate guard: same contact, date, and route already exists
                if doc_exists_for_contact_date_and_route(contact.strip(), trip_date_iso, route_key):
                    st.warning("Data already exists in the database for this phone number, date, and route. Skipping insertion.")
                    st.stop()
                doc = {
                    "name": name.strip(),
                    "contact": contact.strip(),
                    "email": email.strip() if email.strip() else None,
                    "is_student": bool(is_student),
                    "age": int(age) if age else None,
                    "gender": gender,
                    "bags": int(bags),
                    "origin": origin,
                    "destination": dest,
                    "route_key": route_key,
                    "date": trip_date_iso,
                    "time_from": t_from.strftime("%H:%M"),
                    "time_to": t_to.strftime("%H:%M"),
                    "time_from_minutes": int(t_from.hour * 60 + t_from.minute),
                    "time_to_minutes": int(t_to.hour * 60 + t_to.minute),
                    "price_min": float(pmin),
                    "price_max": float(pmax),
                    "exact_location": exact_loc.strip(),
                    "prefs": prefs.strip(),
                    "notify_matches": bool(notify_matches),
                    "created_at": created_at
                }
                _id = save_doc(doc)
                st.success(f"Trip posted successfully!")
                
                # Check for matches and send notifications to users who opted in
                if col is not None:  # Only send notifications if using MongoDB
                    try:
                        check_and_notify_matches(origin, dest, trip_date_iso, contact.strip())
                    except WebSocketClosedError:
                        # The client disconnected; ignore this benign error
                        pass
                    except Exception as _:
                        # Swallow notification errors to avoid interrupting the user flow
                        pass

                with st.expander("See matches now"):
                    matches = find_matches(origin=origin, destination=dest, trip_date=trip_date_iso, t_from=t_from, t_to=t_to)
                    if matches:
                        df = pd.DataFrame([
                            {
                                "Name": m.get("name"),
                                "Date": m.get("date", ""),
                                "Time": f'{m.get("time_from")}–{m.get("time_to")}',
                                "Bags": m.get("bags", 0),
                                "Price ($)": f'{int(m.get("price_min",0))}-{int(m.get("price_max",0))}',
                                "Contact": m.get("contact"),
                                "Prefs": (m.get("prefs") or "")[:120],
                                "Route": f'{m.get("origin")} → {m.get("destination")}',
                            }
                            for m in matches if m.get("_id") != _id
                        ])
                        st.dataframe(df, use_container_width=True, height=360)
                        
                        # Show detailed matches with clickable contacts
                        st.subheader("📱 Contact Details")
                        for m in matches:
                            if m.get("_id") != _id:
                                # Use columns instead of nested expander
                                st.markdown("---")
                                st.markdown(f"**{m.get('name')} - {m.get('time_from')}–{m.get('time_to')}**")
                                
                                col1, col2 = st.columns(2)
                                with col1:
                                    st.write(f"**Route:** {m.get('origin')} → {m.get('destination')}")
                                    bags = m.get('bags', 0)
                                    if should_display_attribute("bags", bags):
                                        st.write(f"**Bags:** {bags}")
                                    st.write(f"**Price:** ${int(m.get('price_min',0))}–{int(m.get('price_max',0))}")
                                with col2:
                                    st.write(f"**Student:** {'Yes' if m.get('is_student') else 'No'}")
                                    age = m.get('age')
                                    if should_display_attribute("age", age):
                                        st.write(f"**Age:** {age}")
                                    gender = m.get('gender')
                                    if should_display_attribute("gender", gender):
                                        st.write(f"**Gender:** {gender}")
                                
                                if m.get('exact_location'):
                                    st.write(f"**Pickup/Drop:** {m.get('exact_location')}")
                                if m.get('prefs'):
                                    st.write(f"**Prefs:** {m.get('prefs')}")
                                
                                # Display contact with clickable phone numbers
                                st.markdown(format_contact_display(m.get("contact")))
                    else:
                        st.info("No matches yet. Check 'Find matches' tab.")

with tab_search:
    st.subheader("Find matches")
    with st.form("search_form"):
        origin_s, dest_s = route_inputs(prefix="search_")
        date_s = st.date_input("Date to travel", value=date.today(), key="search_date")
        t_from_s, t_to_s = time_range_inputs(prefix="search_", default_from=dtime(0, 0), default_to=dtime(23, 59))
        pmin_s, pmax_s = price_range_inputs(prefix="search_", default_min=0.0, default_max=100.0)
        bags_max = st.number_input("Baggage count", min_value=0, max_value=10, value=0, step=1)

        q = st.text_input("Search text in preferences (optional)")
        submitted = st.form_submit_button("Search")

    if submitted:
        # Use the new flexible find_matches function
        results = find_matches(
            origin=origin_s.strip(),
            destination=dest_s.strip(),
            trip_date=date_s.isoformat() if date_s else None,
            t_from=t_from_s,
            t_to=t_to_s,
            # p_min=pmin_s,
            # p_max=pmax_s
        )
        
        if q:
            results = [r for r in results if q.lower() in (r.get("prefs","").lower())]
        if bags_max is not None:
            results = [r for r in results if int(r.get("bags", 0)) <= int(bags_max)]

        if not results:
            st.info("No matches found. Try widening your time/price range, adjusting your origin/destination, or post your trip.")
        else:
            st.caption(f"Found {len(results)} match(es).")
            for r in results:
                date_str = r.get("date", "")
                with st.expander(f'{r.get("name")} · {r.get("origin")} → {r.get("destination")} · {date_str} · {r.get("time_from")}–{r.get("time_to")}'):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        bags = r.get("bags", 0)
                        if should_display_attribute("bags", bags):
                            st.write(f'**Bags:** {bags}')
                        st.write(f'**Student:** {"Yes" if r.get("is_student") else "No"}')
                    with c2:
                        st.write(f'**Price range:** ${int(r.get("price_min",0))}–{int(r.get("price_max",0))}')
                        age = r.get("age")
                        if should_display_attribute("age", age):
                            st.write(f'**Age:** {age}')
                    with c3:
                        gender = r.get("gender")
                        if should_display_attribute("gender", gender):
                            st.write(f'**Gender:** {gender}')

                    if r.get("exact_location"):
                        st.write(f'**Pickup/Drop:** {r.get("exact_location")}')
                    if r.get("prefs"):
                        st.write(f'**Prefs:** {r.get("prefs")}')
                    
                    # Display contact with clickable phone numbers
                    st.markdown(format_contact_display(r.get("contact")))

with tab_manage:
    st.subheader("Manage my posts")
    st.caption("Enter your contact to list your posts. You can delete old ones.")
    
    # Add manual cleanup button
    col1, col2 = st.columns([3, 1])
    with col1:
        contact_m = st.text_input("Your contact (must match what you used in the post)")
    with col2:
        if st.button("🔄 Clean Expired Trips"):
            cleanup_expired_trips()
            st.rerun()
    
    if contact_m:
        my_posts = fetch_by_contact(contact_m.strip())
        if not my_posts:
            st.info("No posts found for this contact.")
        else:
            for p in my_posts:
                date_str = p.get("date", "")
                with st.expander(f'{p.get("origin")} → {p.get("destination")} · {date_str} · {p.get("time_from")}–{p.get("time_to")}'):
                    st.write(f'**Price:** ${int(p.get("price_min",0))}–{int(p.get("price_max",0))}')
                    bags = p.get("bags", 0)
                    if should_display_attribute("bags", bags):
                        st.write(f'**Bags:** {bags}')
                    st.write(f'**Prefs:** {p.get("prefs") or "-"}')
                    if st.button("Delete this post", key=f"del_{p.get('_id')}"):
                        ok = delete_doc(str(p.get("_id")), contact_m.strip())
                        if ok:
                            st.success("Deleted.")
                        else:
                            st.error("Delete failed. Contact must match.")
                            st.stop()
                        st.rerun()

st.markdown("---")
st.caption("Tip: Use the same contact each time so you can manage your posts. If its an international number, prefix the international code, for eg. for Indian numbers - +91 91111 11111 enter 919111111111")

st.markdown("---")
st.warning("⚠️ **Important:** Records with 'test' in the name or email were created for testing purposes only. Please ignore these test records and only reach out to non-test users for actual ride sharing.")