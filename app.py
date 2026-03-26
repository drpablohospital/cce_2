import os
import stripe
import qrcode
import random
from glob import glob
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from config import Config
from models import db, User, Registration, NewsletterSubscriber, ContactMessage
from datetime import datetime
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import mm, cm
from PIL import Image

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

# Configuración de correo
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'medicinacriticasjdr@gmail.com'
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
mail = Mail(app)

stripe.api_key = app.config['STRIPE_SECRET_KEY']

with app.app_context():
    db.create_all()

# ------------------------- HELPER FUNCTIONS -------------------------
def get_random_background():
    """Devuelve la URL de una imagen de fondo aleatoria de static/images/ que empiece con 'fondo'."""
    bg_folder = os.path.join(app.static_folder, 'images')
    patterns = ['fondo*', 'Fondo*']
    backgrounds = []
    for pattern in patterns:
        backgrounds.extend(glob(os.path.join(bg_folder, pattern)))
    if not backgrounds:
        # fallback si no hay imágenes de fondo
        return url_for('static', filename='images/fondo1.webp')
    chosen = random.choice(backgrounds)
    rel_path = os.path.relpath(chosen, app.static_folder).replace('\\', '/')
    return url_for('static', filename=rel_path)

def generate_qr(registration_id):
    """Genera el código QR con la URL completa del dominio."""
    base_url = os.environ.get('BASE_URL')
    if not base_url:
        base_url = request.host_url if request else 'http://localhost:5000'
    if not base_url.endswith('/'):
        base_url += '/'

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(f"{base_url}verify/{registration_id}")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    filename = f"qr_{registration_id}.png"
    qrcode_dir = os.path.join(app.static_folder, 'qrcodes')
    os.makedirs(qrcode_dir, exist_ok=True)
    path = os.path.join(qrcode_dir, filename)
    img.save(path)
    return f"static/qrcodes/{filename}"

def send_virtual_instructions(email, name):
    """Envía correo con instrucciones para el acceso virtual."""
    msg = Message('Instrucciones para acceso virtual - Critical Care Experience',
                  sender=app.config['MAIL_USERNAME'],
                  recipients=[email])
    msg.body = f"""
Hola {name},

Gracias por registrarte al Critical Care Experience.

Has seleccionado la modalidad VIRTUAL para el Día 1. El acceso a la transmisión en vivo será a través de la siguiente plataforma:

[Enlace de Zoom/YouTube]

Fecha: 1 de mayo 2026
Horario: 8:30 - 17:40

Recuerda que tu código QR es tu credencial digital; lo necesitarás para acceder al evento virtual.

Si tienes dudas, responde a este correo.

¡Te esperamos!
Equipo Critical Care Experience
"""
    try:
        mail.send(msg)
    except Exception as e:
        app.logger.error(f"Error enviando email a {email}: {e}")

