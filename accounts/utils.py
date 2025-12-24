# accounts/utils.py
import pyotp
import qrcode
import base64
from io import BytesIO
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import secrets
import string

def generate_otp_secret():
    """Generate a new OTP secret key"""
    return pyotp.random_base32()

def generate_otp_token(secret):
    """Generate OTP token using secret"""
    totp = pyotp.TOTP(secret, interval=300)  # 5 minutes validity
    return totp.now()

def verify_otp_token(secret, token):
    """Verify OTP token"""
    totp = pyotp.TOTP(secret, interval=300)
    return totp.verify(token)

def generate_qr_code_data(username, secret, issuer_name="ISP Management"):
    """Generate QR code data for 2FA setup"""
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=username, issuer_name=issuer_name)
    
    # Generate QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    return img_str, provisioning_uri

def send_otp_email(user_email, otp_token, username=None):
    """Send OTP token to user's email"""
    subject = f"Your One-Time Password (OTP) for ISP Management"
    username_display = username or "User"
    
    message = f"""
    Hello {username_display},
    
    Your One-Time Password (OTP) for two-factor authentication is:
    
    🔐 {otp_token}
    
    This OTP is valid for 5 minutes.
    
    If you didn't request this OTP, please ignore this email or contact support.
    
    Best regards,
    ISP Management Team
    """
    
    html_message = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .otp-box {{ 
                background-color: #f4f4f4; 
                padding: 20px; 
                text-align: center; 
                font-size: 32px; 
                font-weight: bold; 
                letter-spacing: 5px;
                margin: 20px 0;
                border-radius: 8px;
            }}
            .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Hello {username_display},</h2>
            <p>Your One-Time Password (OTP) for two-factor authentication is:</p>
            
            <div class="otp-box">
                🔐 {otp_token}
            </div>
            
            <p><strong>This OTP is valid for 5 minutes.</strong></p>
            
            <p>If you didn't request this OTP, please ignore this email or contact support.</p>
            
            <div class="footer">
                <p>Best regards,<br>ISP Management Team</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@ispmanagement.com'),
            recipient_list=[user_email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Error sending OTP email: {e}")
        return False

def generate_backup_codes(count=10):
    """Generate backup codes for 2FA"""
    backup_codes = []
    for _ in range(count):
        code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        backup_codes.append(code)
    return backup_codes