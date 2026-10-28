import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from .store import db, now


DEVELOPMENT_WARNING = 'Development mode: unauthenticated API access has administrator permissions. Set POSTURE_AUTH_MODE=strict for deployment.'


def auth_mode():
    mode = os.environ.get('POSTURE_AUTH_MODE', 'strict').strip().lower()
    if mode not in ('strict', 'development'):
        raise RuntimeError('POSTURE_AUTH_MODE must be strict or development')
    return mode


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return salt + ':' + value


def check_password(password, stored):
    try:
        return hmac.compare_digest(hash_password(password, stored.split(':')[0]), stored)
    except (ValueError, TypeError):
        return False


def initialize_admin():
    password = os.environ.get('POSTURE_ADMIN_PASSWORD', '')
    if len(password) < 16:
        raise RuntimeError('POSTURE_ADMIN_PASSWORD must contain at least 16 characters')
    name = os.environ.get('POSTURE_ADMIN_USER', 'admin')
    if not db.users.find_one({'_id': name}):
        db.users.insert_one({'_id': name, 'username': name, 'password_hash': hash_password(password),
                             'role': 'admin', 'created_at': now()})


def principal(request: Request, device=False):
    auth = request.headers.get('authorization', '')
    token = request.cookies.get('posture_session', '')
    if not auth and not token and auth_mode() == 'development':
        request.state.auth_bypassed = True
        return {'username': 'development', 'role': 'admin', 'unauthenticated': True}
    expected = os.environ.get('POSTURE_INGEST_TOKEN', '')
    if device and len(expected) >= 24 and auth.startswith('Bearer ') and hmac.compare_digest(auth[7:], expected):
        return {'username': 'ros-bridge', 'role': 'device'}
    session = db.auth_sessions.find_one({'_id': hashlib.sha256(token.encode()).hexdigest(),
                                       'expires_at': {'$gt': datetime.now(timezone.utc)}}) if token else None
    if not session:
        raise HTTPException(401, 'Inicia sesión para continuar.')
    user = db.users.find_one({'_id': session['username']})
    if not user:
        raise HTTPException(401, 'La cuenta ya no existe.')
    return {'username': user['username'], 'role': user['role']}


def admin(request: Request):
    user = principal(request)
    if user['role'] != 'admin':
        raise HTTPException(403, 'Se requiere una cuenta administradora.')
    return user


def editor(request: Request):
    user = principal(request, device=True)
    if user['role'] not in ('admin', 'device'):
        raise HTTPException(403, 'Sin permiso de escritura.')
    return user


def login(username, password, request, response):
    key = hashlib.sha256(f'{request.client.host}:{username}'.encode()).hexdigest()
    throttle = db.login_attempts.find_one({'_id': key})
    if throttle and throttle.get('locked_until', 0) > datetime.now(timezone.utc).timestamp():
        raise HTTPException(429, 'Demasiados intentos. Espera unos minutos.')
    user = db.users.find_one({'_id': username})
    if not user or not check_password(password, user['password_hash']):
        tries = (throttle or {}).get('tries', 0) + 1
        db.login_attempts.update_one({'_id': key}, {'$set': {'tries': tries,
            'locked_until': datetime.now(timezone.utc).timestamp() + (300 if tries >= 5 else 0)}}, upsert=True)
        raise HTTPException(401, 'Usuario o contraseña incorrectos.')
    db.login_attempts.delete_one({'_id': key})
    token = secrets.token_urlsafe(48)
    db.auth_sessions.insert_one({'_id': hashlib.sha256(token.encode()).hexdigest(), 'username': username,
        'expires_at': datetime.now(timezone.utc) + timedelta(hours=12)})
    response.set_cookie('posture_session', token, httponly=True, samesite='strict', max_age=43200,
        secure=(os.getenv('POSTURE_COOKIE_SECURE', 'false').lower() == 'true'
                or request.url.scheme == 'https' or request.headers.get('x-forwarded-proto') == 'https'))
    return {'username': username, 'role': user['role']}