def generate_certificate(registration_id):
    """Genera un PDF tipo credencial de tamaño estándar (600x900 pt)."""
    reg = Registration.query.get(registration_id)
    if not reg or reg.payment_status != 'paid':
        return None

    user = User.query.get(reg.user_id)

    # Dimensiones del canvas (tamaño de ID vertical, aprox 8.3cm x 12.5cm)
    width, height = 600, 900  # puntos
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(width, height))

    # Cargar imagen de fondo
    bg_path = os.path.join(app.static_folder, 'images', 'credential_bg.webp')
    if not os.path.exists(bg_path):
        bg_path = os.path.join(app.static_folder, 'images', 'credential_bg.png')

    # Escalar la imagen de fondo para que ocupe todo el canvas
    try:
        from reportlab.lib.utils import ImageReader
        bg_img = ImageReader(bg_path)
        c.drawImage(bg_img, 0, 0, width=width, height=height, preserveAspectRatio=False)
    except Exception:
        # Si no hay fondo, usar un color de respaldo
        c.setFillColorRGB(0.95, 0.95, 0.95)
        c.rect(0, 0, width, height, fill=1)

    # Configurar fuente
    c.setFont("Helvetica-Bold", 14)
    c.setFillColorRGB(0, 0, 0)

    # Coordenadas relativas (ajusta según el diseño de tu fondo)
    name_y = height - 180
    role_y = name_y - 40
    items_y = role_y - 50
    qr_size = 150
    qr_x = width - qr_size - 20
    qr_y = 20

    # Nombre
    c.drawString(40, name_y, f"Nombre: {user.name}")

    # Rol
    role_str = {
        "specialist": "Especialista",
        "student": "Residente",
        "nurse": "Enfermero/a",
        "physio": "Fisioterapeuta"
    }.get(user.role, user.role)
    c.drawString(40, role_y, f"Rol: {role_str}")

    # Eventos incluidos
    items = []
    if reg.days == "day1":
        modality = "Virtual" if reg.day1_virtual else "Presencial"
        items.append(f"Día 1 (Conferencias) - {modality}")
    elif reg.days == "day2":
        items.append("Día 2 (Talleres) - Presencial")
    elif reg.days == "both":
        modality = "Virtual" if reg.day1_virtual else "Presencial"
        items.append(f"Día 1 (Conferencias) - {modality}")
        items.append("Día 2 (Talleres) - Presencial")
    if reg.course:
        items.append("Curso de Fisioterapia")

    if items:
        c.setFont("Helvetica", 10)
        c.drawString(40, items_y, "Incluye:")
        y_offset = items_y - 20
        for item in items:
            c.drawString(40, y_offset, f"• {item}")
            y_offset -= 15

    # Fecha del evento
    c.setFont("Helvetica", 8)
    c.drawString(40, 50, "1 y 2 de mayo 2026 · Hospital General de San Juan del Río")

    # Insertar QR
    if reg.qr_code_path:
        qr_full_path = os.path.join(app.root_path, reg.qr_code_path)
        if os.path.exists(qr_full_path):
            c.drawImage(ImageReader(qr_full_path), qr_x, qr_y, width=qr_size, height=qr_size)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

# ------------------------- RUTAS -------------------------
@app.route('/')
def index():
    return render_template('index.html', background_image=get_random_background())

@app.route('/program')
def program():
    return render_template('program.html', background_image=get_random_background())

@app.route('/info')
def info():
    return render_template('info.html', background_image=get_random_background())

@app.route('/purchase', methods=['GET', 'POST'])
def purchase():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        role = request.form['role']
        day1 = 'day1' in request.form
        day2 = 'day2' in request.form
        course = 'course' in request.form
        day1_virtual = request.form.get('day1_modality') == 'virtual' if day1 else False

        PRICES = {
            'day1_presencial': 200000,
            'day1_virtual': 100000,
            'day2': 225000,
            'course': 60000
        }

        discount = 1.0 if role == 'specialist' else 0.7

        amount = 0
        days_selected = None

        if day1 and day2:
            days_selected = "both"
            day1_price = PRICES['day1_virtual'] if day1_virtual else PRICES['day1_presencial']
            amount = day1_price + PRICES['day2']
        elif day1:
            days_selected = "day1"
            amount = PRICES['day1_virtual'] if day1_virtual else PRICES['day1_presencial']
        elif day2:
            days_selected = "day2"
            amount = PRICES['day2']
        else:
            days_selected = None

        if days_selected:
            amount = int(amount * discount)

        if course:
            amount += PRICES['course']

        if not day1 and not day2 and course:
            days_selected = None
            ticket_type = "course"
        else:
            ticket_type = "days"

        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(name=name, email=email, role=role)
            db.session.add(user)
            db.session.commit()
        else:
            user.name = name
            db.session.commit()

        reg = Registration(
            user_id=user.id,
            ticket_type=ticket_type,
            days=days_selected,
            day1_virtual=day1_virtual,
            course=course,
            amount=amount,
            payment_status='pending'
        )
        db.session.add(reg)
        db.session.commit()

        try:
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'mxn',
                        'unit_amount': amount,
                        'product_data': {
                            'name': f'Critical Care Experience',
                        },
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=url_for('success', registration_id=reg.id, _external=True),
                cancel_url=url_for('cancel', _external=True),
                metadata={
                    'registration_id': reg.id
                }
            )
            reg.stripe_checkout_id = checkout_session.id
            db.session.commit()
            return redirect(checkout_session.url, code=303)
        except Exception as e:
            flash(f'Error creating payment session: {str(e)}', 'danger')
            return redirect(url_for('purchase'))

    return render_template('purchase.html', background_image=get_random_background())

