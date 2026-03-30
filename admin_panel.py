import os
import csv
import zipfile
import io
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from models import db, User, Registration, NewsletterSubscriber, ContactMessage
from config import Config
from datetime import datetime

# Configuración de la aplicación
admin_app = Flask(__name__)
admin_app.config.from_object(Config)
admin_app.config['SECRET_KEY'] = os.environ.get('ADMIN_SECRET_KEY', 'clave-super-secreta-cambiar')
admin_app.config['SQLALCHEMY_DATABASE_URI'] = Config.SQLALCHEMY_DATABASE_URI  # mismo DB que app principal

# Inicializar la base de datos
db.init_app(admin_app)

# Credenciales del administrador (usar variables de entorno)
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD_HASH = generate_password_hash(os.environ.get('ADMIN_PASSWORD', 'admin123'))

# Decorador para requerir login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Por favor inicia sesión para acceder al panel.', 'warning')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# Rutas de autenticación
@admin_app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['logged_in'] = True
            flash('Bienvenido al panel de administración.', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Credenciales incorrectas.', 'danger')
    return render_template('admin/login.html')

@admin_app.route('/admin/logout')
def admin_logout():
    session.pop('logged_in', None)
    flash('Has cerrado sesión.', 'info')
    return redirect(url_for('admin_login'))

# Dashboard principal (lista de registros)
@admin_app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    # Filtros opcionales
    status = request.args.get('status', 'all')
    query = Registration.query
    if status == 'paid':
        query = query.filter_by(payment_status='paid')
    elif status == 'pending':
        query = query.filter_by(payment_status='pending')
    registrations = query.order_by(Registration.created_at.desc()).all()
    return render_template('admin/dashboard.html', registrations=registrations, status_filter=status)

# Exportar registros a CSV
@admin_app.route('/admin/export/csv')
@login_required
def export_csv():
    registrations = Registration.query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    # Cabeceras
    writer.writerow(['ID', 'Usuario', 'Email', 'Rol', 'Tipo ticket', 'Días', 'Virtual Día1', 'Curso', 'Monto', 'Estado pago', 'Fecha creación', 'QR'])
    for reg in registrations:
        user = User.query.get(reg.user_id)
        writer.writerow([
            reg.id,
            user.name,
            user.email,
            user.role,
            reg.ticket_type,
            reg.days,
            reg.day1_virtual,
            reg.course,
            reg.amount,
            reg.payment_status,
            reg.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            reg.qr_code_path
        ])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8')),
                     mimetype='text/csv',
                     as_attachment=True,
                     download_name=f'registros_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')

# Descargar todos los códigos QR en un ZIP
@admin_app.route('/admin/export/qr')
@login_required
def export_qr():
    # Ruta donde se guardan los QR (relativa al root del proyecto)
    qr_dir = os.path.join(admin_app.root_path, 'static', 'qrcodes')
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename in os.listdir(qr_dir):
            if filename.endswith('.png'):
                file_path = os.path.join(qr_dir, filename)
                zf.write(file_path, arcname=filename)
    memory_file.seek(0)
    return send_file(memory_file,
                     mimetype='application/zip',
                     as_attachment=True,
                     download_name=f'qrcodes_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip')

# Respaldar la base de datos (descargar archivo .db)
@admin_app.route('/admin/backup')
@login_required
def backup_db():
    # Obtener la ruta de la base de datos desde la configuración
    db_uri = admin_app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('sqlite:///'):
        db_path = db_uri.replace('sqlite:///', '')
        if os.path.exists(db_path):
            return send_file(db_path,
                             as_attachment=True,
                             download_name=f'backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db')
    flash('No se pudo localizar el archivo de base de datos.', 'danger')
    return redirect(url_for('admin_dashboard'))

# Ver mensajes de contacto
@admin_app.route('/admin/messages')
@login_required
def admin_messages():
    messages = ContactMessage.query.order_by(ContactMessage.created_at.desc()).all()
    return render_template('admin/messages.html', messages=messages)

# Ver suscriptores del newsletter
@admin_app.route('/admin/subscribers')
@login_required
def admin_subscribers():
    subscribers = NewsletterSubscriber.query.order_by(NewsletterSubscriber.created_at.desc()).all()
    return render_template('admin/subscribers.html', subscribers=subscribers)

if __name__ == '__main__':
    admin_app.run(debug=True)
