"""Formularios de autenticación."""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError
from app.models.usuario import Usuario


class LoginForm(FlaskForm):
    login    = StringField('Email o usuario', validators=[DataRequired(), Length(max=120)])
    password = PasswordField('Contraseña', validators=[DataRequired()])
    remember = BooleanField('Recordarme')
    submit   = SubmitField('Ingresar')


class RegistroForm(FlaskForm):
    nombre   = StringField('Nombre completo', validators=[DataRequired(), Length(max=100)])
    username = StringField('Usuario', validators=[DataRequired(), Length(min=3, max=50)])
    email    = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('Contraseña', validators=[DataRequired(), Length(min=8)])
    confirm  = PasswordField('Confirmar contraseña', validators=[
        DataRequired(), EqualTo('password', message='Las contraseñas no coinciden.')
    ])
    submit   = SubmitField('Registrarse')

    def validate_email(self, field):
        if Usuario.query.filter_by(email=field.data.lower()).first():
            raise ValidationError('Este email ya está registrado.')

    def validate_username(self, field):
        if Usuario.query.filter_by(username=field.data.lower()).first():
            raise ValidationError('Este nombre de usuario ya está en uso.')