@app.route('/success/<int:registration_id>')
def success(registration_id):
    reg = Registration.query.get_or_404(registration_id)
    if reg.payment_status != 'paid':
        flash('Tu pago se está verificando. El código QR aparecerá en breve.', 'info')
        return render_template('success.html', registration=reg, qr_path=None, background_image=get_random_background())
    else:
        return render_template('success.html', registration=reg, qr_path=reg.qr_code_path, background_image=get_random_background())

@app.route('/cancel')
def cancel():
    return render_template('cancel.html', background_image=get_random_background())

@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, app.config['STRIPE_WEBHOOK_SECRET']
        )
    except ValueError:
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError:
        return 'Invalid signature', 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        registration_id = session['metadata']['registration_id']
        reg = Registration.query.get(registration_id)
        if reg and reg.payment_status == 'pending':
            reg.payment_status = 'paid'
            qr_path = generate_qr(reg.id)
            reg.qr_code_path = qr_path
            db.session.commit()

            # Enviar correo si es virtual
            if reg.day1_virtual and reg.days in ('day1', 'both'):
                user = User.query.get(reg.user_id)
                send_virtual_instructions(user.email, user.name)

    return '', 200

@app.route('/certificate/<int:registration_id>')
def certificate(registration_id):
    reg = Registration.query.get_or_404(registration_id)
    if reg.payment_status != 'paid':
        flash('El certificado solo está disponible después del pago.', 'warning')
        return redirect(url_for('index'))
    pdf_buffer = generate_certificate(registration_id)
    if not pdf_buffer:
        flash('Error generando el certificado.', 'danger')
        return redirect(url_for('index'))
    return send_file(pdf_buffer, as_attachment=True, download_name=f'certificate_{registration_id}.pdf', mimetype='application/pdf')

@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = request.form.get('email')
    if email:
        existing = NewsletterSubscriber.query.filter_by(email=email).first()
        if not existing:
            sub = NewsletterSubscriber(email=email)
            db.session.add(sub)
            db.session.commit()
            flash('¡Gracias por suscribirte!', 'success')
        else:
            flash('Ya estás suscrito.', 'info')
    else:
        flash('Por favor ingresa un correo.', 'danger')
    return redirect(request.referrer or url_for('index'))

@app.route('/verify/<int:registration_id>')
def verify(registration_id):
    reg = Registration.query.get_or_404(registration_id)
    if reg.payment_status != 'paid':
        return "Acceso no autorizado", 403
    user = User.query.get(reg.user_id)
    info = {
        'name': user.name,
        'email': user.email,
        'role': user.role,
        'ticket_type': reg.ticket_type,
        'days': reg.days,
        'day1_virtual': reg.day1_virtual,
        'course': reg.course,
        'amount': reg.amount / 100
    }
    return render_template('verify.html', info=info, registration=reg, background_image=get_random_background())

@app.route('/contact', methods=['POST'])
def contact():
    nombre = request.form.get('nombre')
    telefono = request.form.get('telefono')
    email = request.form.get('email')
    mensaje = request.form.get('mensaje')

    msg_db = ContactMessage(nombre=nombre, telefono=telefono, email=email, mensaje=mensaje)
    db.session.add(msg_db)
    db.session.commit()

    try:
        msg = Message('Nuevo mensaje desde Critical Care Experience',
                      sender=app.config['MAIL_USERNAME'],
                      recipients=['medicinacriticasjdr@gmail.com'])
        msg.body = f"""
        Nombre: {nombre}
        Teléfono: {telefono}
        Email: {email}
        Mensaje: {mensaje}
        """
        mail.send(msg)
        flash('Mensaje enviado con éxito. Te contactaremos pronto.', 'success')
    except Exception as e:
        flash('Hubo un error al enviar el mensaje. Por favor inténtalo más tarde.', 'danger')
        print(e)
    return redirect(request.referrer or url_for('index'))

@app.route('/carousel-images')
def carousel_images():
    """Endpoint para obtener las imágenes del carrusel dinámicamente."""
    carousel_dir = os.path.join(app.static_folder, 'images', 'carrusel')
    if not os.path.exists(carousel_dir):
        return jsonify([])
    extensions = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
    images = []
    for filename in os.listdir(carousel_dir):
        if os.path.splitext(filename)[1].lower() in extensions:
            images.append(url_for('static', filename=f'images/carrusel/{filename}'))
    return jsonify(images)

if __name__ == '__main__':
    app.run(debug=True)
