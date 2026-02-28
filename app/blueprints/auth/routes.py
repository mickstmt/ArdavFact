"""Rutas de autenticación: login, registro, logout."""
from datetime import datetime
from flask import render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db, limiter
from app.models.usuario import Usuario
from . import auth_bp
from .forms import LoginForm, RegistroForm


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = LoginForm()
    if form.validate_on_submit():
        login_input = form.login.data.strip().lower()
        usuario = (
            Usuario.query.filter_by(email=login_input).first()
            or Usuario.query.filter_by(username=login_input).first()
        )

        if usuario and usuario.activo and usuario.check_password(form.password.data):
            login_user(usuario, remember=form.remember.data)
            usuario.ultimo_login = datetime.utcnow()
            usuario.ip_registro = request.remote_addr
            db.session.commit()

            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard.index'))

        flash('Email/usuario o contraseña incorrectos.', 'danger')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/registro', methods=['GET', 'POST'])
@limiter.limit('3 per hour')
def registro():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = RegistroForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        authorized = current_app.config.get('AUTHORIZED_EMAILS', [])

        if authorized and email not in authorized:
            flash('Este email no está autorizado para registrarse.', 'danger')
            return render_template('auth/registro.html', form=form)

        usuario = Usuario(
            nombre=form.nombre.data.strip(),
            username=form.username.data.strip().lower(),
            email=email,
            activo=True,
        )
        usuario.set_password(form.password.data)
        db.session.add(usuario)
        db.session.commit()

        flash('Cuenta creada. Ya puedes iniciar sesión.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/registro.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sesión cerrada correctamente.', 'info')
    return redirect(url_for('auth.login'))
