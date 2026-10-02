# AutoMM Website

Login + unique User ID + Create MM + automatic Litecoin payment (Apirone).

## Setup
1. `pip install -r requirements.txt`
2. `.env.example` ko `.env` naam se copy karo aur values bharo
   (`SECRET_KEY`, `APIRONE_ACCOUNT`, `APIRONE_TRANSFER_KEY`)
3. `python app.py`  ->  http://127.0.0.1:5000
4. Pehle khud register karo, phir admin banao:
   `python app.py make-admin <tumhara_username>`

## Flow
1. User register karta hai -> unique User ID milta hai (U-XXXXXXXX)
2. Create MM -> partner ki User ID, amount (USD), description
3. Partner accept kare -> LTC amount lock + naya deposit address
4. Buyer pay kare -> server har 30 sec me check karta hai, confirm hote hi "Funds locked"
5. Seller payout address daalta hai, buyer Release dabata hai -> seller ko payout
6. Problem ho to Dispute -> funds freeze, admin (Staff page) release ya refund karta hai

## Production
- Sirf ek worker chalao (poller ek hi hona chahiye):
  `gunicorn -w 1 --threads 4 -b 127.0.0.1:8000 app:app`
- HTTPS lagao (nginx/Caddy) aur `.env` me `COOKIE_SECURE=1` karo
- `data/automm.db` ka regular backup lo
- `.env` aur transfer key kisi ko mat do

## Files
- `app.py`               routes, database, background payment checker
- `apirone_payment.py`   Apirone: address, deposit check, payout
- `templates/`, `static/`  pages, CSS, JS (icons inline SVG hain, emoji nahi)
