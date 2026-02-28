"""Tests de cálculos IGV — Fase 8."""
from decimal import Decimal
import pytest
from app.services.utils import calcular_igv_item, number_to_words_es


def test_gravado_18_percent():
    resultado = calcular_igv_item(Decimal('118.00'), Decimal('1'), '10')
    assert resultado['precio_sin_igv'] == Decimal('100.00')
    assert resultado['igv_unitario'] == Decimal('18.00')
    assert resultado['subtotal_sin_igv'] == Decimal('100.00')
    assert resultado['igv_total'] == Decimal('18.00')
    assert resultado['subtotal_con_igv'] == Decimal('118.00')


def test_exonerado_zero_igv():
    resultado = calcular_igv_item(Decimal('100.00'), Decimal('2'), '20')
    assert resultado['igv_unitario'] == Decimal('0.00')
    assert resultado['igv_total'] == Decimal('0.00')
    assert resultado['precio_sin_igv'] == Decimal('100.00')


def test_inafecto_zero_igv():
    resultado = calcular_igv_item(Decimal('50.00'), Decimal('3'), '30')
    assert resultado['igv_total'] == Decimal('0.00')
    assert resultado['subtotal_con_igv'] == Decimal('150.00')


def test_rounding_precision():
    resultado = calcular_igv_item(Decimal('10.00'), Decimal('1'), '10')
    precio_sin = resultado['precio_sin_igv']
    igv = resultado['igv_unitario']
    assert precio_sin + igv == Decimal('10.00')


def test_number_to_words_simple():
    assert 'MIL QUINCE' in number_to_words_es(Decimal('1015.00'))
    assert '00/100 SOLES' in number_to_words_es(Decimal('1015.00'))


def test_number_to_words_centavos():
    result = number_to_words_es(Decimal('100.50'))
    assert '50/100 SOLES' in result
