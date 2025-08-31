# UMass Ride Share (Streamlit + MongoDB)

A quick web app to match students sharing rides between Amherst ↔ Boston/NYC.

## Features
- Post your trip (date, time range, price range, bags, prefs, contact).
- Find matches with overlapping time and price ranges on the same route/day.
- Manage (list/delete) your posts by contact.

## Setup

1. **Clone files**
   ```bash
   unzip umass_ride_share.zip -d umass_ride_share
   cd umass_ride_share
   ```

2. **Install deps**
   ```bash
   uv sync
   ```

3. **MongoDB**
   - Create a MongoDB Atlas cluster (or use local MongoDB).
   - Allow network access to your IP.
   - Create a `.env` and set `MONGODB_URI` and `DB_NAME`.

4. **Run**
   ```bash
   streamlit run app.py
   ```

5. **Demo without MongoDB**
   - If `MONGODB_URI` is not set, the app runs with an in-memory list (data resets on refresh).

## Notes
- Matching requires same **route** and **date**, overlapping **time** and **price** ranges.
- Contact is shown so students can coordinate directly.
- Minimal schema; extend as needed (e.g., add verification, NetID login, map pickers).